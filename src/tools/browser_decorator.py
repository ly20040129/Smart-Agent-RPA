# -*- coding: utf-8 -*-
"""
browser-use 装饰器封装 - 用最少的代码驱动浏览器

三种用法（从简单到灵活）：

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法1：@browser_task  —— 单步任务，最简单
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @browser_task("登录京东后台 https://trade.jd.com")
    async def login_jd(result=None):
        # result 是 browser-use 执行后的返回值
        print(f"登录结果: {result}")
        return result

    # 调用：await login_jd()
    # 也支持 yaml: action: run_workflow → function: login_jd

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法2：@browser_flow  —— 多步链式，同一个浏览器会话
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @browser_flow(
        initial_url="https://trade.jd.com",
        cookie_domain="jd.com",
        steps=[
            "登录京东后台",
            "点击订单管理 → 导出",
            "选昨天日期，确认导出",
            "等待下载完成",
        ],
    )
    async def jd_daily_export(results=None):
        # results 是每一步的返回值列表
        # 这里做 Excel 处理、发钉钉等后续逻辑
        return {"status": "success", "downloads": results}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法3：BrowserSession  —— 上下文管理器，最灵活
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def complex_task():
        async with BrowserSession(cookie_domain="jd.com") as session:
            await session.do("登录京东后台")
            data = await session.do("获取页面上所有订单号的列表")
            # 中间可以判断、循环、分支
            if "失败" in str(data):
                await session.do("重新点击导出")
            # 最后做 Excel 处理
            return {"status": "success"}
"""
import functools
import asyncio
from typing import Callable, List, Optional

from loguru import logger

# 延迟导入，避免没装 browser-use 时整个模块都 import 失败
try:
    from browser_use import Agent, Browser  # type: ignore
    _BU_AVAILABLE = True
except ImportError:
    _BU_AVAILABLE = False


def _get_llm():
    """获取项目的 LLM（复用 browser_use_agent 里已有的适配器）"""
    from src.tools.browser_use_agent import BrowserUseLLMAdapter
    from src.core.llm_client import LocalLLMClient
    return BrowserUseLLMAdapter(LocalLLMClient())


def _load_cookies(browser, domain: str):
    """从 Redis 加载 cookie 注入到浏览器（如果有的话）"""
    if not domain or not _BU_AVAILABLE:
        return
    try:
        from src.storage.storage_manager import storage_manager
        cookies = storage_manager.load_cookies(domain)
        if cookies and browser:
            # browser-use 的 Browser 对象有 context，可以加 cookie
            # 不同版本 API 略有差异，这里做兼容
            try:
                context = browser._context
                if context:
                    import asyncio as _aio
                    _aio.get_event_loop().run_until_complete(
                        context.add_cookies(cookies)
                    )
            except Exception:
                pass  # cookie 加载失败不阻断任务
            logger.debug(f"[browser-deco] 已加载 {len(cookies)} 条 cookie: {domain}")
    except Exception as e:
        logger.debug(f"[browser-deco] cookie加载跳过: {e}")


def _save_cookies(browser, domain: str):
    """任务完成后保存 cookie 到 Redis"""
    if not domain or not _BU_AVAILABLE:
        return
    try:
        from src.storage.storage_manager import storage_manager
        context = getattr(browser, "_context", None)
        if context:
            cookies = asyncio.get_event_loop().run_until_complete(
                context.cookies()
            )
            if cookies:
                storage_manager.save_cookies(domain, cookies)
                logger.debug(f"[browser-deco] 已保存 {len(cookies)} 条 cookie: {domain}")
    except Exception as e:
        logger.debug(f"[browser-deco] cookie保存跳过: {e}")


# ═══════════════════════════════════════════════
#  装饰器1：@browser_task —— 单步任务
# ═══════════════════════════════════════════════

def browser_task(
    task: str = "",
    initial_url: str = "",
    cookie_domain: str = "",
    headless: bool = False,
):
    """
    装饰器：用自然语言执行单个浏览器任务

    Args:
        task: 自然语言任务描述（留空则用函数的 docstring）
        initial_url: 起始页面 URL
        cookie_domain: cookie 存储域名（留空则不存取 cookie）
        headless: 是否无头模式（默认 False，能看到浏览器）
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if not _BU_AVAILABLE:
                msg = "未安装 browser-use，请先: pip install browser-use"
                logger.warning(msg)
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, result=msg, **kwargs)
                return func(*args, result=msg, **kwargs)

            task_desc = task or (func.__doc__ or "").strip() or str(func.__name__)
            llm = _get_llm()
            browser = Browser(headless=headless, enable_default_extensions=False, disable_security=True)

            if cookie_domain:
                _load_cookies(browser, cookie_domain)

            agent = Agent(
                task=task_desc,
                llm=llm,
                browser=browser,
                initial_url=initial_url or None,
            )
            result = await agent.run()
            try:
                result_text = result.final_result()
            except Exception:
                result_text = str(result)

            if cookie_domain:
                _save_cookies(browser, cookie_domain)

            # 把结果传给原函数做后处理
            if asyncio.iscoroutinefunction(func):
                return await func(*args, result=result_text, **kwargs)
            return func(*args, result=result_text, **kwargs)

        wrapper._browser_task = True
        wrapper._task_desc = task
        return wrapper
    return decorator


# ═══════════════════════════════════════════════
#  装饰器2：@browser_flow —— 多步链式
# ═══════════════════════════════════════════════

def browser_flow(
    initial_url: str = "",
    cookie_domain: str = "",
    steps: List[str] = None,
    headless: bool = False,
):
    """
    装饰器：链式执行多个浏览器步骤（同一个浏览器会话）

    Args:
        initial_url: 起始页面
        cookie_domain: cookie 域名
        steps: 每一步的自然语言描述
        headless: 无头模式

    用法：
        @browser_flow(
            initial_url="https://trade.jd.com",
            cookie_domain="jd.com",
            steps=["登录", "导出报表", "等待下载"],
        )
        async def my_task(results=None):
            # results[0], results[1], results[2] 是每步的返回值
            return {"status": "success"}
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if not _BU_AVAILABLE:
                msg = "未安装 browser-use，请先: pip install browser-use"
                logger.warning(msg)
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, results=[msg], **kwargs)
                return func(*args, results=[msg], **kwargs)

            llm = _get_llm()
            browser = Browser(headless=headless, enable_default_extensions=False, disable_security=True)

            if cookie_domain:
                _load_cookies(browser, cookie_domain)

            results = []
            for i, step_desc in enumerate(steps or []):
                logger.info(f"[browser-flow] 步骤 {i+1}/{len(steps)}: {step_desc}")
                agent = Agent(
                    task=step_desc,
                    llm=llm,
                    browser=browser,
                    # 只有第一步传 initial_url
                    initial_url=initial_url if i == 0 else None,
                )
                step_result = await agent.run()
                try:
                    results.append(step_result.final_result())
                except Exception:
                    results.append(str(step_result))

            if cookie_domain:
                _save_cookies(browser, cookie_domain)

            if asyncio.iscoroutinefunction(func):
                return await func(*args, results=results, **kwargs)
            return func(*args, results=results, **kwargs)

        wrapper._browser_flow = True
        return wrapper
    return decorator


# ═══════════════════════════════════════════════
#  上下文管理器：BrowserSession —— 最灵活
# ═══════════════════════════════════════════════

class BrowserSession:
    """
    上下文管理器：灵活控制浏览器会话

    用法：
        async with BrowserSession(cookie_domain="jd.com") as session:
            await session.do("登录京东后台")
            data = await session.do("获取页面上所有订单号")
            if "失败" in str(data):
                await session.do("重新点击导出")
    """

    def __init__(
        self,
        cookie_domain: str = "",
        headless: bool = False,
        initial_url: str = "",
    ):
        self.cookie_domain = cookie_domain
        self.headless = headless
        self.initial_url = initial_url
        self._browser = None
        self._llm = None

    async def __aenter__(self):
        if not _BU_AVAILABLE:
            raise RuntimeError("未安装 browser-use，请先: pip install browser-use")
        self._browser = Browser(headless=self.headless, enable_default_extensions=False, disable_security=True)
        self._llm = _get_llm()
        if self.cookie_domain:
            _load_cookies(self._browser, self.cookie_domain)
        if self.initial_url:
            await self.do(f"打开页面 {self.initial_url}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.cookie_domain and self._browser:
            _save_cookies(self._browser, self.cookie_domain)
        # browser-use 的 Browser 会自动清理
        return False

    async def do(self, task: str) -> str:
        """执行一个浏览器操作，返回结果文本"""
        logger.info(f"[browser-session] 执行: {task}")
        agent = Agent(
            task=task,
            llm=self._llm,
            browser=self._browser,
        )
        result = await agent.run()
        try:
            return result.final_result()
        except Exception:
            return str(result)

    async def get(self, task: str) -> str:
        """获取页面数据（和 do 一样，语义上更清晰）"""
        return await self.do(task)
