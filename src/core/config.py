# -*- coding: utf-8 -*-
"""
全局配置管理器

加载 config/config.yaml，提供两种访问方式：
  1. config.config_data["xxx"]["yyy"]  —— 原始字典，任意节点都能取
  2. config.llm / config.browser / config.web / config.agent —— 解析后的对象
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from loguru import logger
from pydantic import BaseModel

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"
_EXAMPLE_PATH = _PROJECT_ROOT / "config" / "config.example.yaml"


class LLMConfig(BaseModel):
    provider: str = "zhipuai"
    zhipuai_api_key: str = ""
    zhipuai_model: str = "glm-4-flash"
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.1
    timeout: int = 60


class BrowserConfig(BaseModel):
    headless: bool = False
    browser_type: str = "chromium"
    slow_mo: int = 100
    timeout: int = 30000
    screenshot_on_error: bool = True


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False


class AgentConfig(BaseModel):
    max_retries: int = 3
    retry_delay: int = 5


class Config:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else _CONFIG_PATH
        self.config_data: Dict[str, Any] = self._load()
        self._parse()

    def _load(self) -> Dict[str, Any]:
        path = self.config_path
        if not path.exists():
            logger.warning(f"配置文件不存在: {path}，尝试加载 example")
            path = _EXAMPLE_PATH
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _parse(self):
        d = self.config_data
        llm = d.get("llm", {})
        if llm.get("provider") == "zhipuai":
            z = llm.get("zhipuai", {})
            self.llm = LLMConfig(
                provider="zhipuai",
                zhipuai_api_key=z.get("api_key", ""),
                zhipuai_model=z.get("model", "glm-4-flash"),
                temperature=z.get("temperature", 0.1),
                timeout=z.get("timeout", 60),
            )
        elif llm.get("provider") == "deepseek":
            ds = llm.get("deepseek", {})
            self.llm = LLMConfig(
                provider="deepseek",
                deepseek_api_key=ds.get("api_key", ""),
                deepseek_base_url=ds.get("base_url", ""),
                deepseek_model=ds.get("model", ""),
                temperature=ds.get("temperature", 0.1),
                timeout=ds.get("timeout", 60),
            )
        else:
            self.llm = LLMConfig(provider=llm.get("provider", "zhipuai"))

        b = d.get("browser", {})
        self.browser = BrowserConfig(**b) if b else BrowserConfig()

        w = d.get("web", {})
        self.web = WebConfig(**w) if w else WebConfig()

        a = d.get("agent", {})
        self.agent = AgentConfig(**a) if a else AgentConfig()

        self.storage = d.get("storage", {})
        self.workflows = d.get("workflows", {})

    @property
    def mysql_pro(self) -> Dict[str, Any]:
        return self.config_data.get("mysql_pro", {})


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
