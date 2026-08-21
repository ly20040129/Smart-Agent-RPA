# -*- coding: utf-8 -*-
"""京东商智竞品数据统计 - 调API匹配Excel写入保存，cookie从Redis自动读取"""
import os
import re
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from src.core.config import get_config
from sdk.cookie_manager import cookie_manager
from sdk.platforms import init_platforms, get_platform

# 初始化平台工具类
init_platforms()
jd = get_platform("jd")

COOKIE_KEY = "jd_shangzhi"


# ==================== 工具函数 ====================

def clean_sku(sku):
    """只保留数字"""
    return re.sub(r'[^0-9]', '', str(sku).strip())


def fmt(val):
    """去掉 .0"""
    if val is None or val == '':
        return ''
    return str(int(val)) if isinstance(val, float) and val == int(val) else str(val)


# ==================== API调用（非官方网页接口，cookie认证） ====================

def _get_extra_headers():
    """
    商智特有的请求头（用户私有信息从config.yaml读取）

    这些头会merge到平台默认头(default_headers)上，
    其中Referer会覆盖默认的vcnew.jd.com为商智的sz.jd.com
    """
    cfg = get_config().config_data
    jd_cfg = cfg.get('jd_shangzhi', {})

    return {
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "p-pin": jd_cfg.get('p_pin', ''),
        "Referer": "https://sz.jd.com/sz/view/competitionAnalysis/competePros.html",
        "user-mnp": jd_cfg.get('user_mnp', ''),
        "user-mup": jd_cfg.get('user_mup', ''),
        "uuid": jd_cfg.get('uuid', ''),
    }


async def call_api(date_str):
    """
    调用京东商智API（非官方网页接口）

    使用 jd.web_api() 调用：cookie自动注入、失效自动检测+刷新重试。
    商智特有请求头通过headers参数传入，merge到平台默认头。
    """
    url = "https://sz.jd.com/sz/api/competitionAnalysis/getCompeteProDetail.ajax"
    params = {
        "date": date_str,
        "dateType": "day",
        "endDate": date_str,
        "indChannel": "99",
        "startDate": date_str,
        "unitType": "1",
    }

    # 非官方API调用：web_api自动注入cookie + 失效检测 + 自动刷新重试
    result = await jd.web_api(
        url=url,
        cookie_key=COOKIE_KEY,
        method="GET",
        params=params,
        headers=_get_extra_headers(),
    )

    # 商智特有响应格式校验（status字段，与京麦的success字段不同）
    status = result.get('status', '')
    if status in ('1', '2', '99'):
        # web_api的_is_expired未覆盖商智status码，此处补充检测
        cookie_manager.delete(COOKIE_KEY)
        raise RuntimeError(
            f"京东商智API返回登录过期（status={status}），cookie已自动清除。\n"
            f"请去Web界面 → Cookie管理 → 点击「刷新」按钮重新登录京东商智。"
        )

    if status != '0':
        raise RuntimeError(f"API异常: {result}")

    return result.get('content', {}).get('data', [])


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

async def process(date_str=None, excel_path=None, output_dir=None, **kwargs):
    """
    主入口（被task_executor调用）

    Args:
        date_str: 查询日期 YYYY-MM-DD（不传则默认昨天）
        excel_path: Excel模板文件路径（从Web界面上传或用户配置）
        output_dir: 输出目录（从Web界面选择）

    cookie不再需要用户上传，自动从Redis读取（由jd.web_api管理）。
    """
    # 1. 日期处理
    if not date_str:
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # 2. 参数校验
    if not excel_path:
        raise RuntimeError("缺少 excel_path 参数（请在Web界面上传Excel模板）")
    if not output_dir:
        raise RuntimeError("缺少 output_dir 参数（请在Web界面选择保存目录）")

    logger.info(f"查询日期: {date_str}")

    # 3. cookie预检查（平台工具类）
    if not jd.is_cookie_valid(COOKIE_KEY):
        raise RuntimeError(
            f"Cookie不存在或已过期（平台: {COOKIE_KEY}）。\n"
            f"请去Web界面 → Cookie管理 → 点击「刷新」按钮重新登录京东商智。"
        )

    # 4. 调用API（非官方网页接口，cookie由jd.web_api自动管理）
    data_list = await call_api(date_str)
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
