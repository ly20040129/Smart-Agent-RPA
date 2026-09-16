# -*- coding: utf-8 -*-
"""
京东艾贝自营仓销售出库 - 数据清洗模块（重构版）

重构前：367 行（含读Excel、SKU清洗、分类汇总、物料匹配、日期处理、Excel美化等通用逻辑）
重构后：~80 行（只保留差异化业务规则，通用操作全部收敛到 sdk/data_tools.py）

设计原则：影刀中几个简单代码块就能完成的需求，迁移过来后不应过度工程化。
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
from sdk.data_tools import (
    clean_sku_column, clean_numeric_column, clean_date_column,
    classify_positive_negative, load_material, match_sku,
    get_dominant_month_end, apply_border, save_empty_result,
)

# ==================== 差异化业务配置 ====================

DEFAULT_CONFIG = {
    "material_path": r"D:\ly\京东艾贝自营出库\新物料.xlsx",
    "output_dir": r"D:\ly\京东艾贝自营出库",
    "similarity_threshold": 0.92,
}

# 京东导出固定列映射
JD_COLUMNS = [
    "单据类型", "单据编号", "采购单号", "订单号",
    "采销员", "合同主体", "SKU编码", "数量",
    "金额", "币种", "业务日期", "采购渠道",
]

# 输出模板固定值
FIXED_VALUES = {
    "购货单位": "京东-艾贝自营店",
    "销售方式": "赊销",
    "发货仓库": "京东自营仓",
}

# 输出表头（27列固定模板）
OUTPUT_HEADERS = [
    "[表头]单据编号(*)", "[表头]单据日期(*)", "[表头]购货单位(*)", "[表头]销售方式(*)",
    "[表头]摘要", "[表头]交货地点", "[表头]联系人", "[表头]联系人电话",
    "[表头]收货地址", "[表头]红蓝单", "物料代码(*)", "物料名称",
    "规格型号", "单位(*)", "发货仓库(*)", "实发数量(*)", "单位成本(*)", "备注",
    "辅助属性", "客户料号", "客户商品名称", "生产/采购日期", "保质期(天)",
    "有效期至", "批号", "销售单价", "折扣率",
]


# ==================== 主入口 ====================

def process(input_file: str, context: dict = None, params: dict = None, **kwargs) -> str:
    """清洗京东艾贝自营仓销售出库数据"""
    config = _merge_config(context, params)
    logger.info(f"[jd_ibay] 开始处理: {input_file}")

    # 1. 读取 + 通用清洗（全部走 data_tools）
    df = pd.read_excel(input_file)
    if len(df.columns) >= len(JD_COLUMNS):
        df.columns = JD_COLUMNS + list(df.columns[len(JD_COLUMNS):])
    df = df.dropna(how="all")
    df = clean_sku_column(df, "SKU编码")
    df = clean_numeric_column(df, "数量")
    df = clean_date_column(df, "业务日期")

    if len(df) == 0:
        return save_empty_result(config["output_dir"], "京东艾贝_无数据")

    # 2. 分类蓝单/红单（通用工具）
    red, blue = classify_positive_negative(df, "SKU编码", "数量")
    logger.info(f"[jd_ibay] 红单 {len(red)} 个SKU，蓝单 {len(blue)} 个SKU")

    # 3. 加载物料表（通用工具）
    name_map, unit_map = load_material(config["material_path"])

    # 4. 生成输出（差异化：27列模板、红蓝单分行格式）
    output_file = _build_output(red, blue, name_map, unit_map, config)

    logger.info(f"[jd_ibay] 完成: {output_file}")
    return output_file


# ==================== 差异化逻辑 ====================

def _merge_config(context, params):
    """合并配置：params > user_params > 默认"""
    user_params = context.get("user_params", {}) if context else {}
    config = DEFAULT_CONFIG.copy()
    config.update(user_params)
    if params:
        config.update({k: v for k, v in params.items() if v is not None})
    return config


def _build_output(red, blue, name_map, unit_map, config):
    """构建 27 列上传模板（这是京东艾贝特有的输出格式）"""
    threshold = config["similarity_threshold"]
    output_dir = config["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    unmatched = []
    blue_no = datetime.now().strftime("%Y%m%d%H%M%S")
    red_no = (datetime.now() + timedelta(seconds=100)).strftime("%Y%m%d%H%M%S")
    doc_date = get_dominant_month_end(
        pd.concat([red, blue], axis=0) if len(red) > 0 or len(blue) > 0 else pd.DataFrame(),
        "业务日期",
    )

    rows = []
    # 红单（数量为正 = 退货入库）
    for i, (_, row) in enumerate(red.iterrows()):
        sku, name, unit = match_sku(row["SKU编码"], name_map, unit_map, threshold, unmatched)
        rows.append(_make_row(red_no if i == 0 else "", doc_date if i == 0 else "",
                              "红单" if i == 0 else "", sku, name, unit, row["positive_qty"]))
    # 蓝单（数量为负 = 销售出库）
    for i, (_, row) in enumerate(blue.iterrows()):
        sku, name, unit = match_sku(row["SKU编码"], name_map, unit_map, threshold, unmatched)
        rows.append(_make_row(blue_no if i == 0 else "", doc_date if i == 0 else "",
                              "蓝单" if i == 0 else "", sku, name, unit, row["negative_qty"]))

    # 写入 Excel
    data = [OUTPUT_HEADERS]
    for r in rows:
        row = [""] * len(OUTPUT_HEADERS)
        row[0], row[1], row[2], row[3] = r["no"], r["date"], r["buyer"], r["sale_type"]
        row[9] = r["color"]
        row[10], row[11], row[13] = r["sku"], r["name"], r["unit"]
        row[14] = FIXED_VALUES["发货仓库"]
        row[15] = r["qty"]
        row[22], row[25], row[26] = 0, 1, 0
        data.append(row)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"京东艾贝自营出库单汇总_{ts}.xlsx")
    pd.DataFrame(data).to_excel(output_file, index=False, header=False, sheet_name="销售出库单", engine="openpyxl")
    apply_border(output_file, len(rows))

    # 未匹配日志
    if unmatched:
        log_file = os.path.join(output_dir, f"未匹配物料_{datetime.now().strftime('%Y%m%d')}.txt")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"未匹配物料 ({len(unmatched)} 个)\n{'=' * 40}\n")
            for sku in sorted(set(unmatched)):
                f.write(f"  {sku}\n")
        logger.info(f"[jd_ibay] 未匹配物料: {log_file}")

    return output_file


def _make_row(no, date, color, sku, name, unit, qty):
    return {
        "no": no, "date": date,
        "buyer": FIXED_VALUES["购货单位"] if no else "",
        "sale_type": FIXED_VALUES["销售方式"] if no else "",
        "color": color, "sku": sku, "name": name, "unit": unit, "qty": qty,
    }