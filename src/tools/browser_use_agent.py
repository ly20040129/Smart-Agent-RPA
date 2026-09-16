# -*- coding: utf-8 -*-
"""
browser-use 封装 - 用自然语言驱动浏览器自动化

用法：
    agent = BrowserUseAgent()
    result = await agent.run(task="登录京东后导出昨天的销售报表到 data/output/")
    print(result)
"""
import random
from typing import Optional
from loguru import logger

from src.core.llm_client import LocalLLMClient
from src.core.config import get_config
from browser_use import Browser, BrowserProfile

try:
    from browser_use import Agent, Browser, ChatOpenAI
    _BROWSER_USE_AVAILABLE = True
except ImportError:
    _BROWSER_USE_AVAILABLE = False


class BrowserUseAgent:
    """browser-use 薄封装：用自然语言描述任务，AI 自动操作浏览器"""

    # 拟人化：随机UA + 随机窗口 + 反自动化参数（借鉴旧项目 rpaTools）
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]
    _HUMAN_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=zh-CN",
    ]

    def __init__(self, llm: Optional[LocalLLMClient] = None):
        self.llm = llm or LocalLLMClient()
        self.config = get_config()
        self._browser = None

    def _humanize_profile(self) -> dict:
        """生成随机窗口、UA、反自动化参数，降低被识别为机器人的概率"""
        return {
            "user_agent": random.choice(self._USER_AGENTS),
            "window_size": {
                "width": random.randint(1280, 1920),
                "height": random.randint(720, 1080),
            },
            "args": list(self._HUMAN_ARGS),
            "headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        }

    async def _get_or_create_browser(self, headless: bool = False):
        if self._browser is None:
            profile_kwargs = self._humanize_profile()
            profile_kwargs.update(enable_default_extensions=False, headless=headless)
            self._browser = Browser(browser_profile=BrowserProfile(**profile_kwargs))
        return self._browser

    def _build_browser_llm(self):
        """根据当前 provider 构造 browser-use 能用的 ChatOpenAI"""
        provider = self.llm.provider

        if provider == "zhipuai":
            # 智谱的 OpenAI 兼容接口
            return ChatOpenAI(
                model=self.config.llm.zhipuai_model,
                api_key=self.config.llm.zhipuai_api_key,
                base_url="https://open.bigmodel.cn/api/paas/v4",
            )
        elif provider == "deepseek":
            return ChatOpenAI(
                model=self.config.llm.deepseek_model,
                api_key=self.config.llm.deepseek_api_key,
                base_url=self.config.llm.deepseek_base_url,
            )
        else:
            raise ValueError(f"browser-use 暂不支持 {provider}，请切换为 zhipuai 或 deepseek")

    async def run(self, task: str, initial_url: str = None, **kwargs) -> str:
        if not _BROWSER_USE_AVAILABLE:
            hint = "未安装 browser-use，请先执行: pip install browser-use"
            logger.warning(hint)
            return hint

        try:
            browser = await self._get_or_create_browser(headless=False)
            llm = self._build_browser_llm()

            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
                initial_url=initial_url,
                **kwargs,
            )
            result = await agent.run()

            try:
                return result.final_result()
            except Exception:
                return str(result)

        except Exception as e:
            logger.error(f"[browser-use] 执行失败: {e}")
            return f"执行失败: {e}"