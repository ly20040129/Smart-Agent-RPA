# -*- coding: utf-8 -*-
"""网店管家审单决策模块（第四版，按用户 2026-11-06 批注修正）

输入：订单导出表（订单 + 订单明细）、总库存表、仓库快递对接表
输出：audit_result.json（影刀消费）、审核清单.xlsx、审单规则清单.xlsx、回传摘要.txt

第四版修正点（依据：用户批注 + 11-11 新导出表）
1. R01 发票单 → 发货仓固定「发票仓-财务」，快递保持原值（不再"原值不动"）
2. R02 权益/预约/补差价/补运费单 → 不审核，进待定（后续正常都会取消）
3. R19 主子单 → 每个子单按它自己的货品定仓定快递（机器单与耗材子单分开），
   赠品只加主单；修复 JY2611050714 被套成机器快递的问题
4. R17 赠品按库存品名模糊匹配；匹配不唯一/缺货 → 剔除赠品，主商品照审
5. R02b 无货品编码但货品摘要有机型 → 按摘要机型定仓，进可审并标注「未校验库存」
6. 机型匹配改为「摘要中最早出现的机型」优先，避免 752/664 同串冲突
7. R25 整单退款（新「退款状态」列）→ 不审，进待定 —— 解决"被取消订单无法识别"
8. R03 延期备注补「到货审」；备注含「可以发」视为解除延期
9. 订单表自适应：新单sheet合并格式（订单+明细一行）/ 旧双sheet格式均可
10. R11/R12 机型匹配不上/冲突 → 默认深圳仓+深圳仓-韵达快递，不再进疑问
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:                     # 影刀运行时提供 xbot.print；本地运行走内置 print
    from xbot import print
except Exception:
    pass

import openpyxl

# ---------------- 配置区（业务规则变动先改这里） ----------------
STRICT_STOCK = True              # 可用量 = 库存量 - 不良品 - 待发量
ALLOW_FALLBACK = False           # 预留：首选仓缺货是否换仓

# 编号分类前缀（v6 撤回 1./2./3./4. 兼容——和 v5 保持一致，排除干扰变量）
MACHINE_PREFIX = ("01.",)
CONSUMABLE_PREFIX = ("02.", "03.")
GIFT_PREFIX = ("04.",)

# R01：发票/专票单
INVOICE_WAREHOUSE = ["发票仓-财务"]
INVOICE_KEYWORDS = ["数电专票"]
INVOICE_TARGET_WH = "发票仓-财务"

# R02：权益/预约/补差价单（无真实货品，审单只走流程）
PLACEHOLDER_KEYWORDS = ["预约", "权益", "单拍不发货", "补差价", "补运费",
                        "邮费专用链接", "补专票税点", "补税点", "补邮费"]

# R20：退货仓新机 —— 只读订单导出表的「标记」字段，不硬编码订单号
RETURN_NEW_MACHINE_KEYWORDS = ["退货仓新机"]

# R24：买家/客服明确说不发货、退差价、退前一台 → 待定，不审
CANCEL_KEYWORDS = [
    "不发货", "不发", "不要了", "取消", "退差价", "退前一台", "退之前的",
    "退单", "退机器", "退打印机", "拒收", "不要了",
]

# R13 机器快递（11-11 批注修正）：合捷仓→合捷仓顺丰；深圳仓机器→韵达（同耗材）
LOGISTICS_MACHINE = {"合捷仓": "合捷仓顺丰", "深圳仓": "深圳仓-韵达快递",
                     "退货仓": "深圳仓-韵达快递"}

# R22：跨境单 —— 店铺名含「跨境」（如 添美办公跨境供货商）走国际，
#      机器按《机器发货仓》定仓（合捷仓 + 合捷仓顺丰）；同一原始单号/分销单号拆出的另一单是耗材 → 深圳仓 + 韵达
CROSS_BORDER_SHOP_KEYWORDS = ["跨境", "国际"]
HEJIE_WAREHOUSE = "合捷仓"
LOGISTICS_SUPPLY_DEFAULT = "深圳仓-韵达快递"
LOGISTICS_SUPPLY_SF = "顺丰快递（平湖标快）"
SF_KEYWORD = "指定顺丰"

# 延期/暂停发货：命中即不审；备注含「可以发」视为解除延期，照常审
DEFER_PATTERNS = [
    r"延迟", r"延期", r"等客户通知", r"等通知", r"通知发货", r"暂不发", r"先不发", r"说不发",
    r"到货(再)?审", r"\d{1,2}月\d{1,2}[号日]", r"\d{1,2}[号日]\s*(左右)?\s*发", r"\d{1,2}\.\d{1,2}\s*发",
]
DEFER_RELEASE_KEYWORDS = ["可以发", "能发", "正常发", "放行"]

# 赠品需求识别词：备注出现即视为要加（不再要求「送/赠」动词）
GIFT_SUBJECTS = ["硒鼓", "碳粉", "墨粉", "墨水", "墨盒", "A3纸", "A4纸", "筋膜枪", "筋膜",
                 "吸尘器", "吸尘", "榨汁杯", "礼品", "赠品", "U盘", "打印线", "转换插头",
                 "芯片", "鼠标垫"]

# 店铺前缀 → 名称关键词：赠品多候选时用来消歧（如「天天送榨汁杯」→ TT-榨汁杯）
SHOP_PREFIX_MAP = {"TT": ["天天"], "JD": ["京东"], "PD": ["拼多"],
                   "TB": ["淘宝"], "TM": ["天猫"], "HF": ["惠宝"], "KY": ["康云"]}

# 规则清单（输出给业务校对；第四版按用户 2026-11-06 批注）
RULES_DOC = [
    ("R01", "专票/发票单", "仓库=发票仓-财务 或 货品摘要含「数电专票」",
     "可审；发货仓固定「发票仓-财务」，快递保持原值", "用户 11-06 确认"),
    ("R02", "权益/预约/补差价单", "订单明细无货品编码，且摘要/备注含「预约/权益/补差价/补运费/单拍不发货」",
     "不审，进待定队列（后续正常都会取消）", "用户 11-11 确认：不审核"),
    ("R02b", "无编码但有货品", "订单明细无编码，但货品摘要有真实货品",
     "按摘要机型定仓，进可审；不校验库存，标注待补编码", "新增（编码待业务协商）"),
    ("R03", "延期发货", "备注含「延迟/延期/等通知/等客户通知/先不发/暂不发/X号发/X月X号/X.X发/到货审」；备注含「可以发」视为解除",
     "不审，进待定队列", "11-11 加「到货审」「可以发」豁免"),
    ("R25", "整单退款", "订单「退款状态」列含「退款」", "不审，进待定（等取消）", "11-11 新增（新导出表字段）"),
    ("R04", "暂停发货", "备注含「先不发/暂不发/说不发」", "不审，进待定队列", "已校验"),
    ("R05", "机器缺货", "01 开头机器行，目标仓可用量不足", "不审，标缺货", "存疑"),
    ("R06", "有价耗材缺货", "02/03 行且单价>0，目标仓可用量不足", "不审，标缺货", "存疑"),
    ("R07", "零元配件缺货", "02/03 行且单价=0：目标仓不足但深圳仓够", "照审，标注配件另仓发", "已校验"),
    ("R07b", "零元配件两仓都缺", "02/03 行且单价=0：目标仓与深圳仓均不足", "不审，标缺货", "已校验"),
    ("R08", "赠品缺货", "04 开头行，目标仓可用量不足", "剔除该赠品，主商品照审", "11-11 确认"),
    ("R09", "整单仅赠品行", "订单明细全部为 04 开头", "视为正常商品，必须校验库存", "已校验"),
    ("R10", "机器定仓", "01 行品名按机型 token 匹配《机器发货仓》（表内末行备注会被忽略）",
     "国内单：深圳仓有货优先深圳仓，缺货才走机型表仓；跨境单直接按机型表仓（667/664/621CW→合捷仓）",
     "11-11 批注修正"),
    ("R11", "机型未配置", "机型表无匹配", "默认深圳仓 + 深圳仓-韵达快递，标注机型未匹配", "用户 11-11 确认"),
    ("R12", "机型多仓冲突", "同一机型 token 命中多个不同仓", "默认深圳仓 + 深圳仓-韵达快递，标注冲突", "用户 11-11 确认"),
    ("R13", "机器快递", "合捷仓 → 合捷仓顺丰；深圳仓/退货仓 → 深圳仓-韵达快递", "按仓定快递", "11-11 批注修正"),
    ("R14", "耗材默认", "非机器单", "深圳仓 + 深圳仓-韵达快递", "已校验"),
    ("R15", "耗材指定顺丰", "备注含「指定顺丰」", "深圳仓 + 顺丰快递（平湖标快）", "已校验"),
    ("R16", "赠品识别", "备注出现赠品词（硒鼓/碳粉/墨水/纸/筋膜枪/吸尘器/榨汁杯等），按库存品名模糊匹配",
     "唯一命中→加赠品；数量按备注「2个/×2」解析，没写默认1", "11-11 改为模糊匹配"),
    ("R17", "赠品不唯一/无编码", "只提品类词（如「硒鼓」）匹配到多个编码",
     "主商品照审；赠品剔除并列出候选，人工确认后补", "11-11 确认"),
    ("R18", "赠品不重复", "订单明细已含同项赠品", "不重复添加", "已校验"),
    ("R19", "主子单", "同「分销单号」或同「原始单号」多笔订单（分销单号优先）",
     "每个子单按自己的货品定仓定快递；赠品只加主单", "11-10 修正（加分销单号归组）"),
    ("R20", "退货仓新机", "订单「标记」字段含「退货仓新机」",
     "带标记的机器单：有真实货品编码且原仓库有值 → 放行照审；否则进疑问（人工取消/改退货仓）。"
     "同组耗材子单 → 照审发出",
     "11-13 用户核查修正：有编码+有仓库的 9 单用户已实际审核过，加豁免"),
    ("R21", "刷单拦截", "独立单 + 货款=1 元 + 货品摘要含「打印」+ 明细全纸/全空", "不审，进待定队列（建议人工批量取消）", "11-06 新增（多单组不受影响）"),
    ("R22", "跨境单", "店铺名含「跨境/国际」（如 添美办公跨境供货商），与国内单靠「分销单号=原始单号」配对",
     "有配对：跨境单走机型表（合捷仓+合捷仓顺丰），国内单只剩耗材→深圳仓+韵达，且两单明细不合并；"
     "无配对：按 R10 正常规则走",
     "11-10 用户确认"),
    ("R23", "明细合并边界", "跨境配对组不合并明细（真实货品拆分）；管家主子单仍按原始单号合并明细",
     "各单只校验自己的明细", "11-10 新增"),
    ("R26", "耗材缺货替代品提示", "02/03 行目标仓缺货：同仓找「型号数字+品类+套装属性」一致且有货的编码",
     "不自动换货、不放审；仍进疑问，原因里附带替代品编码供人工确认换货",
     "11-11 批注修正（仅提示）"),
    ("R27", "已合并空壳单", "订单报表「订单拆分合并」字段含「合并」",
     "该单货品已并入他单，整单跳过，不进可审/不审",
     "11-12 核查新增"),
    ("R29", "赠品无法匹配（不唯一/泛词）", "赠品模糊匹配返回多候选/零候选（如「墨水」64 个候选）",
     "主商品照常审；赠品剔除，在「跳过赠品」列标注原因（含候选数），人工挑具体 SKU 补挂",
     "11-12 修订：曾误改为拦单导致过多疑问，退回剔除照审"),
    ("R30", "明细无货品编码", "整组明细全无货品编码",
     "货款>100（补差价/大额单）或 货款≤1 且摘要含机器/办公词 → 放行并标注建议补编码；"
     "其余进疑问请人工挂编码",
     "11-13 用户核查修正：840/450 元补差价单已审核过，加豁免"),
    ("R31", "原物流方式为空", "订单「物流方式」列为空",
     "整组有真实编码且原仓库有值 → 按仓规则给默认快递放行；否则进疑问",
     "11-13 用户核查修正：1151 有编码有仓库已审核过，加豁免"),
    ("R32", "库存表无记录", "目标仓库存表查不到该编码",
     "编码非空且原仓库有值（机器/耗材/赠品）→ 豁免放行并标注；否则进疑问",
     "11-13 新增：1434/20202 编码真实但库存表未更新"),
    ("R33", "刷单族（批量）", "同店铺 + 货款=1 + 备注空 + 摘要含「打印/办公」+ 订单号末4位连续簇≥3单",
     "整簇进待定，建议人工批量取消/核对。宁缺勿错：含品牌词、含A4纸占位编码的也在内",
     "11-13 用户核定 A 方案：能确定能过的才放，无法区分的全不动"),
    ("R36", "整单仅赠品行且无主单", "整组明细全为 4.xxx 赠品行 + 货款=0 + 无主单",
     "进待定，确认是否补发/赠品单（例：0257/0894 只有 TT-加热鼠标垫，标记缺货）",
     "11-13 新增"),
]

# 待业务确认问题（输出到规则清单第二页）
OPEN_QUESTIONS = [
    ("JY2611060001：明细 01.221 佳能MF754cdw，机型表 754→合捷仓（合捷仓可用 187、深圳仓 0），"
     "代码原给「合捷仓+合捷仓顺丰」，用户实测被审核成「深圳仓+深圳仓-韵达快递」",
     "R22：该单是跨境单 JY2611060158（分销单号 3316564418035019587）拆出来的国内单，"
     "机器随跨境单走，国内单只剩耗材 → 深圳仓+韵达",
     "—", "11-10 已按 R22 处理"),
    ("国内（非跨境）机器单是否也按《机器发货仓》走合捷仓？"
     "如 667/664/621CW 表内是合捷仓，但深圳仓库存为 0",
     "按机型表定仓（667/664/621CW 走合捷仓）",
     "全部强制深圳仓", "11-10 用户确认：无配对跨境单就按正常规则走"),
    ("JY2611050821：发票单原快递为「深圳仓-韵达快递」（其余 3 张发票单快递为空）",
     "快递保持原值，只改仓库为发票仓-财务", "清空快递", "11-11 用户确认：快递不影响"),
    ("明细无编码但有货品的订单（621cw / WF7845 / 3303sdw / MF752 等），编码待与业务协商",
     "按摘要机型定仓，不校验库存", "待补编码后恢复库存校验", "编码协商中"),
    ("赠品识别：备注只写品类词（如「硒鼓」）时有几百个编码，如何定编码？",
     "按库存完整品名模糊匹配+数量校验；不唯一/缺货时剔除赠品，主商品照审并列出候选",
     "业务补全常用赠品编码表提高自动率", "11-11 用户确认：模糊匹配"),
    ("审核后被取消的订单（用户标注「被取消」）如何识别与处理", "导出表无字段可识别", "管家 API / 人工核对", "待用户确认"),
    ("「退货」「都找不到」的订单暂不处理，等业务确认", "维持不审", "确认后补规则", "待用户确认"),
    ("11-13 用户在可审清单标红的 8 单（0731/1120/1221/1336/1349/1361/1374/1451）："
     "数据特征与用户已审核的 35 单完全同质（同店铺/同机型/同仓快递/need_change=False），规则无法区分",
     "维持进可审，由管家系统审核时兜底", "若为导出后状态变更（取消/已审），需提供管家侧最新状态",
     "待用户确认标红原因"),
]


def _num(v):
    """转数字，失败返回 0"""
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _all_remark(row):
    """合并客服备注 + 买家留言 + 发货备注，压缩空白"""
    parts = [row.get("客服备注"), row.get("买家留言"), row.get("发货备注")]
    text = " ".join(str(p or "") for p in parts)
    return re.sub(r"\s+", " ", text).strip()


def _norm(s):
    """归一化文本，去空格括号"""
    return re.sub(r"[（）()\s　]", "", str(s or "")).lower()


def _gnorm(s):
    """赠品名归一化：在 _norm 基础上再去横线/下划线，让「TT-榨汁杯」匹配「TT榨汁杯」"""
    return re.sub(r"[-—_·]", "", _norm(s))


def load_sheet(path, sheet_name):
    """读 sheet 为 dict 列表"""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows = list(wb[sheet_name].iter_rows(values_only=True))
    wb.close()
    header = [str(v).strip() if v is not None else "" for v in rows[0]]
    return [dict(zip(header, r)) for r in rows[1:] if any(v not in (None, "") for v in r)]


def _clean(v):
    """清洗单元格：去 Excel 转义符 _x000D_/_x000A_，压缩空白"""
    if v is None:
        return ""
    s = str(v).replace("_x000D_", " ").replace("_x000A_", " ")
    return re.sub(r"\s+", " ", s).strip()


# 订单级字段（新合并格式里每明细行都重复携带）
ORDER_LEVEL_FIELDS = ["分销单号", "原始单号", "订单号", "登记时间", "店铺名", "订单状态",
                      "登记人", "货品摘要", "收件人", "货款合计", "应收合计", "仓库",
                      "物流方式", "客服备注", "标记", "退款状态", "货品样数",
                      "货品总数", "订单拆分合并"]


def load_orders(path):
    """读订单导出表，自适应两种格式 → (orders, details)

    A. 新格式（订单11-11 起）：单 sheet「订单明细」，订单主信息 + 明细合并一行，
       订单级字段每明细行重复 → 同订单号取首行做订单主信息
    B. 旧格式：「订单」+「订单明细」两个 sheet
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets = {}
    for sn in wb.sheetnames:
        rows = list(wb[sn].iter_rows(values_only=True))
        if not rows:
            continue
        header = [_clean(h) for h in rows[0]]
        recs = [{k: _clean(v) for k, v in zip(header, r)}
                for r in rows[1:] if any(v not in (None, "") for v in r)]
        sheets[sn] = recs
    wb.close()

    # A. 单 sheet 合并格式：表头同时含订单级和明细级字段
    for sn, recs in sheets.items():
        cols = set(recs[0].keys()) if recs else set()
        if {"订单号", "编号", "品名"} <= cols and ("货品摘要" in cols or "货款合计" in cols):
            orders, details, seen = [], [], set()
            for r in recs:
                ono = str(r.get("订单号") or "")
                if ono and ono not in seen:
                    seen.add(ono)
                    orders.append({k: _clean(r.get(k)) for k in ORDER_LEVEL_FIELDS})
                details.append(r)
            return orders, details

    # B. 旧格式
    if "订单" in sheets and "订单明细" in sheets:
        return sheets["订单"], sheets["订单明细"]
    raise ValueError(f"订单表格式无法识别，sheet 列表: {list(sheets.keys())}")


def load_stock(path):
    """总库存：返回两个结构
      stock      : {(仓库, 编码): {...name/qty/bad/pending/alias/model...}}
      name_index : {归一化品名或别名或适用型号 → [code,...]}   用于 R02b 无编码反查
    """
    stock = {}
    name_index = defaultdict(set)
    for r in load_sheet(path, "数据段1"):
        wh = str(r.get("仓库") or "").strip()
        code = str(r.get("货品编号") or "").strip()
        if not wh or not code:
            continue
        name = str(r.get("品名") or "").strip()
        alias = str(r.get("别名") or "").strip()
        model = str(r.get("适用型号") or "").strip()
        rec = {"name": name, "alias": alias, "model": model,
               "qty": _num(r.get("库存量")), "bad": _num(r.get("不良品")),
               "pending": _num(r.get("待发量"))}
        stock[(wh, code)] = rec
        for key in (name, alias, model):
            key = _norm(key)
            if key:
                name_index[key].add(code)
    return stock, name_index


def resolve_code_by_name(name, name_index, prefer_warehouse=None, stock=None):
    """R02b：按品名字符串在库存表反查货品编码。

    优先用精确匹配；再用包含匹配（长名包含短 token 且 token 也包含长名片段 → 互为包含 → 取最长）。
    prefer_warehouse + stock 都给时，优先选在该仓有可用量的编码；该仓无可用则回退全量候选。
    返回：(code 或 None, 说明)
    """
    low = _norm(name)
    if not low:
        return None, ""
    # 精确
    if low in name_index:
        codes = list(name_index[low])
        return codes[0], f"品名字段精确匹配 → {codes[0]}"
    # 包含匹配：name 包含 index key（且 key 也能反向在 name 里看到）
    candidates = {}
    for key, codes in name_index.items():
        if len(key) < 2:
            continue
        if key in low or low in key:
            for c in codes:
                candidates.setdefault(c, []).append(key)
    if not candidates:
        return None, f"品名字段无匹配"
    note = ""
    if prefer_warehouse and stock is not None:
        in_wh = {c for c in candidates if available(stock, prefer_warehouse, c)}
        if in_wh:
            candidates = {c: candidates[c] for c in in_wh}
            note = f"（限 {prefer_warehouse} 有货）"
        else:
            note = f"（{prefer_warehouse} 无货，回退全量候选）"
    # 优先 01. 机器；否则 02/03；取出现最早的 key
    def score(code):
        pref = 0
        c0 = code.split(".")[0]
        if c0 == "01": pref = 3
        elif c0 in ("02", "03"): pref = 2
        else: pref = 1
        keys = candidates[code]
        longest = max(len(k) for k in keys)
        return (pref, longest)
    best = max(candidates.keys(), key=score)
    return best, f"品名字段包含匹配（候选 {len(candidates)}，选 {best}）{note}"


def load_model_warehouse(path):
    """机器发货仓：[(token, 仓库, 机型原名)]；左右两列表头重名，按列索引读"""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows = list(wb["机器发货仓"].iter_rows(values_only=True))
    wb.close()
    pairs = []
    for r in rows[1:]:
        for mi, wi in ((0, 1), (3, 4)):
            if len(r) <= wi:
                continue
            model, wh = str(r[mi] or "").strip(), str(r[wi] or "").strip()
            if not model or not wh:
                continue
            if "仓" not in wh:          # 过滤表末尾的备注行（如 752,754,667,621,664）
                continue
            m = re.search(r"[A-Za-z0-9]+", model)
            pairs.append((_norm(m.group(0) if m else model), wh, model))
    return pairs


def _code_variants(code):
    """编码格式兼容：订单表用 1.319，库存表用 01.319（11-13 发现）
    返回原样 + 补前导0 / 去前导0 的变体集合"""
    c = str(code or "").strip()
    if not c:
        return ()
    v = {c}
    if re.match(r"^\d\.", c):
        v.add("0" + c)
    elif re.match(r"^0\d\.", c):
        v.add(c[1:])
    return tuple(v)


def available(stock, warehouse, code):
    """目标仓可用量；无记录返回 None（兼容 1.319 / 01.319 两种编码格式）"""
    rec = None
    for c in _code_variants(code):
        rec = stock.get((warehouse, c))
        if rec is not None:
            break
    if rec is None:
        return None
    return rec["qty"] - rec["bad"] - rec["pending"] if STRICT_STOCK else rec["qty"]


def find_substitute(stock, warehouse, code, name):
    """R26：耗材缺货找替代品 —— 同仓 + 品名含相同型号数字 + 同品类 + 同套装属性 + 有货，唯一才换

    例：02.1122 尖嘴瓶8600墨水（一套4支）缺货 → 02.200 8600墨水套装（VC05一套4支）有货
    """
    name = str(name or "")
    m = re.search(r"\d{3,4}", name)          # 型号数字，如 8600 / 938
    if not m:
        return None
    model_no = m.group(0)
    is_set = ("一套" in name) or ("套装" in name)
    KIND_WORDS = ["墨水", "墨盒", "硒鼓", "碳粉", "墨粉", "芯片", "纸"]
    kinds = [w for w in KIND_WORDS if w in name]
    cands = []
    for (wh, c), rec in stock.items():
        if wh != warehouse or c in _code_variants(code):
            continue
        if classify(c) != "consumable":
            continue                           # 替代品只限 02/03 耗材，机器/赠品不换
        n = str(rec.get("name") or "")
        if model_no not in n:
            continue
        if is_set != (("一套" in n) or ("套装" in n)):
            continue                       # 套装只换套装，单支只换单支
        if kinds and not any(w in n for w in kinds):
            continue                       # 品类必须一致（墨水不换墨盒）
        if (available(stock, warehouse, c) or 0) > 0:
            cands.append(c)
    return cands[0] if len(cands) == 1 else None


def match_warehouse(names, model_rules):
    """按机型匹配仓库

    qualifier = 机型全名称中除去 token 以外的修饰词（升级版/标配/稳速版）。
    如果机型行带 qualifier 但品名不含该 qualifier，跳过该行（避免 9730免芯片 错配到 9730升级版→合捷仓）。

    免芯片产品兜底：产品含"免芯片"且机型行也含"免芯片" → 正常匹配；
    产品含"免芯片"但没找到任何合捷仓精确匹配 → 默认深圳仓。
    """
    QUALIFIER_KEYWORDS = ["升级版", "标配", "稳速版"]

    def _skip_for_qualifier(model_full, low):
        """机型行带 qualifier 但品名没有 → 跳过"""
        for q in QUALIFIER_KEYWORDS:
            if q in model_full and q not in low:
                return True
        return False

    for name in names:
        low = _norm(name)
        has_mianxinpian = "免芯片" in low

        cands = []                       # 严格 qualifier 匹配
        cands_loose = []                 # 回退：qualifier 不匹配但 token 匹配

        for tok, wh, full in model_rules:
            if not tok:
                continue
            pos = low.find(tok)
            if pos < 0:
                continue
            # 产品免芯片 → 机型行也必须含"免芯片"才匹配上；否则直接跳过（回退深圳仓兜底）
            if has_mianxinpian and "免芯片" not in full:
                continue
            if _skip_for_qualifier(full, low):
                cands_loose.append((pos, -len(tok), wh, full))
                continue
            cands.append((pos, -len(tok), wh, full))

        cands = cands if cands else cands_loose
        if not cands:
            continue

        cands.sort(key=lambda c: (c[0], c[1]))
        best_pos = cands[0][0]
        tied = [c for c in cands if c[0] == best_pos]
        whs = {c[2] for c in tied}
        if len(whs) == 1:
            return next(iter(whs)), ""
        return None, f"机型仓库冲突: {name} → {sorted(whs)}"

    # 兜底：产品含免芯片 → 默认深圳仓
    for name in names:
        if "免芯片" in _norm(name):
            return "深圳仓", ""

    return None, f"机型未配置仓库: {names[0] if names else ''}"


def classify(code):
    """按编码前缀分类"""
    if code.startswith(MACHINE_PREFIX):
        return "machine"
    if code.startswith(CONSUMABLE_PREFIX):
        return "consumable"
    if code.startswith(GIFT_PREFIX):
        return "gift"
    return "other"


def is_defer(remark):
    """备注是否延期/暂停发货；含「可以发」等放行词则视为解除延期"""
    if not remark:
        return False
    if any(k in remark for k in DEFER_RELEASE_KEYWORDS):
        return False
    return any(re.search(p, remark) for p in DEFER_PATTERNS)


def is_refunded(order_rows):
    """R25：订单「退款状态」列是否整单退款（新导出表字段）"""
    for o in order_rows:
        if "退款" in str(o.get("退款状态") or ""):
            return True
    return False


def is_cancel(remark):
    """R24：备注是否明确说不发货/退差价/退前一台"""
    if not remark:
        return False
    return any(kw in remark for kw in CANCEL_KEYWORDS)


def is_return_new_machine(order_rows, remark):
    """R20：退货仓新机识别 —— 扫组内所有订单的「标记」字段"""
    all_text = " ".join(str(o.get("标记") or "") for o in order_rows) + " " + remark
    return any(kw in all_text for kw in RETURN_NEW_MACHINE_KEYWORDS)


def _ret_machine_orders(rows, details_by_order):
    """R20：组内带「退货仓新机」标记的所有订单。
    业务实际（11-12 用户核查）：机器主单 + 耗材子单都要拦进疑问，
    人工取消/改退货仓后才放。管家的「订购量/库存量」字段不可信（1151 案），
    不能用它来判断超订。"""
    out = []
    for o in rows:
        if any(kw in str(o.get("标记") or "") for kw in RETURN_NEW_MACHINE_KEYWORDS):
            out.append(o)
    return out


def is_invoice(first_row):
    """R01：是否发票/专票单"""
    return (str(first_row.get("仓库") or "") in INVOICE_WAREHOUSE or
            any(k in str(first_row.get("货品摘要") or "") for k in INVOICE_KEYWORDS))


def is_cross_border(order_row):
    """R22：是否跨境单（店铺名含「跨境/国际」）——只有跨境单的机器才走合捷仓"""
    shop = str(order_row.get("店铺名") or "")
    return any(k in shop for k in CROSS_BORDER_SHOP_KEYWORDS)


def is_placeholder(abstract):
    """R02：权益/预约/补差价单（摘要命中占位商品词）"""
    return any(k in str(abstract or "") for k in PLACEHOLDER_KEYWORDS)


def is_appointment(order_rows, details_by_order):
    """R02：是否无货品编码单"""
    for r in order_rows:
        for d in details_by_order.get(str(r.get("订单号") or ""), []):
            if str(d.get("编号") or "").strip():
                return False
    return True


def _gift_qty(remark, keyword):
    """备注里解析赠品数量：送2个硒鼓 / 硒鼓×2 / 硒鼓2个；没写默认 1

    只认「数字+单位」或「×数字」，避免把型号里的数字（如 136A）当成数量。
    """
    pats = [
        rf"{keyword}\s*[×xX*]\s*(\d{{1,2}})",
        rf"(\d{{1,2}})\s*(个|支|包|瓶|盒|张|套|条|只|台|份)\s*{keyword}",
        rf"{keyword}\s*(\d{{1,2}})\s*(个|支|包|瓶|盒|张|套|条|只|台|份)",
    ]
    for p in pats:
        m = re.search(p, remark)
        if m:
            n = int(m.group(1))
            if 0 < n <= 99:
                return n
    return 1


def _shop_prefix_hint(remark):
    """备注含「天天/京东」等店铺词 → 返回可用于消歧的名称前缀（tt/jd…）"""
    return {pfx.lower() for pfx, words in SHOP_PREFIX_MAP.items()
            if any(w in remark for w in words)}


def resolve_gifts(remark, details, stock, name_index, warehouse, code_name):
    """R16/R17/R18：备注提到赠品 → 按库存品名模糊匹配 + 数量校验

    返回 (要加的赠品, 已含, 剔除清单, 候选列表)
      - 库存完整品名出现在备注里（越长越具体）且唯一 → 自动加，数量按备注解析
      - 只命中品类词（如「硒鼓」有 586 个编码）→ 不自动加，剔除并列出候选待人工确认
      - 库存不足 → 剔除该赠品，主商品照审
    """
    if not remark:
        return [], [], [], []
    # 「未选赠品：xxx」是客服未选赠品的提示，不算要加赠品
    remark = re.sub(r"未选赠品[：:][^\s，,；;]*", "", remark)
    low_remark = _gnorm(remark)
    hint = _shop_prefix_hint(remark)
    add, included, skipped, candidates = [], [], [], []
    detail_names = [_gnorm(d.get("品名") or "") for d in details]
    detail_codes = {str(d.get("编号") or "").strip() for d in details}

    # 命中词去重叠：「筋膜」被「筋膜枪」包含时只处理长的，避免重复剔除
    matched = [s for s in GIFT_SUBJECTS if s in remark]
    matched = [s for s in matched if not any(s != o and s in o for o in matched)]

    for subj in matched:
        key_subj = _gnorm(subj)

        # 1) 明细里已经含这个赠品 → 不重复加
        if any(key_subj in n for n in detail_names):
            included.append(subj)
            continue

        qty = _gift_qty(remark, subj)

        # 2) 库存完整品名出现在备注中且比品类词更具体（避免「硒鼓」这种通用名）
        hits = set()
        for key, codes in name_index.items():
            gkey = _gnorm(key)
            if len(gkey) <= len(key_subj) or key_subj not in gkey or gkey not in low_remark:
                continue
            hits.update(c for c in codes if not c.startswith(MACHINE_PREFIX))

        # 3) 同店铺前缀消歧（天天→TT- / 京东→JD-）
        if len(hits) > 1 and hint:
            narrowed = {c for c in hits
                        if any(h in _gnorm(code_name.get(c, "")) for h in hint)}
            if narrowed:
                hits = narrowed

        # 4) 明细里已有同一编码 → 视为已含
        if hits & detail_codes:
            included.append(subj)
            continue

        # 5) 候选池：优先精确名字命中；只提品类词时用库存表反查；再用店铺前缀消歧
        pool_all = hits or {c for c, n in code_name.items()
                            if key_subj in _gnorm(n) and not c.startswith(MACHINE_PREFIX)}
        if hint and len(pool_all) > 1:
            narrowed = {c for c in pool_all
                        if any(h in _gnorm(code_name.get(c, "")) for h in hint)}
            if narrowed:
                pool_all = narrowed

        # 6) 唯一命中 → 按数量校验库存
        if len(pool_all) == 1:
            code = next(iter(pool_all))
            avail = available(stock, warehouse, code)
            if avail is not None and avail >= qty:
                add.append({"code": code, "name": code_name.get(code, code), "qty": qty})
            else:
                skipped.append({"code": code, "name": code_name.get(code, code),
                                "reason": f"赠品库存不足（需{qty}，可用"
                                          f"{0 if avail is None else avail:.0f}），已剔除"})
            continue

        # 7) 仍不唯一 → 列候选，赠品剔除，主商品照审
        pool = sorted(pool_all)[:5]
        cand_text = "、".join(f"{c} {code_name.get(c, '')}" for c in pool)
        candidates.append(cand_text)
        skipped.append({"code": "", "name": subj,
                        "reason": f"赠品不唯一（共 {len(pool_all)} 个候选），需人工确认后补",
                        "candidates": cand_text})
    return add, included, skipped, candidates


def _supply_logistics(remark):
    """耗材快递：备注含「指定顺丰」→ 平湖标快，否则韵达"""
    return LOGISTICS_SUPPLY_SF if SF_KEYWORD in remark else LOGISTICS_SUPPLY_DEFAULT


def _plan_one_order(order_row, lines, abstract, remark, model_rules,
                    is_main=True, main_wh=None, main_logistics=None,
                    stock=None, is_cross=False):
    """单个订单（子单）的定仓定快递 → (wh, logistics, note)。wh 为空表示原值不动；wh=None 表示出错。

    主单（11-11 批注修正）：
      - 国内机器单：深圳仓有货 → 深圳仓+韵达；深圳仓缺货 → 才走机型表的仓
      - 跨境机器单：直接按机型表（合捷仓+合捷仓顺丰）
      - 全耗材 → 深圳仓+快递按备注
    子单：仓库沿用主单；快递按备注算（指定顺丰→平湖标快，否则韵达）。
    跨境拆出来的国内单不走这里，由 judge_group 直接判 深圳仓 + 韵达（R22）。
    """
    # 子单 —— 仓库跟主单，快递同耗材逻辑（看备注有无"指定顺丰"）
    if not is_main:
        if not main_wh:
            main_wh = str(order_row.get("仓库") or "") or "深圳仓"
        return main_wh, _supply_logistics(remark), "子单沿用主单仓库"

    # —— 主单路径 ——
    if not lines:
        if is_placeholder(abstract):
            return "", "", "权益/预约/补差价单，仓库/快递原值不动"
        wh, err = match_warehouse([abstract], model_rules)
        if err:
            return "深圳仓", LOGISTICS_SUPPLY_DEFAULT, f"机型未匹配，默认深圳仓+韵达（{err}）"
        return wh, LOGISTICS_MACHINE.get(wh, ""), "无货品编码，按摘要机型定仓，未校验库存"

    machine_lines = [d for d in lines if classify(str(d["编号"]).strip()) == "machine"
                     and _num(d.get("数量")) > 0]
    if machine_lines:
        wh, err = match_warehouse([str(d.get("品名") or "") for d in machine_lines], model_rules)
        if err:
            return "深圳仓", LOGISTICS_SUPPLY_DEFAULT, f"机型未匹配，默认深圳仓+韵达（{err}）"
        # 国内机器单：深圳仓有货优先深圳仓+韵达；跨境单直接按机型表仓
        if not is_cross and wh != "深圳仓" and stock is not None:
            first = machine_lines[0]
            code = str(first["编号"]).strip()
            need = _num(first.get("数量"))
            sz = available(stock, "深圳仓", code)
            if sz is not None and sz >= need:
                return "深圳仓", LOGISTICS_MACHINE["深圳仓"], f"国内单深圳仓有货（{sz:.0f}件），优先深圳仓"
        return wh, LOGISTICS_MACHINE.get(wh, ""), ""
    return "深圳仓", _supply_logistics(remark), ""


def judge_group(order_rows, details_by_order, details_by_origin, stock, model_rules, name_index):
    """同一原始单号/分销单号一组订单的决策 → (queue_items, question_items, skip_items)

    核心改动（R19 主子单 + R22 跨境单）：
      - 明细优先按「原始单号」合并（管家拆分主子单后明细可能都挂在其中一个子单上）
      - 主单 = 货款最大那单（有跨境单时，跨境单优先当主单）；主单用合并后的全部明细
      - 子单 = 货款小/明细空的；仓库跟主单
      - R22 跨境单：店铺含「跨境」→ 机器按《机器发货仓》走合捷仓 + 合捷仓顺丰；
        同组里拆出来的国内单是耗材 → 固定 深圳仓 + 深圳仓-韵达快递
    """
    cross_rows = [o for o in order_rows if is_cross_border(o)]
    has_cross = bool(cross_rows)
    main = max(cross_rows or order_rows, key=lambda o: _num(o.get("货款合计")))
    origin_no = str(main.get("原始单号") or "").strip()
    shop = str(main.get("店铺名") or "")
    # 组内备注合并（去重）：主子单各有客服备注，任一子单说延期/要赠品都要识别到
    seen_rm, rm_parts = set(), []
    for o in order_rows:
        rm = _all_remark(o)
        if rm and rm not in seen_rm:
            seen_rm.add(rm)
            rm_parts.append(rm)
    remark = " ".join(rm_parts)
    abstract = str(main.get("货品摘要") or "")

    base = {"order_no": str(main.get("订单号") or ""), "shop": shop,
            "main_item": abstract[:40], "remark": remark}

    # 0. 延期 / 暂停（优先级最高）
    if is_defer(remark):
        return [], [], [dict(base, reason=f"备注要求延期/暂停发货: {remark[:60]}")]

    # 0.5 R24：备注明确说不发货/退差价/退前一台
    if is_cancel(remark):
        return [], [], [dict(base, reason=f"备注明确不发货/退差价: {remark[:60]}")]

    # 1. R20 退货仓新机（v6 加豁免，同主循环 R20）：
    #   有真实编码 + 有原仓库记录 → 放行照审（用户已审核 9 单）
    if _ret_machine_orders(order_rows, details_by_order):
        j_has_code = any(str(d.get("编号") or "").strip()
                         for o in order_rows
                         for d in details_by_order.get(str(o.get("订单号") or ""), []))
        j_has_wh = any(str(o.get("仓库") or "").strip() for o in order_rows)
        if not (j_has_code and j_has_wh):
            return [], [], [dict(base, reason="退货仓新机机器单，暂进疑问队列")]

    # —— 明细归组：原始单号优先，订单号兜底 ——
    # 合并策略：所有子单明细之和 + 原始单号下的明细
    all_shared = []
    seen_keys = set()
    # 1) 原始单号 / 分销单号下的明细（管家导出新给的列）
    origin_keys = {origin_no, str(main.get("分销单号") or "").strip()} - {""}
    for ok in origin_keys:
        for d in details_by_origin.get(ok, []):
            key = (str(d.get("编号") or ""), str(d.get("品名") or ""), _num(d.get("数量")))
            if key not in seen_keys:
                seen_keys.add(key); all_shared.append(d)
    # 2) 订单号下的明细（兜底）
    for o in order_rows:
        ono = str(o.get("订单号") or "")
        for d in details_by_order.get(ono, []):
            key = (str(d.get("编号") or ""), str(d.get("品名") or ""), _num(d.get("数量")))
            if key not in seen_keys:
                seen_keys.add(key); all_shared.append(d)

    # 主单 = 货款最大；子单 = 其余 —— 两趟：先算主单仓，再用它算子单
    main_no = str(main.get("订单号") or "")
    plans = {}
    main_wh, main_logistics = None, None

    # 第一趟：算主单
    main_o = next(o for o in order_rows if str(o.get("订单号") or "") == main_no)
    main_cross = is_cross_border(main_o)
    if has_cross:
        # 跨境组：机器在跨境单、耗材在国内单，是真实货品拆分 → 各用各的明细，不能合并
        main_lines = [d for d in details_by_order.get(main_no, []) if str(d.get("编号") or "").strip()]
    else:
        main_lines = [d for d in all_shared if str(d.get("编号") or "").strip()]
    main_wh, main_logistics, main_note = _plan_one_order(
        main_o, main_lines, str(main_o.get("货品摘要") or "") or abstract, remark, model_rules,
        is_main=True, stock=stock, is_cross=main_cross)
    if main_wh is None:
        return [], [], [dict(base, reason=main_logistics)]
    if main_cross:
        main_note = ("跨境单：" + (main_note or f"{main_wh} + {main_logistics}")).strip("：")
    plans[main_no] = {"wh": main_wh, "logistics": main_logistics, "note": main_note,
                      "lines": main_lines, "is_main": True}

    # 第二趟：算各子单（仓库跟主单，快递平湖标快）
    for o in order_rows:
        ono = str(o.get("订单号") or "")
        if ono == main_no:
            continue
        olines = [d for d in details_by_order.get(ono, []) if str(d.get("编号") or "").strip()]
        if not olines and not has_cross:
            # 子单没自己的明细 → 从 shared 里排除机器类（跨境组不做这个兜底）
            olines = [d for d in all_shared
                      if classify(str(d.get("编号") or "").strip()) != "machine"
                      and str(d.get("编号") or "").strip()]
        if has_cross and not is_cross_border(o):
            # R22：跨境单拆出来的国内单是耗材 → 深圳仓 + 韵达
            wh, logistics, note = "深圳仓", LOGISTICS_SUPPLY_DEFAULT, "跨境拆分子单：耗材走深圳仓"
        else:
            wh, logistics, note = _plan_one_order(
                o, olines, str(o.get("货品摘要") or "") or abstract, remark, model_rules,
                is_main=False, main_wh=main_wh, main_logistics=main_logistics, stock=stock)
        if wh is None:
            return [], [], [dict(base, reason=logistics)]
        plans[ono] = {"wh": wh, "logistics": logistics, "note": note,
                      "lines": olines, "is_main": False}

    # 3. 库存校验（主单用主单的仓 + 主单的明细；子单用子单的仓 + 子单的明细）
    short_notes = []
    for ono, p in plans.items():
        wh = p["wh"] or str(next((o.get("仓库") for o in order_rows
                                  if str(o.get("订单号") or "") == ono), "") or "")
        lines = p["lines"]
        if not lines:
            continue
        kinds = {classify(str(d["编号"]).strip()) for d in lines}
        gift_only = kinds == {"gift"}
        has_machine = any(classify(str(d["编号"]).strip()) == "machine" and _num(d.get("数量")) > 0
                          for d in lines)
        for d in lines:
            code = str(d["编号"]).strip()
            kind = classify(code)
            need = _num(d.get("数量"))
            if need <= 0:
                continue
            # 11-12 删除 R28 超订拦截：管家的「订购量/库存量」字段不可信（1151 案
            # 客户拍 9 台但实际只发 1 台，订购量列残留 9），真正发多少看明细数量
            avail = available(stock, wh, code)
            if avail is None:
                # v6 加豁免：库存表查不到但编码非空 + 原仓库非空 → 豁免放行
                #   20202/1434 两单都是真实编码 TT-9730XL免芯片-2 + 深圳仓有记录，
                #   但库存表没这个编码 → 可能是库存表没更新，放行标注
                if kind in ("machine", "consumable", "gift") and wh:
                    # 豁免：跳过这一条的库存校验，继续下一条
                    continue
                else:
                    return [], [], [dict(base, reason=f"库存表无记录: {code} {d.get('品名')}")]
            if avail >= need:
                continue
            if kind == "gift" and not gift_only:
                short_notes.append(f"赠品缺货 {d.get('品名')}")
                continue
            # R26：耗材缺货 —— 同仓有替代品只做提示，不自动换货放审（人工确认后手动换）
            sub_hint = ""
            if kind == "consumable":
                sub = find_substitute(stock, wh, code, str(d.get("品名") or ""))
                if sub:
                    sub_avail = available(stock, wh, sub)
                    if sub_avail is not None and sub_avail >= need:
                        sub_name = str(stock.get((wh, sub), {}).get("name") or sub)
                        sub_hint = (f"；同仓有替代品 {sub} {sub_name}（可用{sub_avail:.0f}），"
                                    f"请人工确认是否换货")
            if kind == "consumable" and _num(d.get("单价")) == 0 and has_machine:
                alt = available(stock, "深圳仓", code)
                if alt is not None and alt >= need:
                    short_notes.append(f"配件缺货 {d.get('品名')}（深圳仓可发）")
                    continue
                return [], [], [dict(base, reason=f"配件缺货[{wh}] {code} {d.get('品名')} 需{need:.0f} "
                                                 f"可用{avail:.0f}，深圳仓"
                                                 f"{('无记录' if alt is None else f'{alt:.0f}')}也缺"
                                                 f"{sub_hint}")]
            tag = "缺货" if kind != "consumable" else "有价耗材缺货"
            return [], [], [dict(base, reason=f"{tag}[{wh}] {code} {d.get('品名')} 需{need:.0f} "
                                             f"可用{avail:.0f}{sub_hint}")]

    # 4. 赠品（R16/R17/R18：按库存品名模糊匹配 + 数量校验；缺货剔除，主商品照审）
    main_wh = plans.get(main_no, {}).get("wh") or str(main.get("仓库") or "")
    code_name = {c: rec["name"] for (_, c), rec in stock.items() if rec.get("name")}
    gifts_add, gift_included, gifts_skip, _ = resolve_gifts(
        remark, all_shared, stock, name_index, main_wh, code_name)
    # R29 退回：赠品配不上（不唯一/泛词）→ 剔除，主商品照常审，只在「跳过赠品」列标注原因
    # （11-12 曾误改为拦单，导致 7 单"墨水不唯一""硒鼓不唯一"全部进疑问，人工实际挑具体 SKU 即可）
    for n in dict.fromkeys(short_notes):
        if n.startswith("配件缺货"):
            skip_reason = "目标仓缺，深圳仓可发"
        else:
            skip_reason = "缺货，已剔除赠品"
        gifts_skip.append({"code": "", "name": n.split(" ", 1)[-1], "reason": skip_reason})

    # 5. 逐单输出
    items = []
    for o in order_rows:
        ono = str(o.get("订单号") or "")
        cur_wh, cur_ex = str(o.get("仓库") or ""), str(o.get("物流方式") or "")
        p = plans.get(ono, {})
        final_wh = p.get("wh") or cur_wh
        final_ex = p.get("logistics") or cur_ex
        is_main = p.get("is_main", True)
        items.append(dict(base,
                          order_no=ono,
                          shop=str(o.get("店铺名") or ""),
                          origin_no=str(o.get("原始单号") or ""),
                          warehouse=final_wh, logistics=final_ex,
                          need_change=not (cur_wh == final_wh and cur_ex == final_ex),
                          cur_warehouse=cur_wh, cur_logistics=cur_ex,
                          note=p.get("note", "") + ("" if is_main else "；子单默认耗材快递"),
                          is_main=is_main,
                          gifts=gifts_add if is_main else [],
                          gifts_included=gift_included if is_main else [],
                          gifts_skipped=gifts_skip if is_main else []))
    return items, [], []


def run(orders_path, stock_path, rules_path, out_dir):
    """审单主入口

    Args:
        orders_path: 订单导出 Excel 路径（自适应新单sheet合并格式 / 旧双sheet格式）
        stock_path: 总库存 Excel 路径
        rules_path: 仓库快递对接 Excel 路径
        out_dir: 输出目录（不存在自动创建）

    Returns:
        dict: 执行结果摘要，含 ok/total_ok/total_deferred/total_question 等
    """
    orders_path = str(orders_path)
    stock_path = str(stock_path)
    rules_path = str(rules_path)
    out_dir = str(out_dir)

    for label, p in [("订单", orders_path), ("库存", stock_path), ("规则", rules_path)]:
        if not Path(p).exists():
            raise FileNotFoundError(f"{label}文件不存在: {p}")

    orders, details = load_orders(orders_path)
    stock, name_index = load_stock(stock_path)
    model_rules = load_model_warehouse(rules_path)

    details_by_order = defaultdict(list)
    details_by_origin = defaultdict(list)
    for d in details:
        details_by_order[str(d.get("订单号") or "")].append(d)
        oid = str(d.get("原始单号") or "").strip()
        if oid:
            details_by_origin[oid].append(d)

    groups = defaultdict(list)
    for o in orders:
        if str(o.get("订单状态") or "") != "待审核":
            continue
        # R22：跨境单的「分销单号」= 拆分出的国内单「原始单号」，用分销单号归组把两单串起来
        # 11-12 修复：key 加店铺名前缀，防止「A店分销单号碰巧等于B店原始单号」被错归一组
        #     （0766 添美办公跨境 vs 0785 淘宝睿彩办公 就是这个问题）
        shop = str(o.get("店铺名") or "").strip()
        id_key = (str(o.get("分销单号") or "").strip()
                  or str(o.get("原始单号") or "").strip()
                  or str(o.get("订单号") or ""))
        groups[(shop, id_key)].append(o)

    # R33 刷单族预识别（v6.3 回退到 v5 保守拦截——宁缺勿错）：
    #   同店铺 + 货款=1 + 备注空 + 摘要含打印/办公 + 订单号末尾4位连续簇≥3单
    #   → 整组进待定（包括含品牌词、含 A4纸 2.225 编码、甚至全无编码的）
    #   用户手动审了 9 单刷单簇单只是随机抽的，代码不能因为审了几个就全部放行。
    #   这 36 单可以批量处理/取消，但不能逐个自动审核。
    anti_spam_clusters = set()
    spam_candidates = []
    for o in orders:
        if str(o.get("订单状态") or "") != "待审核": continue
        shop = str(o.get("店铺名") or "").strip()
        pay = _num(o.get("货款合计"))
        rm = str(o.get("客服备注") or "").strip()
        abstract = str(o.get("货品摘要") or "")
        if pay == 1 and not rm and ("打印" in abstract or "办公" in abstract):
            ono = str(o.get("订单号") or "")
            spam_candidates.append((shop, o, int(ono[-4:])))
    spam_candidates.sort(key=lambda x: (x[0], x[2]))
    cur_shop, cur_nums, cur_shop_orders = None, [], []
    for shop, o, num in spam_candidates:
        if cur_shop and shop == cur_shop and num - cur_nums[-1] < 100:
            cur_nums.append(num); cur_shop_orders.append(o)
        else:
            if len(cur_nums) >= 3:
                for oo in cur_shop_orders:
                    anti_spam_clusters.add(str(oo.get("订单号") or ""))
            cur_shop, cur_nums, cur_shop_orders = shop, [num], [o]
    if len(cur_nums) >= 3:
        for oo in cur_shop_orders:
            anti_spam_clusters.add(str(oo.get("订单号") or ""))
    if anti_spam_clusters:
        print(f"R33 刷单族识别命中 {len(anti_spam_clusters)} 单（门槛≥3单/簇，宁缺勿错全拦）")

    queues = {"plain": [], "gift": [], "split": []}
    deferred, question = [], []
    invoice_count, placeholder_count, refund_count = 0, 0, 0
    for rows in groups.values():
        first = rows[0]
        # 组内备注合并（去重）：任一子单说延期/不发货/要赠品都要识别到
        seen_rm, rm_parts = set(), []
        for o in rows:
            rm = _all_remark(o)
            if rm and rm not in seen_rm:
                seen_rm.add(rm)
                rm_parts.append(rm)
        remark = " ".join(rm_parts)

        # 0. R27 已合并空壳单：报表「订单拆分合并」含「合并」→ 货品已并入他单，整单跳过不审
        merged = {str(o.get("订单号") or "") for o in rows
                  if "合并" in str(o.get("订单拆分合并") or "")}
        if merged:
            rows = [o for o in rows if str(o.get("订单号") or "") not in merged]
            if not rows:
                continue

        # 0. R33 刷单族拦截（11-12 新增）：组内任一单命中刷单族 → 整组进待定
        #     特征：同店铺 + 货款=1 + 备注空 + 摘要含打印/办公 + 订单号序号连续
        spam_hit = anti_spam_clusters & {str(o.get("订单号") or "") for o in rows}
        if spam_hit:
            main = max(rows, key=lambda o: _num(o.get("货款合计")))
            shop = str(main.get("店铺名") or "")
            main_no = str(main.get("订单号") or "")
            # 组里没有货款大的单（只有 1 元占位）才整组拦，否则只拦占位单
            has_real = any(_num(o.get("货款合计")) > 1 for o in rows)
            if not has_real:
                for o in rows:
                    deferred.append(dict(
                        order_no=str(o.get("订单号") or ""),
                        shop=str(o.get("店铺名") or ""),
                        main_item=str(o.get("货品摘要") or "")[:40],
                        remark=remark[:60],
                        reason="疑似刷单族（批量下单货款1元），建议人工核对/批量取消"))
                continue

        # 0. R25 整单退款 → 待定（优先级最高：已退款的单不再审）
        if is_refunded(rows):
            main = max(rows, key=lambda o: _num(o.get("货款合计")))
            deferred.append(dict(
                order_no=str(main.get("订单号") or ""),
                shop=str(main.get("店铺名") or ""),
                main_item=str(main.get("货品摘要") or "")[:40],
                remark=remark[:60],
                reason="整单退款，不审核（等取消）"))
            refund_count += 1
            continue

        # 0. 延期/暂停 → 待定（最高优先，所有单都不例外）
        if is_defer(remark):
            main = max(rows, key=lambda o: _num(o.get("货款合计")))
            deferred.append(dict(
                order_no=str(main.get("订单号") or ""),
                shop=str(main.get("店铺名") or ""),
                main_item=str(main.get("货品摘要") or "")[:40],
                remark=remark[:60],
                reason=f"备注要求延期/暂停发货: {remark[:60]}"))
            continue

        # 0.5 R24 备注明确不发货/退差价
        if is_cancel(remark):
            main = max(rows, key=lambda o: _num(o.get("货款合计")))
            deferred.append(dict(
                order_no=str(main.get("订单号") or ""),
                shop=str(main.get("店铺名") or ""),
                main_item=str(main.get("货品摘要") or "")[:40],
                remark=remark[:60],
                reason=f"备注明确不发货/退差价: {remark[:60]}"))
            continue

        # 1. R20 退货仓新机（v6 加豁免）：
        #   原逻辑：只要组内有单带「退货仓新机」标记 → 整组进疑问
        #   v6 豁免：**有真实外部编码** + **原仓库有记录** → 放行照审（用户已审核 9 单，
        #     证明这些标记只是备注，编码/仓库/快递都对的时候可以直接过）
        #   只有「无编码 + 仓库也空」的退货仓新机才进疑问
        if is_return_new_machine(rows, remark):
            r_has_code = any(str(d.get("编号") or "").strip()
                             for o in rows
                             for d in details_by_order.get(str(o.get("订单号") or ""), []))
            r_has_wh = any(str(o.get("仓库") or "").strip() for o in rows)
            if r_has_code and r_has_wh:
                # 豁免：有真实编码 + 有原仓库 → 不走疑问，继续后续规则
                pass
            else:
                for o in rows:
                    question.append(dict(
                        order_no=str(o.get("订单号") or ""),
                        shop=str(o.get("店铺名") or ""),
                        main_item=str(o.get("货品摘要") or "")[:40],
                        remark=remark[:60],
                        reason="退货仓新机，暂进疑问队列（含耗材子单，人工确认后放审）"))
                continue

        # 1.5 R02 权益/预约/补差价单 → 待定（11-12 严化）
        #     只有「货款=1 + 无编码 + placeholder」才拦；货款大的补差价（840/450）
        #     备注有真实商品信息，按真实单处理（用户已审核过 1346/1331）
        abstract_all = " ".join(str(o.get("货品摘要") or "") for o in rows)
        has_coded = any(str(d.get("编号") or "").strip()
                        for o in rows
                        for d in details_by_order.get(str(o.get("订单号") or ""), []))
        main = max(rows, key=lambda o: _num(o.get("货款合计")))
        main_pay = _num(main.get("货款合计"))
        if (not has_coded and main_pay <= 1
                and (is_placeholder(abstract_all) or is_placeholder(remark))):
            deferred.append(dict(
                order_no=str(main.get("订单号") or ""),
                shop=str(main.get("店铺名") or ""),
                main_item=str(main.get("货品摘要") or "")[:40],
                remark=remark[:60],
                reason="权益/预约/补差价单（货款1元无实质内容），后续正常取消，不审核"))
            placeholder_count += 1
            continue

        # 1.6 R30 整组无货品编码（v6.4 收紧豁免）：
        #   豁免条件（满足任一）：
        #     a) 货款 ≤ 1 + summary 是机器关键词 → 放行
        #     b) 货款 > 100 且摘要含「补差价/补邮费/补运费」→ 放行
        #        （11-13 收紧：原「货款>100 全放」把 1363/0015 两单 1637 元无编码机器单也放了，
        #         用户实际没审这两单；只有补差价类大额单 1331(450)/1346(840) 用户审过）
        if not has_coded:
            main = max(rows, key=lambda o: _num(o.get("货款合计")))
            main_pay = _num(main.get("货款合计"))
            abstract_all = " ".join(str(o.get("货品摘要") or "") for o in rows)
            is_adj = any(kw in abstract_all for kw in ("补差价", "补邮费", "补运费", "补快递"))
            if (main_pay <= 1 and any(kw in abstract_all for kw in ("打印机", "一体机", "机器", "办公"))) \
                    or (main_pay > 100 and is_adj):
                pass
            else:
                for o in rows:
                    question.append(dict(
                        order_no=str(o.get("订单号") or ""),
                        shop=str(o.get("店铺名") or ""),
                        main_item=str(o.get("货品摘要") or "")[:40],
                        remark=remark[:60],
                        reason="明细无货品编码，无法校验库存，请人工核对后挂编码"))
                continue

        # 1.7 R31 原物流方式为空（v6 加豁免）：
        #   原逻辑：原物流方式为空 → 进疑问
        #   v6 豁免：整组**有真实编码** + **原仓库有记录** → 放行（用默认快递）
        #     只有「无真实编码」或「原仓库也空」才进疑问
        rows_empty_ex = [o for o in rows if not str(o.get("物流方式") or "").strip()]
        if rows_empty_ex:
            # 检查整组有没有编码 + 仓库有没有值
            r31_has_code = any(str(d.get("编号") or "").strip()
                               for o in rows
                               for d in details_by_order.get(str(o.get("订单号") or ""), []))
            r31_has_wh = any(str(o.get("仓库") or "").strip() for o in rows)
            if r31_has_code and r31_has_wh:
                # 豁免：有编码+有仓库 → 用默认快递，不走疑问
                pass
            else:
                main = max(rows, key=lambda o: _num(o.get("货款合计")))
                for o in rows_empty_ex:
                    question.append(dict(
                        order_no=str(o.get("订单号") or ""),
                        shop=str(o.get("店铺名") or ""),
                        main_item=str(o.get("货品摘要") or "")[:40],
                        remark=remark[:60],
                        reason="原物流方式为空，无法确定快递，请人工核对"))
                continue

        # R32 回退（11-12 核查发现过于激进）：
        # 用户 ps7 标正常的 16 单里，1284/0019 备注赠品都没配齐但照审了——
        # 赠品配不上时先剔除照审主商品（库存不足/泛词都不拦），人工事后补挂赠品
        # 原位置：line 1028-1046


        # 2. R01 发票/专票单 → 可审；发货仓固定「发票仓-财务」，快递保持原值
        if is_invoice(first):
            invoice_count += len(rows)
            main = max(rows, key=lambda o: _num(o.get("货款合计")))
            shop = str(main.get("店铺名") or "")
            for o in rows:
                cur_wh = str(o.get("仓库") or "")
                cur_ex = str(o.get("物流方式") or "")
                queues["plain"].append({
                    "shop": shop, "main_item": f"[发票单] {str(o.get('货品摘要') or '')[:40]}",
                    "order_no": str(o.get("订单号") or ""),
                    "origin_no": str(o.get("原始单号") or ""),
                    "warehouse": INVOICE_TARGET_WH, "logistics": cur_ex,
                    "need_change": cur_wh != INVOICE_TARGET_WH,
                    "cur_warehouse": cur_wh, "cur_logistics": cur_ex,
                    "note": "发票单：发货仓固定发票仓-财务",
                    "gifts": [], "gifts_included": [], "gifts_skipped": []})
            continue

        # 3. R21 刷单拦截（v6.3 回退 v5 保守：不豁免品牌词，宁缺勿错）：
        #     独立单 + 货款=1 + 明细全无编码 + summary 只有笼统占位词 → 进待定
        if len(rows) == 1:
            main = rows[0]
            main_no = str(main.get("订单号") or "")
            total_pay = _num(main.get("货款合计"))
            abstract = str(main.get("货品摘要") or "")
            if total_pay == 1 and "打印" in abstract:
                origin_no = str(main.get("原始单号") or "").strip()
                all_dets = []
                if origin_no and origin_no in details_by_origin:
                    all_dets.extend(details_by_origin[origin_no])
                all_dets.extend(details_by_order.get(main_no, []))
                all_codes = [str(d.get("编号") or "").strip() for d in all_dets]
                codes_all_empty = all_codes and all(not c for c in all_codes)
                if codes_all_empty:
                    shop = str(main.get("店铺名") or "")
                    deferred.append(dict(
                        order_no=main_no, shop=shop,
                        main_item=abstract[:40], remark=remark[:60],
                        reason="疑似刷单单（货款1元，明细编号全空），建议批量取消"))
                    continue

        # R34 已撤回（v6.1 验证太激进，放了 37 单不该放的刷单簇）
        # 原位置：lines 1195-1219

        # R36 仅赠品行单（11-13 新增）：整组明细全是赠品行（4.xxx）且货款=0，且本组无主单
        #   例：0257/0894 只有 4.102 TT-加热鼠标垫，标记=缺货，用户没审 → 不该进可审
        #   注意：如果是主子单组里的子单，不适用（子单要跟主单一起审）
        if len(rows) == 1:
            r36_codes = [str(d.get("编号") or "").strip()
                         for d in details_by_order.get(str(rows[0].get("订单号") or ""), [])
                         if str(d.get("编号") or "").strip()]
            r36_pay = _num(rows[0].get("货款合计"))
            if r36_codes and r36_pay == 0 and all(classify(c) == "gift" for c in r36_codes):
                deferred.append(dict(
                    order_no=str(rows[0].get("订单号") or ""),
                    shop=str(rows[0].get("店铺名") or ""),
                    main_item=str(rows[0].get("货品摘要") or "")[:40],
                    remark=remark[:60],
                    reason="整单仅赠品行且无主单（货款0），确认是否为补发/赠品单"))
                continue

        # 4. 正常流程（含 R02/R02b 无编码单、主子单拆分单）
        items, _, q = judge_group(rows, details_by_order, details_by_origin,
                                   stock, model_rules, name_index)
        if q:
            question.extend(q)
            continue

        if len(rows) > 1:
            queues["split"].extend(items)
        elif any(it.get("gifts") for it in items):
            queues["gift"].extend(items)
        else:
            queues["plain"].extend(items)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"queues": queues, "deferred": deferred, "question": question}
    (out_dir / "audit_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                               encoding="utf-8")

    total_ok = sum(len(v) for v in queues.values())
    accessory = [q for q in question if "配件缺货" in q.get("reason", "")]
    gift_q = [q for q in question if "赠品编码规则" in q.get("reason", "")]
    model_q = [q for q in question if "机型" in q.get("reason", "")]
    stock_q = [q for q in question if q.get("reason", "").startswith(("缺货", "有价耗材缺货"))]
    return_q = [q for q in question if "退货仓新机" in q.get("reason", "")]
    other_q = [q for q in question if q not in accessory + gift_q + model_q + stock_q + return_q]

    lines = [f"待审核 {len(orders)} 单：可审 {total_ok}（改仓快递 {len(queues['plain'])} / "
             f"加赠品 {len(queues['gift'])} / 拆分 {len(queues['split'])}），"
             f"其中发票/专票 {invoice_count}、权益/预约/补差价 {placeholder_count}、"
             f"整单退款 {refund_count}（均进待定），"
             f"待定 {len(deferred)}，疑问 {len(question)}",
             f"疑问分布：退货仓新机 {len(return_q)}、缺货 {len(stock_q)}、赠品规则待补 {len(gift_q)}、"
             f"机型 {len(model_q)}、配件提示 {len(accessory)}、其他 {len(other_q)}"]
    for it in deferred:
        lines.append(f"[待定] {it['order_no']} {it['reason']}")
    for it in question:
        lines.append(f"[疑问] {it['order_no']} {it['reason']}")
    (out_dir / "回传摘要.txt").write_text("\n".join(lines), encoding="utf-8")

    # 审核清单（三页：可审清单 / 不审 / 规则清单）
    # 「货品总数」「订单拆分合并」由订单报表提供（11-12 起新增），旧表无该列时为空
    omap = {str(o.get("订单号") or ""): o for o in orders}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "可审清单"
    ws.append(["订单号", "原始单号", "店铺", "类别", "主货品", "货品总数", "订单拆分合并",
               "原仓库", "新仓库", "原快递", "新快递", "需修改", "加赠品", "已含赠品",
               "跳过赠品", "备注"])
    for cat, its in queues.items():
        for it in its:
            o = omap.get(it["order_no"], {})
            ws.append([it["order_no"], it["origin_no"], it["shop"], cat, it["main_item"],
                       o.get("货品总数") or "", o.get("订单拆分合并") or "",
                       it["cur_warehouse"], it["warehouse"], it["cur_logistics"], it["logistics"],
                       "是" if it["need_change"] else "否",
                       "、".join(f"{g['name']}×{g['qty']}" for g in it["gifts"]),
                       "、".join(it["gifts_included"]),
                       "、".join(g["name"] for g in it["gifts_skipped"]),
                       it.get("note", "")])
    ws2 = wb.create_sheet("不审")
    ws2.append(["订单号", "原始单号", "类型", "货品总数", "订单拆分合并", "原因"])
    for it in deferred:
        o = omap.get(it["order_no"], {})
        ws2.append([it["order_no"], str(o.get("原始单号") or ""), "待定",
                    o.get("货品总数") or "", o.get("订单拆分合并") or "", it["reason"]])
    for it in question:
        o = omap.get(it["order_no"], {})
        qtype = "退货仓新机" if "退货仓新机" in it.get("reason", "") else "疑问"
        ws2.append([it["order_no"], str(o.get("原始单号") or ""), qtype,
                    o.get("货品总数") or "", o.get("订单拆分合并") or "", it["reason"]])
    ws3 = wb.create_sheet("规则清单")
    ws3.append(["编号", "规则", "判定条件", "执行动作", "校验状态"])
    for row in RULES_DOC:
        ws3.append(list(row))
    for col, w in zip("ABCDEFGHIJKLMNOP",
                      (14, 16, 18, 9, 36, 10, 12, 12, 12, 20, 26, 8, 18, 14, 28, 40)):
        ws.column_dimensions[col].width = w
    for col, w in zip("ABCDEF", (14, 16, 12, 10, 12, 50)):
        ws2.column_dimensions[col].width = w
    for col, w in zip("ABCDE", (8, 20, 50, 34, 28)):
        ws3.column_dimensions[col].width = w
    wb.save(out_dir / "审核清单.xlsx")

    # 独立规则清单（给业务校对用）
    wb3 = openpyxl.Workbook()
    r1 = wb3.active
    r1.title = "审单规则"
    r1.append(["编号", "规则", "判定条件", "执行动作", "校验状态"])
    for row in RULES_DOC:
        r1.append(list(row))
    for col, w in zip("ABCDE", (8, 18, 60, 36, 30)):
        r1.column_dimensions[col].width = w
    r1.freeze_panes = "A2"
    r2 = wb3.create_sheet("待业务确认")
    r2.append(["序号", "待确认问题", "当前默认处理", "备选方案", "结论"])
    for i, (q, cur, alt, ans) in enumerate(OPEN_QUESTIONS, 1):
        r2.append([i, q, cur, alt, ans])
    for col, w in zip("ABCDE", (6, 55, 20, 30, 20)):
        r2.column_dimensions[col].width = w
    wb3.save(out_dir / "审单规则清单.xlsx")

    print("\n".join(lines[:12]))
    print(f"\n输出目录: {out_dir}")

    # 返回执行摘要 + 完整列表 —— 影刀直接循环，不需要再读任何文件
    return {
        "ok": True,
        "out_dir": str(out_dir),
        "audit_json": str(out_dir / "audit_result.json"),
        "audit_xlsx": str(out_dir / "审核清单.xlsx"),
        "rules_xlsx": str(out_dir / "审单规则清单.xlsx"),
        "summary_txt": str(out_dir / "回传摘要.txt"),
        "total_orders": len(orders),
        "total_ok": total_ok,
        "total_deferred": len(deferred),
        "total_question": len(question),
        "plain": len(queues["plain"]),
        "gift": len(queues["gift"]),
        "split": len(queues["split"]),
        "invoice_count": invoice_count,
        "appointment_count": placeholder_count,
        "refund_count": refund_count,
        # ↓ 完整列表，影刀直接循环用
        "queues": queues,
        "deferred": deferred,
        "question": question,
    }


# ---------- 影刀调用入口 ----------
#
# 方式 B：影刀「调用模块」组件
#   模块文件: order_judge.py
#   调用函数: run
#   参数: 按位置传 4 个字符串（影刀列表参数）：
#     ["订单Excel路径", "库存Excel路径", "规则Excel路径", "输出目录"]
#
#   返回值 → 影刀变量 {res}
#     res["ok"] / res["total_ok"] / res["queues"]["plain"] / res["deferred"] / res["question"]


# ---------- 命令行入口 ----------
#
# 方式 A：影刀「执行命令」组件
#   python order_judge.py 订单.xlsx 库存.xlsx 规则.xlsx 输出目录

def main():
    """命令行入口 —— python order_judge.py 订单 库存 规则 输出"""
    if len(sys.argv) < 4:
        print("""用法: python order_judge.py <订单Excel> <库存Excel> <规则Excel> <输出目录>

示例:
  python order_judge.py 订单.xlsx 总库存.xlsx 仓库快递对接.xlsx audit_out
""")
        sys.exit(1)

    result = run(sys.argv[1], sys.argv[2], sys.argv[3],
                 sys.argv[4] if len(sys.argv) > 4 else "audit_out")

    if result["ok"]:
        print("\n[SUCCESS] 审单完成")
        print(f"  可审 {result['total_ok']} 单")
        print(f"  待定 {result['total_deferred']} 单")
        print(f"  疑问 {result['total_question']} 单")
        print(f"  输出: {result['out_dir']}")
        sys.exit(0)
    else:
        print("\n[FAIL] 审单异常")
        sys.exit(3)


if __name__ == "__main__":
    main()
