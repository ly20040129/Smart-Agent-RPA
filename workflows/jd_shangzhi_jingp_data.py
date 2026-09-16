# -*- coding: utf-8 -*-
"""
京东商智竞品数据统计（重构版）

重构前：179 行，手动 Cookie 预检查、参数校验、路径创建
重构后：~90 行，装饰器自动处理 Cookie/日志/参数/路径

设计原则：影刀中几个代码块就能完成的需求，迁移过来后不应过度工程化。
"""
import os
import re
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from src.core.config import get_config
from src.decorators import with_logging, validate_params, ensure_output_dir
from sdk.cookie_manager import cookie_manager
from sdk.platforms import init_platforms, get_platform

init_platforms()
jd = get_platform("jd")
COOKIE_KEY = "jd_shangzhi"


# ==================== 工具函数（业务特有） ====================

def clean_sku(sku):
    return re.sub(r"[^0-9]", "", str(sku).strip())


def fmt(val):
    if val is None or val == "":
        return ""
    return str(int(val)) if isinstance(val, float) and val == int(val) else str(val)


# ==================== API 调用 ====================

def _get_extra_headers():
    cfg = get_config().config_data
    jd_cfg = cfg.get("jd_shangzhi", {})
    return {
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "p-pin": jd_cfg.get("p_pin", ""),
        "Referer": "https://sz.jd.com/sz/view/competitionAnalysis/competePros.html",
        "user-mnp": jd_cfg.get("user_mnp", ""),
        "user-mup": jd_cfg.get("user_mup", ""),
        "uuid": jd_cfg.get("uuid", ""),
    }


async def call_api(date_str):
    url = "https://sz.jd.com/sz/api/competitionAnalysis/getCompeteProDetail.ajax"
    params = {"date": date_str, "dateType": "day", "endDate": date_str,
              "indChannel": "99", "startDate": date_str, "unitType": "1"}
    result = await jd.web_api(url=url, cookie_key=COOKIE_KEY, method="GET",
                              params=params, headers=_get_extra_headers())
    status = result.get("status", "")
    if status in ("1", "2", "99"):
        cookie_manager.delete(COOKIE_KEY)
        raise RuntimeError(f"京东商智API登录过期（status={status}），请去Web界面刷新Cookie")
    if status != "0":
        raise RuntimeError(f"API异常: {result}")
    return result.get("content", {}).get("data", [])


# ==================== 匹配写入 ====================

def match_and_write(df, sku_map):
    found = 0
    for idx in range(2, len(df)):
        sku_val = df.iloc[idx, 2]
        if pd.isna(sku_val):
            continue
        item = sku_map.get(clean_sku(str(sku_val)))
        if item:
            df.iloc[idx, 5] = fmt(item[4].get("range", "") if len(item) > 4 and item[4] else "")
            df.iloc[idx, 6] = fmt(item[6].get("range", "") if len(item) > 6 and item[6] else "")
            found += 1
    return found


# ==================== 主入口 ====================

@with_logging("京东商智竞品统计")
@validate_params("excel_path", "output_dir")
@ensure_output_dir("output_dir")
async def process(date_str=None, excel_path=None, output_dir=None, **kwargs):
    """主入口（被 task_executor 调用）"""
    if not date_str:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info(f"查询日期: {date_str}")

    # Cookie 预检查
    if not jd.is_cookie_valid(COOKIE_KEY):
        raise RuntimeError(f"Cookie不存在或已过期（{COOKIE_KEY}），请去Web界面刷新")

    # 调 API
    data_list = await call_api(date_str)
    logger.info(f"API返回: {len(data_list)} 个SKU")

    # 构建 SKU 索引
    sku_map = {clean_sku(str(item[1])): item for item in data_list if len(item) > 1}

    # 读取 Excel → 匹配 → 保存
    df = pd.read_excel(excel_path, header=None)
    found = match_and_write(df, sku_map)
    logger.info(f"匹配完成: {found}/{len(sku_map)}")

    out_file = os.path.join(output_dir, f"每日9730销量统计表_{date_str}.xlsx")
    df.to_excel(out_file, index=False, header=False)

    return {"file": out_file, "output_file": out_file, "matched": found, "total": len(sku_map)}