# -*- coding: utf-8 -*-
"""
京东艾贝自营仓销售出库 - API接口版（重构版）

重构前：121 行，手动 Cookie 预检查、手动拼接路径
重构后：~60 行，装饰器自动处理 Cookie/日志/参数，data_tools 处理输出

设计原则：影刀中几个代码块就能完成的需求，迁移过来后不应过度工程化。
"""
import sys
from pathlib import Path
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
from loguru import logger

from src.decorators import with_logging, validate_params, ensure_output_dir
from sdk.platforms import init_platforms, get_platform
from sdk.entities import init_entities, get_entity
from sdk.mysql_sdk import MySQL
from sdk.data_tools import save_output

init_platforms()
init_entities()

jd = get_platform("jd")
entity = get_entity("jd_ibay_sales")

TASK_NAME = "京东艾贝自营仓销售出库(API)"
COOKIE_KEY = entity.cookie_key
API_URL = "https://vcf.jd.com/api/finance/saleBill/list"


@with_logging(TASK_NAME)
@validate_params("date_from", "date_to")
@ensure_output_dir("output_dir")
async def run_api(date_from=None, date_to=None, output_dir=None, progress_callback=None, **kwargs):
    """执行 API 采集任务（被 task_executor 调用）"""
    # Cookie 预检查
    if not jd.is_cookie_valid(COOKIE_KEY):
        raise RuntimeError(f"Cookie不存在或已过期（{COOKIE_KEY}），请去Web界面刷新")

    if progress_callback:
        progress_callback(1, f"Cookie已加载（{COOKIE_KEY}）")

    # 分页获取数据
    all_data = await jd.fetch_paged(
        url=API_URL, cookie_key=COOKIE_KEY,
        body_template={"bizType": "4"},
        date_from=date_from, date_to=date_to,
        page_size=1000, progress_callback=progress_callback,
    )

    if not all_data:
        raise RuntimeError("没有获取到数据")

    if progress_callback:
        progress_callback(4, f"正在保存 {len(all_data)} 条数据...")

    # 保存 Excel
    df = pd.DataFrame(all_data)
    out_dir = output_dir or str(Path(r"E:\smart_agent_platform\data\downloads"))
    out_file = save_output(df, out_dir, prefix=TASK_NAME)

    # 同时存 MySQL
    try:
        MySQL.save(out_file, table=entity)
    except Exception as e:
        logger.warning(f"[MySQL] 存储失败（不影响Excel）: {e}")

    if progress_callback:
        progress_callback(5, f"完成！已保存到: {out_file}")

    return all_data, out_file