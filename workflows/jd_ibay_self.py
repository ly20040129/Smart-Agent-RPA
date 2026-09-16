# -*- coding: utf-8 -*-
"""
京东艾贝自营仓销售出库 - 浏览器方案（重构版）

重构前：251 行，手写 Playwright + JS 注入 React 受控组件 + 多级兜底
重构后：~60 行，browser-use 自然语言驱动，AI 自动操作浏览器

设计原则：ant-design 复杂 DOM 不再手写 selector，全交给 AI。
"""
import sys
import asyncio
from pathlib import Path
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
from loguru import logger

from src.decorators import with_logging, validate_params, ensure_output_dir
from src.tools.browser_use_agent import BrowserUseAgent
from sdk.entities import init_entities, get_entity
from sdk.data_tools import save_output

init_entities()

TASK_NAME = "京东艾贝自营仓销售出库"
LOGIN_URL = "https://shop.jd.com/jdm/home"
TARGET_URL = "https://vcnew.jd.com/finance/actualSalesSolidDetails"


@with_logging(TASK_NAME)
@validate_params("date_from", "date_to")
@ensure_output_dir("output_dir")
async def run(date_from=None, date_to=None, output_dir=None, progress_callback=None, **kwargs):
    """
    task_executor 调用的入口函数（browser-use 自然语言版）

    浏览器操作全部由 AI 完成：登录 → 导航 → 填日期 → 查询 → 提取表格 → 导出。
    """
    agent = BrowserUseAgent()

    # 1. 登录京东
    logger.info("步骤1: 登录京东商家后台")
    task = f"""打开 {LOGIN_URL}。
    如果页面需要登录，请提示用户扫码或输入账号密码。
    登录成功后确认页面显示了商家后台主界面。"""
    await agent.run(task=task, initial_url=LOGIN_URL)

    # 2. 导航到实销实结明细
    logger.info("步骤2: 导航到实销实结明细")
    task = f"""打开 {TARGET_URL}。
    等待页面加载完成，确认显示了实销实结明细列表或业务日期筛选框。"""
    await agent.run(task=task)

    # 3. 填写日期并查询
    logger.info(f"步骤3: 填写日期 {date_from} ~ {date_to} 并查询")
    task = f"""在当前页面上：
    1. 找到日期范围选择器（通常是 ant-design 的 RangePicker）
    2. 设置开始日期为 {date_from}，结束日期为 {date_to}
    3. 点击「查询」按钮
    4. 等待表格数据加载完成
    5. 设置每页显示 1000 条（如果页面有分页选项）"""
    await agent.run(task=task)

    # 4. 提取表格数据
    logger.info("步骤4: 提取表格数据")
    task = """滚动页面加载所有数据行。
    提取表格中所有数据（从「单据类型」列开始），以 JSON 数组格式返回，
    每行是一个对象，key 是列名。"""
    result = await agent.run(task=task)

    # 5. 保存 Excel
    df = pd.DataFrame(result if isinstance(result, list) else [])
    if len(df) == 0:
        raise RuntimeError("没有提取到表格数据")

    out_dir = output_dir or str(Path(r"E:\smart_agent_platform\data\downloads"))
    out_file = save_output(df, out_dir, prefix=TASK_NAME)
    logger.info(f"已保存到: {out_file}（共 {len(df)} 行 x {len(df.columns)} 列）")

    return result, out_file