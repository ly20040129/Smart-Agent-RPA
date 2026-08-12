# -*- coding: utf-8 -*-
"""
京东商智竞品数据统计
调用API → 匹配Excel → 写入保存

用户私有配置（p-pin等）在 config/config.local.yaml 的 jd_shangzhi 节点
任务参数（cookie/excel_path/output_dir）从 Web 界面传入
"""
import os
import re
import sys
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from src.core.config import get_config


# ==================== 工具函数 ====================

def clean_sku(sku):
    """只保留数字"""
    return re.sub(r'[^0-9]', '', str(sku).strip())


def fmt(val):
    """去掉 .0"""
    if val is None or val == '':
        return ''
    return str(int(val)) if isinstance(val, float) and val == int(val) else str(val)


def load_cookie(path):
    """从文件读取cookie，返回字符串"""
    if not path or not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # 解析成 cookie 字符串: name1=value1; name2=value2
    if 'cookies' in data:
        return '; '.join([f"{c['name']}={c['value']}" for c in data['cookies']])
    return data.get('cookie')


# ==================== API调用 ====================

def _get_headers():
    """
    构建请求头，用户私有信息从 config.l  ocal.yaml 读取

    config.local.yaml 里这样填:
        jd_shangzhi: 
          p_pin: "xxx"        # 你的京东p in（URL编码）
          user_mnp: "xxx"     # 用户标识
          user_mup: "xxx"     # 时间戳
          uuid: "xxx"         # 设备标识
    """
    cfg = get_config().config_data
    jd_cfg = cfg.get('jd_shangzhi', {})

    return {
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "p-pin": jd_cfg.get('p_pin', ''),
        "Referer": "https://sz.jd.com/sz/view/competitionAnalysis/competePros.html",
        "user-mnp": jd_cfg.get('user_mnp', ''),
        "user-mup": jd_cfg.get('user_mup', ''),
        "uuid": jd_cfg.get('uuid', ''),
        "x-requested-with": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def call_api(date_str, cookie_str):
    """调用京东商智API"""
    url = "https://sz.jd.com/sz/api/competitionAnalysis/getCompeteProDetail.ajax"
    params = {
        "date": date_str,
        "dateType": "day",
        "endDate": date_str,
        "indChannel": "99",
        "startDate": date_str,
        "unitType": "1",
    }

    # 解析cookie字符串 → 字典
    cookie_dict = {}
    for item in cookie_str.split('; '):
        if '=' in item:
            k, v = item.split('=', 1)
            cookie_dict[k] = v

    resp = requests.get(url, headers=_get_headers(), params=params, cookies=cookie_dict, timeout=30).json()

    if resp.get('status') != '0':
        raise RuntimeError(f"API异常: {resp}")

    return resp.get('content', {}).get('data', [])


# ==================== 匹配写入 ====================

def match_and_write(df, sku_map):
    """匹配SKU，写入Excel"""
    found = 0
    for idx in range(2, len(df)):
        sku_val = df.iloc[idx, 2]
        if pd.isna(sku_val):
            continue

        item = sku_map.get(clean_sku(str(sku_val)))
        if item:
            df.iloc[idx, 5] = fmt(item[4].get('range', '') if len(item) > 4 and item[4] else '')
            df.iloc[idx, 6] = fmt(item[6].get('range', '') if len(item) > 6 and item[6] else '')
            found += 1

    return found


# ==================== 主入口 ====================

def process(date_str=None, cookie=None, excel_path=None, output_dir=None, **kwargs):
    """
    主入口

    Args:
        date_str: 查询日期 YYYY-MM-DD（不传则默认昨天）
        cookie: cookie文件路径（必填，从Web界面上传）
        excel_path: Excel模板文件路径（必填，从Web界面上传）
        output_dir: 输出目录（必填，从Web界面选择）
    """
    # 1. 日期处理
    if not date_str:
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # 2. 必填参数校验（不再用硬编码默认值，必须从Web界面传入）
    if not cookie:
        raise RuntimeError("缺少 cookie 参数（请在Web界面上传 cookie 文件）")
    if not excel_path:
        raise RuntimeError("缺少 excel_path 参数（请在Web界面上传 Excel 模板）")
    if not output_dir:
        raise RuntimeError("缺少 output_dir 参数（请在Web界面选择保存目录）")

    logger.info(f"查询日期: {date_str}")

    # 3. 加载Cookie
    cookie_str = load_cookie(cookie)
    if not cookie_str:
        raise RuntimeError("Cookie加载失败")

    # 4. 调用API
    data_list = call_api(date_str, cookie_str)
    logger.info(f"API返回: {len(data_list)} 个SKU")

    # 5. 构建SKU索引
    sku_map = {}
    for item in data_list:
        if len(item) > 1:
            sku_map[clean_sku(str(item[1]))] = item

    # 6. 读取Excel
    df = pd.read_excel(excel_path, header=None)

    # 7. 匹配写入
    found = match_and_write(df, sku_map)
    logger.info(f"匹配完成: {found}/{len(sku_map)}")

    # 8. 保存
    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, f"每日9730销量统计表_{date_str}.xlsx")
    df.to_excel(out_file, index=False, header=False)

    return {"file": out_file, "output_file": out_file, "matched": found, "total": len(sku_map)}


# ==================== 命令行测试 ====================

if __name__ == "__main__":
    print("京东商智竞品数据统计 - 命令行测试")
    date_str = input("查询日期(YYYY-MM-DD，回车默认昨天): ").strip() or None
    cookie = input("Cookie文件路径: ").strip()
    excel_path = input("Excel模板路径: ").strip()
    output_dir = input("输出目录: ").strip()

    result = process(date_str=date_str, cookie=cookie, excel_path=excel_path, output_dir=output_dir)
    print(f"\n✅ {result['matched']}/{result['total']} 匹配成功")
    print(f"📁 {result['file']}")
