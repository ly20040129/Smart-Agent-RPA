# -*- coding: utf-8 -*-
"""
LLM客户端 - 统一接口
  provider: "zhipuai"  → 智谱GLM-4-Flash
  provider: "deepseek" → DeepSeek-V4 (ModelScope, OpenAI兼容接口)
  provider: "ollama"   → 本地Ollama
"""
import time
import json
from typing import Dict, List, Optional, Any
from loguru import logger

from src.core.config import get_config


class ZhipuAIBackend:
    """智谱AI后端"""

    def __init__(self, api_key: str, model: str, temperature: float, timeout: int):
        from zhipuai import ZhipuAI
        self.client = ZhipuAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        logger.info(f"智谱AI后端初始化: model={model}")

    def invoke(self, messages: List[Dict]) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature)
        return resp.choices[0].message.content

    async def ainvoke(self, messages: List[Dict]) -> str:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(None, self.invoke, messages)

    def stream(self, messages: List[Dict]):
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature, stream=True)
        for chunk in resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class DeepSeekBackend:
    """DeepSeek后端 - ModelScope OpenAI兼容接口"""

    def __init__(self, api_key: str, base_url: str, model: str, temperature: float, timeout: int):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        logger.info(f"DeepSeek后端初始化: model={model}")

    def invoke(self, messages: List[Dict]) -> str:
        import requests
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": 2048},
            timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices")
        if not choices:
            raise RuntimeError(f"API返回空结果，可能模型不可用或额度不足: {data}")
        return choices[0]["message"]["content"]

    async def ainvoke(self, messages: List[Dict]) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": 2048})
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices")
            if not choices:
                raise RuntimeError(f"API返回空结果，可能模型不可用或额度不足: {data}")
            return choices[0]["message"]["content"]

    def stream(self, messages: List[Dict]):
        import requests
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": self.temperature, "stream": True},
            timeout=self.timeout, stream=True)
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                data = line[6:]
                if data == b"[DONE]":
                    break
                delta = json.loads(data)["choices"][0].get("delta", {}).get("content", "")
                if delta:
                    yield delta


class OllamaBackend:
    """Ollama本地后端"""

    def __init__(self, base_url: str, model: str, temperature: float, timeout: int):
        from langchain_ollama import ChatOllama
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        self.HumanMessage = HumanMessage
        self.SystemMessage = SystemMessage
        self.AIMessage = AIMessage
        self.llm = ChatOllama(model=model, base_url=base_url, temperature=temperature, timeout=timeout)
        self.model = model
        logger.info(f"Ollama后端初始化: model={model}")

    def _to_lc(self, messages: List[Dict]):
        m = {"system": self.SystemMessage, "user": self.HumanMessage, "assistant": self.AIMessage}
        return [m[msg["role"]](content=msg["content"]) for msg in messages]

    def invoke(self, messages: List[Dict]) -> str:
        return self.llm.invoke(self._to_lc(messages)).content

    async def ainvoke(self, messages: List[Dict]) -> str:
        return (await self.llm.ainvoke(self._to_lc(messages))).content

    def stream(self, messages: List[Dict]):
        for chunk in self.llm.stream(self._to_lc(messages)):
            yield chunk.content


class LocalLLMClient:
    """统一LLM客户端 - 对外接口不变，后端可切换"""

    def __init__(self, provider: Optional[str] = None, model_name: Optional[str] = None,
                 temperature: Optional[float] = None, **kwargs):
        self.config = get_config()
        self.provider = provider or self.config.llm.provider
        self.temperature = temperature or self.config.llm.temperature
        self.backend = self._init_backend(model_name, **kwargs)
        self.conversation_history: List[Dict[str, str]] = []
        logger.info(f"LLM就绪: provider={self.provider}, model={self.get_model_name()}")

    def _init_backend(self, model_name: Optional[str] = None, **kwargs):
        if self.provider == "zhipuai":
            return ZhipuAIBackend(self.config.llm.zhipuai_api_key,
                                  model_name or self.config.llm.zhipuai_model,
                                  self.temperature, self.config.llm.timeout)
        elif self.provider == "deepseek":
            return DeepSeekBackend(self.config.llm.deepseek_api_key,
                                    self.config.llm.deepseek_base_url,
                                    model_name or self.config.llm.deepseek_model,
                                    self.temperature, self.config.llm.timeout)
        elif self.provider == "ollama":
            return OllamaBackend(self.config.llm.base_url,
                                 model_name or self.config.llm.model,
                                 self.temperature, self.config.llm.timeout)
        raise ValueError(f"不支持的LLM: {self.provider}")

    def get_model_name(self) -> str:
        if self.provider == "zhipuai":
            return self.config.llm.zhipuai_model
        elif self.provider == "deepseek":
            return self.config.llm.deepseek_model
        return self.config.llm.model

    def _build_messages(self, message: str, system_prompt: str = None, use_history: bool = False):
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        if use_history and self.conversation_history:
            msgs.extend(self.conversation_history)
        msgs.append({"role": "user", "content": message})
        return msgs

    def chat(self, message: str, system_prompt: str = None, use_history: bool = False, **kwargs) -> str:
        msgs = self._build_messages(message, system_prompt, use_history)
        try:
            reply = self.backend.invoke(msgs)
            if use_history:
                self.conversation_history.append({"role": "user", "content": message})
                self.conversation_history.append({"role": "assistant", "content": reply})
            logger.info(f"LLM调用成功 [{self.provider}] - {time.time():.0f}, 输出{len(reply)}字")
            return reply
        except Exception as e:
            logger.error(f"LLM调用失败 [{self.provider}]: {e}")
            raise

    async def async_chat(self, message: str, system_prompt: str = None, use_history: bool = False, **kwargs) -> str:
        msgs = self._build_messages(message, system_prompt, use_history)
        reply = await self.backend.ainvoke(msgs)
        if use_history:
            self.conversation_history.append({"role": "user", "content": message})
            self.conversation_history.append({"role": "assistant", "content": reply})
        return reply

    def stream_chat(self, message: str, system_prompt: str = None, use_history: bool = False, **kwargs):
        msgs = self._build_messages(message, system_prompt, use_history)
        yield from self.backend.stream(msgs)

    def clear_history(self):
        self.conversation_history = []

    def switch_provider(self, provider: str, model_name: str = None):
        self.provider = provider
        self.backend = self._init_backend(model_name)
        self.clear_history()

    def get_model_info(self) -> Dict[str, Any]:
        return {"provider": self.provider, "model": self.get_model_name(),
                "temperature": self.temperature, "history": len(self.conversation_history)}
