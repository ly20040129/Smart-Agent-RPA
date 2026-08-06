# -*- coding: utf-8 -*-
"""
LLM客户端 - 统一接口，支持智谱AI和Ollama

根据 config.yaml 中的 provider 字段自动选择后端:
  - provider: "zhipuai" → 智谱GLM-4-Flash（云端，免费）
  - provider: "ollama"  → Ollama本地模型

对外接口完全统一，所有智能体模块无需修改任何代码。
"""
import time
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
        """同步调用"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )
        return response.choices[0].message.content

    async def ainvoke(self, messages: List[Dict]) -> str:
        """异步调用（智谱SDK暂用同步，包一层asyncio）"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.invoke, messages)

    def stream(self, messages: List[Dict]):
        """流式调用"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            stream=True,
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class OllamaBackend:
    """Ollama本地后端 - 通过langchain调用"""

    def __init__(self, base_url: str, model: str, temperature: float, timeout: int):
        from langchain_ollama import ChatOllama
        from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
        self.ChatOllama = ChatOllama
        self.HumanMessage = HumanMessage
        self.SystemMessage = SystemMessage
        self.AIMessage = AIMessage
        self.llm = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=temperature,
            timeout=timeout,
        )
        self.model = model
        logger.info(f"Ollama后端初始化: model={model}, base_url={base_url}")

    def _to_langchain_messages(self, messages: List[Dict]):
        """把通用消息格式转为langchain格式"""
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
        lc_messages = self._to_langchain_messages(messages)
        response = self.llm.invoke(lc_messages)
        return response.content

    async def ainvoke(self, messages: List[Dict]) -> str:
        lc_messages = self._to_langchain_messages(messages)
        response = await self.llm.ainvoke(lc_messages)
        return response.content

    def stream(self, messages: List[Dict]):
        lc_messages = self._to_langchain_messages(messages)
        for chunk in self.llm.stream(lc_messages):
            yield chunk.content


class LocalLLMClient:
    """
    统一LLM客户端

    根据 config.yaml 的 provider 字段自动选择后端:
      - "zhipuai" → 智谱AI (GLM-4-Flash免费)
      - "ollama"  → 本地Ollama

    对外接口:
      chat()         - 同步对话
      async_chat()   - 异步对话
      stream_chat()  - 流式对话
      clear_history()
      switch_provider()
      get_model_info()
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs
    ):
        self.config = get_config()

        # 确定provider
        self.provider = provider or self.config.llm.provider
        self.temperature = temperature or self.config.llm.temperature

        # 根据provider初始化后端
        self.backend = self._init_backend(model_name, **kwargs)

        # 对话历史
        self.conversation_history: List[Dict[str, str]] = []

        logger.info(
            f"LLM客户端就绪: provider={self.provider}, "
            f"model={self.get_model_name()}, temperature={self.temperature}"
        )

    def _init_backend(self, model_name: Optional[str] = None, **kwargs):
        """根据provider初始化对应后端"""
        if self.provider == "zhipuai":
            return ZhipuAIBackend(
                api_key=self.config.llm.zhipuai_api_key,
                model=model_name or self.config.llm.zhipuai_model,
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
            raise ValueError(f"不支持的LLM提供商: {self.provider}，请选择 zhipuai 或 ollama")

    def get_model_name(self) -> str:
        """获取当前模型名"""
        if self.provider == "zhipuai":
            return self.config.llm.zhipuai_model
        return self.config.llm.model

    def _build_messages(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        use_history: bool = False
    ) -> List[Dict[str, str]]:
        """构建统一格式的消息列表"""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if use_history and self.conversation_history:
            messages.extend(self.conversation_history)

        messages.append({"role": "user", "content": message})
        return messages

    def chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        use_history: bool = False,
        **kwargs
    ) -> str:
        """
        同步对话

        Args:
            message: 用户消息
            system_prompt: 系统提示词
            use_history: 是否使用对话历史

        Returns:
            模型回复
        """
        start_time = time.time()

        messages = self._build_messages(message, system_prompt, use_history)

        try:
            reply = self.backend.invoke(messages)

            if use_history:
                self.conversation_history.append({"role": "user", "content": message})
                self.conversation_history.append({"role": "assistant", "content": reply})

            elapsed = time.time() - start_time
            logger.info(
                f"LLM调用成功 [{self.provider}] - 耗时: {elapsed:.2f}秒, "
                f"输入: {len(message)}字, 输出: {len(reply)}字"
            )

            return reply

        except Exception as e:
            logger.error(f"LLM调用失败 [{self.provider}]: {e}")
            raise

    async def async_chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        use_history: bool = False,
        **kwargs
    ) -> str:
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

    def stream_chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        use_history: bool = False,
        **kwargs
    ):
        """流式对话（用于Web界面实时显示）"""
        messages = self._build_messages(message, system_prompt, use_history)

        try:
            for chunk in self.backend.stream(messages):
                yield chunk
        except Exception as e:
            logger.error(f"流式LLM调用失败 [{self.provider}]: {e}")
            raise

    def clear_history(self) -> None:
        """清空对话历史"""
        self.conversation_history = []
        logger.info("对话历史已清空")

    def set_temperature(self, temperature: float) -> None:
        """动态调整温度参数"""
        self.temperature = temperature
        if self.provider == "ollama":
            self.backend.llm.temperature = temperature
        logger.info(f"温度参数已更新: {temperature}")

    def switch_provider(self, provider: str, model_name: Optional[str] = None) -> None:
        """
        切换LLM提供商

        Args:
            provider: "zhipuai" 或 "ollama"
            model_name: 模型名称（可选）
        """
        old_provider = self.provider
        self.provider = provider
        self.backend = self._init_backend(model_name)
        self.clear_history()
        logger.info(f"LLM提供商已切换: {old_provider} → {provider}")

    def switch_model(self, model_name: str) -> None:
        """切换模型（保持provider不变）"""
        if self.provider == "zhipuai":
            self.backend = ZhipuAIBackend(
                api_key=self.config.llm.zhipuai_api_key,
                model=model_name,
                temperature=self.temperature,
                timeout=self.config.llm.timeout,
            )
        else:
            self.backend = OllamaBackend(
                base_url=self.config.llm.base_url,
                model=model_name,
                temperature=self.temperature,
                timeout=self.config.llm.timeout,
            )
        logger.info(f"模型已切换: {model_name}")

    def get_model_info(self) -> Dict[str, Any]:
        """获取当前模型信息"""
        return {
            "provider": self.provider,
            "model": self.get_model_name(),
            "temperature": self.temperature,
            "history_length": len(self.conversation_history)
        }


# 测试入口
if __name__ == "__main__":
    client = LocalLLMClient()

    print(f"\n当前模型: {client.get_model_info()}")
    print()

    # 简单测试
    response = client.chat(
        "你好，请用一句话介绍你自己",
        system_prompt="你是一个智能体助手，回答要简洁。"
    )
    print(f"回复: {response}\n")

    # 数据处理能力测试
    response = client.chat(
        '一个Excel有"收支类型"和"金额"两列，收支类型有"收入"和"支出"。'
        '请写一行Python代码筛选出所有收入数据并求和。',
        system_prompt="你是一个Python专家，只返回代码，不要解释。"
    )
    print(f"代码测试:\n{response}")
