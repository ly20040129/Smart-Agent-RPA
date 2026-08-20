# -*- coding: utf-8 -*-
"""
LLM客户端 - 统一接口，支持多个模型提供商

根据 config.yaml 中的 provider 字段自动选择后端:
  - provider: "zhipuai"   → 智谱GLM-4-Flash（云端，免费）
  - provider: "deepseek"  → DeepSeek-V4（ModelScope，OpenAI兼容接口）
  - provider: "ollama"    → Ollama本地模型

对外接口完全统一，所有智能体模块无需修改任何代码。
"""
import time
import json
from typing import Dict, List, Optional, Any
from loguru import logger

from src.core.config import get_config


class ZhipuAIBackend:
    """智谱AI后端 - 通过官方SDK调用GLM-4-Flash"""

    def __init__(self, api_key: str, model: str, temperature: float, timeout: int):
        from zhipuai import ZhipuAI
        self.client = ZhipuAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        logger.info(f"智谱AI后端初始化: model={model}")

    def invoke(self, messages: List[Dict]) -> str:
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature,
        )
        return response.choices[0].message.content

    async def ainvoke(self, messages: List[Dict]) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.invoke, messages)

    def stream(self, messages: List[Dict]):
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature, stream=True,
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class DeepSeekBackend:
    """DeepSeek后端 - 通过ModelScope的OpenAI兼容API调用"""

    def __init__(self, api_key: str, base_url: str, model: str, temperature: float, timeout: int):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        logger.info(f"DeepSeek后端初始化: model={model}, base_url={base_url}")

    def invoke(self, messages: List[Dict]) -> str:
        """同步调用（用requests）"""
        import requests
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": self.temperature},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def ainvoke(self, messages: List[Dict]) -> str:
        """异步调用（用httpx）"""
        import httpx
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "messages": messages, "temperature": self.temperature},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    def stream(self, messages: List[Dict]):
        """流式调用"""
        import requests
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": self.temperature, "stream": True},
            timeout=self.timeout, stream=True,
        )
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                data = line[6:]
                if data == b"[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {}).get("content", "")
                if delta:
                    yield delta


class OllamaBackend:
    """Ollama本地后端 - 通过langchain调用"""

    def __init__(self, base_url: str, model: str, temperature: float, timeout: int):
        from langchain_ollama import ChatOllama
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        self.ChatOllama = ChatOllama
        self.HumanMessage = HumanMessage
        self.SystemMessage = SystemMessage
        self.AIMessage = AIMessage
        self.llm = ChatOllama(
            model=model, base_url=base_url, temperature=temperature, timeout=timeout,
        )
        self.model = model
        logger.info(f"Ollama后端初始化: model={model}, base_url={base_url}")

    def _to_langchain_messages(self, messages: List[Dict]):
        result = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                result.append(self.SystemMessage(content=content))
            elif role == "user":
                result.append(self.HumanMessage(content=content))
            elif role == "assistant":
                result.append(self.AIMessage(content=content))
        return result

    def invoke(self, messages: List[Dict]) -> str:
        response = self.llm.invoke(self._to_langchain_messages(messages))
        return response.content

    async def ainvoke(self, messages: List[Dict]) -> str:
        response = await self.llm.ainvoke(self._to_langchain_messages(messages))
        return response.content

    def stream(self, messages: List[Dict]):
        for chunk in self.llm.stream(self._to_langchain_messages(messages)):
            yield chunk.content


class LocalLLMClient:
    """
    统一LLM客户端

    根据 config.yaml 的 provider 字段自动选择后端:
      - "zhipuai"  → 智谱AI
      - "deepseek" → DeepSeek (ModelScope)
      - "ollama"   → 本地Ollama

    对外接口:
      chat()         - 同步对话
      async_chat()   - 异步对话
      stream_chat()  - 流式对话
      switch_provider() - 切换模型提供商
    """

    def __init__(self, provider: Optional[str] = None, model_name: Optional[str] = None,
                 temperature: Optional[float] = None, **kwargs):
        self.config = get_config()
        self.provider = provider or self.config.llm.provider
        self.temperature = temperature or self.config.llm.temperature
        self.backend = self._init_backend(model_name, **kwargs)
        self.conversation_history: List[Dict[str, str]] = []
        logger.info(f"LLM客户端就绪: provider={self.provider}, model={self.get_model_name()}")

    def _init_backend(self, model_name: Optional[str] = None, **kwargs):
        """根据provider初始化对应后端"""
        if self.provider == "zhipuai":
            return ZhipuAIBackend(
                api_key=self.config.llm.zhipuai_api_key,
                model=model_name or self.config.llm.zhipuai_model,
                temperature=self.temperature,
                timeout=self.config.llm.timeout,
            )
        elif self.provider == "deepseek":
            return DeepSeekBackend(
                api_key=self.config.llm.deepseek_api_key,
                base_url=self.config.llm.deepseek_base_url,
                model=model_name or self.config.llm.deepseek_model,
                temperature=self.temperature,
                timeout=self.config.llm.timeout,
            )
        elif self.provider == "ollama":
            return OllamaBackend(
                base_url=self.config.llm.base_url,
                model=model_name or self.config.llm.model,
                temperature=self.temperature,
                timeout=self.config.llm.timeout,
            )
        else:
            raise ValueError(f"不支持的LLM提供商: {self.provider}，可选: zhipuai / deepseek / ollama")

    def get_model_name(self) -> str:
        if self.provider == "zhipuai":
            return self.config.llm.zhipuai_model
        elif self.provider == "deepseek":
            return self.config.llm.deepseek_model
        return self.config.llm.model

    def _build_messages(self, message: str, system_prompt: Optional[str] = None,
                        use_history: bool = False) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if use_history and self.conversation_history:
            messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": message})
        return messages

    def chat(self, message: str, system_prompt: Optional[str] = None,
             use_history: bool = False, **kwargs) -> str:
        """同步对话"""
        start_time = time.time()
        messages = self._build_messages(message, system_prompt, use_history)
        try:
            reply = self.backend.invoke(messages)
            if use_history:
                self.conversation_history.append({"role": "user", "content": message})
                self.conversation_history.append({"role": "assistant", "content": reply})
            elapsed = time.time() - start_time
            logger.info(f"LLM调用成功 [{self.provider}] - 耗时: {elapsed:.2f}秒, 输出: {len(reply)}字")
            return reply
        except Exception as e:
            logger.error(f"LLM调用失败 [{self.provider}]: {e}")
            raise

    async def async_chat(self, message: str, system_prompt: Optional[str] = None,
                         use_history: bool = False, **kwargs) -> str:
        """异步对话"""
        start_time = time.time()
        messages = self._build_messages(message, system_prompt, use_history)
        try:
            reply = await self.backend.ainvoke(messages)
            if use_history:
                self.conversation_history.append({"role": "user", "content": message})
                self.conversation_history.append({"role": "assistant", "content": reply})
            elapsed = time.time() - start_time
            logger.info(f"异步LLM调用成功 [{self.provider}] - 耗时: {elapsed:.2f}秒")
            return reply
        except Exception as e:
            logger.error(f"异步LLM调用失败 [{self.provider}]: {e}")
            raise

    def stream_chat(self, message: str, system_prompt: Optional[str] = None,
                    use_history: bool = False, **kwargs):
        """流式对话"""
        messages = self._build_messages(message, system_prompt, use_history)
        try:
            for chunk in self.backend.stream(messages):
                yield chunk
        except Exception as e:
            logger.error(f"流式LLM调用失败 [{self.provider}]: {e}")
            raise

    def clear_history(self) -> None:
        self.conversation_history = []

    def switch_provider(self, provider: str, model_name: Optional[str] = None) -> None:
        """切换LLM提供商"""
        old = self.provider
        self.provider = provider
        self.backend = self._init_backend(model_name)
        self.clear_history()
        logger.info(f"LLM提供商已切换: {old} → {provider}")

    def switch_model(self, model_name: str) -> None:
        """切换模型（保持provider不变）"""
        self.backend = self._init_backend(model_name)
        logger.info(f"模型已切换: {model_name}")

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.get_model_name(),
            "temperature": self.temperature,
            "history_length": len(self.conversation_history)
        }


if __name__ == "__main__":
    client = LocalLLMClient()
    print(f"\n当前模型: {client.get_model_info()}\n")
    response = client.chat("你好，请用一句话介绍你自己",
                           system_prompt="你是一个智能体助手，回答要简洁。")
    print(f"回复: {response}\n")
