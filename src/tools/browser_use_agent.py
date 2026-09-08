# -*- coding: utf-8 -*-
"""
browser-use 封装 - 用自然语言驱动浏览器自动化

用法：
    agent = BrowserUseAgent()
    result = await agent.run(task="登录京东后导出昨天的销售报表到 data/output/")
    print(result)  # AI执行的结果

说明：
  - 内部用 browser-use 的 Agent 类，AI 自己找元素操作
  - LLM 优先复用项目的 LocalLLMClient（通过适配器转成 langchain 接口）
  - headless=False，用户能看到浏览器操作过程
  - 若未安装 browser-use，会给出友好提示而不是抛异常
"""
from typing import Optional
from loguru import logger

from src.core.llm_client import LocalLLMClient

# 延迟导入 browser-use，没装也不影响其它模块
try:
    from browser_use import Agent, Browser, BrowserConfig  # type: ignore
    _BROWSER_USE_AVAILABLE = True
except ImportError:
    _BROWSER_USE_AVAILABLE = False


class BrowserUseLLMAdapter:
    """
    把项目的 LocalLLMClient 适配成 browser-use 期望的 langchain ChatModel 接口。

    browser-use 内部会调用 llm.ainvoke(messages)，messages 是 langchain 的
    BaseMessage 列表（Human/AIMessage/SystemMessage 等），返回值需要是 AIMessage。
    这里做一层格式转换，把 langchain 消息转成 LocalLLMClient 认识的
    {"role", "content"} 列表，再调 backend.ainvoke。
    """

    def __init__(self, llm: LocalLLMClient):
        self._llm = llm

    def _to_dict_list(self, messages) -> list:
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage  # type: ignore

        result = []
        for m in messages:
            if isinstance(m, SystemMessage):
                result.append({"role": "system", "content": m.content})
            elif isinstance(m, AIMessage):
                result.append({"role": "assistant", "content": m.content})
            else:
                # HumanMessage 及其它一律按 user 处理
                result.append({"role": "user", "content": getattr(m, "content", str(m))})
        return result

    async def ainvoke(self, messages, **kwargs):
        from langchain_core.messages import AIMessage  # type: ignore

        dict_msgs = self._to_dict_list(messages)
        content = await self._llm.backend.ainvoke(dict_msgs)
        return AIMessage(content=content)

    def invoke(self, messages, **kwargs):
        import asyncio
        return asyncio.run(self.ainvoke(messages, **kwargs))


class BrowserUseAgent:
    """browser-use 薄封装：用自然语言描述任务，AI 自动操作浏览器"""

    def __init__(self, llm: Optional[LocalLLMClient] = None):
        self.llm = llm or LocalLLMClient()

    async def run(self, task: str, initial_url: str = None, **kwargs) -> str:
        """
        执行自然语言浏览器任务

        Args:
            task: 自然语言描述的任务，例如 "打开百度搜索天气"
            initial_url: 起始 URL（可选）
            **kwargs: 透传给 browser-use Agent 的额外参数

        Returns:
            AI 执行结果文本
        """
        if not _BROWSER_USE_AVAILABLE:
            hint = (
                "未安装 browser-use，请先执行: pip install browser-use>=0.1.0\n"
                "安装后即可用自然语言描述浏览器任务，AI 自动操作。"
            )
            logger.warning(hint)
            return hint

        try:
            # headless=False 让用户能看到浏览器
            browser = Browser(config=BrowserConfig(headless=False))
            agent = Agent(
                task=task,
                llm=BrowserUseLLMAdapter(self.llm),
                browser=browser,
                initial_url=initial_url,
                **kwargs,
            )
            result = await agent.run()

            # browser-use 的 run 返回 AgentOutput，用 final_result() 取最终文本
            try:
                return result.final_result()
            except Exception:
                return str(result)

        except Exception as e:
            logger.error(f"[browser-use] 执行失败: {e}")
            return f"执行失败: {e}"
