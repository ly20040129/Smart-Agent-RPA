# -*- coding: utf-8 -*-
"""
公众号资金账单自动化任务（重构版）

重构前：551 行，手写 Playwright selector + JS 注入 + 多级兜底点击
重构后：~60 行，browser-use 自然语言驱动，AI 自动操作浏览器

设计原则：金蝶云、网店管家这类老旧系统，不再手写 Playwright selector。
"""
import os
import sys
import asyncio
import shutil
from pathlib import Path
from datetime import datetime

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger
from src.decorators import with_logging, validate_params, ensure_output_dir
from src.tools.browser_use_agent import BrowserUseAgent

TASK_NAME = "公众号资金账单"
LOGIN_URL = "https://pay.weixin.qq.com/index.php/core/home"
COOKIE_KEY = "wechat_pay"


@with_logging(TASK_NAME)
@validate_params("date_from", "date_to")
@ensure_output_dir("output_dir")
async def run(date_from=None, date_to=None, output_dir=None, progress_callback=None, **kwargs):
    """
    task_executor 调用的入口函数（browser-use 自然语言版）

    浏览器操作全部由 AI 完成，不手写任何 selector。
    Cookie 由 BrowserUseAgent 自动从 Redis 读取注入。
    """
    agent = BrowserUseAgent()

    # 1. 登录并导航到资金账单页面
    logger.info("步骤1: 登录微信支付 → 资金账单")
    task = f"""打开 {LOGIN_URL}。
    如果页面需要扫码登录，请提示用户扫码。
    登录成功后，点击「交易中心」菜单，再点击「资金账单」。
    确保页面显示了账单查询表单。"""
    await agent.run(task=task, initial_url=LOGIN_URL)

    # 2. 选择日期范围并查询
    logger.info(f"步骤2: 选择日期 {date_from} ~ {date_to} 并查询")
    task = f"""在当前页面上：
    1. 找到日期选择器，选择开始日期 {date_from}，结束日期 {date_to}
    2. 点击「业务明细账单」按钮
    3. 点击「查询」按钮（如果有的话）"""
    await agent.run(task=task)

    # 3. 点击确认下载
    logger.info("步骤3: 确认下载")
    task = f"""等待确认下载的弹窗出现（通常包含「确 定」或「确认」按钮）。
    点击确认按钮触发下载。
    等待文件下载完成。"""
    await agent.run(task=task)

    # 4. 查找下载文件
    downloaded_file = _find_latest_download()
    if not downloaded_file:
        raise RuntimeError("未获取到下载文件，请检查浏览器")

    # 5. 移动到输出目录
    out_dir = Path(output_dir) if output_dir else (_PROJECT_ROOT / "data" / "downloads")
    out_dir.mkdir(exist_ok=True, parents=True)
    ext = Path(downloaded_file).suffix or ".xlsx"
    out_file = out_dir / f"{TASK_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    if str(Path(downloaded_file).resolve()) != str(out_file.resolve()):
        shutil.copy2(downloaded_file, str(out_file))

    logger.info(f"完成！账单已保存到: {out_file}")
    return str(out_file)


def _find_latest_download():
    """扫描下载目录找最近 10 分钟的文件"""
    import time
    home = Path(os.path.expanduser("~"))
    search_dirs = [
        _PROJECT_ROOT / "data" / "downloads",
        home / "Downloads",
        home / "下载",
    ]
    best, best_mtime = None, time.time() - 600
    for sd in search_dirs:
        if not sd.exists():
            continue
        for p in sd.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".xlsx", ".xls", ".csv", ".zip"):
                continue
            mt = p.stat().st_mtime
            if mt > best_mtime:
                best, best_mtime = str(p), mt
    return best