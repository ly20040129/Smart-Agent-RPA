# -*- coding: utf-8 -*-
"""
智能异常自修复模块 - LLM驱动的任务失败诊断和自动重试

核心思想：
  传统方式: 任务失败 → 直接返回错误 → 用户手动排查 → 手动重跑
  智能方式: 任务失败 → LLM分析错误原因 → 给出修复策略 → 自动重试（带修正）

错误分类（LLM自动识别）：
  1. 元素找不到     → 页面改版/加载慢   → 等待+重试/换选择器
  2. 超时           → 网络慢/弹窗未出现 → 延长超时+重试
  3. 登录过期       → Cookie失效       → 提示重新登录
  4. 网络错误       → 临时网络问题      → 指数退避重试
  5. 下载失败       → 弹窗未确认/路径错 → 重新触发下载
  6. 数据处理失败   → 列名变化/数据格式 → LLM重新理解数据
  7. 未知错误       → 其他             → 记录日志，建议人工介入

用法（集成在 task_executor.py 中，无需手动调用）：
  from src.agent.smart_recovery import SmartRecovery
  recovery = SmartRecovery()
  strategy = recovery.analyze_error(error_msg, step, context)
  if strategy.should_retry:
      # 按策略修正后重试
"""
import json
import time
import asyncio
from typing import Optional, Dict, Any, List
from enum import Enum
from loguru import logger

from src.core.llm_client import LocalLLMClient


class ErrorType(Enum):
    """错误类型枚举"""
    ELEMENT_NOT_FOUND = "element_not_found"      # 元素找不到
    TIMEOUT = "timeout"                          # 超时
    LOGIN_EXPIRED = "login_expired"              # 登录过期
    NETWORK_ERROR = "network_error"              # 网络错误
    DOWNLOAD_FAILED = "download_failed"          # 下载失败
    DATA_PROCESS_ERROR = "data_process_error"    # 数据处理失败
    PERMISSION_DENIED = "permission_denied"      # 权限不足
    UNKNOWN = "unknown"                          # 未知错误


class RecoveryStrategy:
    """修复策略"""

    def __init__(
        self,
        should_retry: bool = False,
        max_retries: int = 1,
        wait_seconds: float = 2.0,
        error_type: ErrorType = ErrorType.UNKNOWN,
        diagnosis: str = "",
        fix_action: str = "",
        need_human: bool = False,
        modified_params: Optional[Dict] = None,
    ):
        self.should_retry = should_retry
        self.max_retries = max_retries
        self.wait_seconds = wait_seconds
        self.error_type = error_type
        self.diagnosis = diagnosis
        self.fix_action = fix_action
        self.need_human = need_human
        self.modified_params = modified_params or {}

    def to_dict(self) -> Dict:
        return {
            "should_retry": self.should_retry,
            "max_retries": self.max_retries,
            "wait_seconds": self.wait_seconds,
            "error_type": self.error_type.value,
            "diagnosis": self.diagnosis,
            "fix_action": self.fix_action,
            "need_human": self.need_human,
        }


class SmartRecovery:
    """
    智能异常自修复

    用法：
        recovery = SmartRecovery()

        # 任务失败时
        strategy = recovery.analyze_error(
            error_message="元素未找到: 下载按钮",
            step={"type": "browser", "action": "click", "params": {...}},
            context={"current_url": "..."}
        )

        if strategy.should_retry:
            # 等待
            await asyncio.sleep(strategy.wait_seconds)
            # 用修正后的参数重试
            modified_step = apply_fix(step, strategy.modified_params)
            result = await execute_step(modified_step)
    """

    # 规则匹配优先于LLM，节省token
    ERROR_RULES = [
        # (关键字列表, 错误类型, 是否可重试, 建议等待秒数)
        (["元素未找到", "not found", "找不到", "selector", "no element"],
         ErrorType.ELEMENT_NOT_FOUND, True, 3.0),
        (["timeout", "超时", "timed out", "waiting for"],
         ErrorType.TIMEOUT, True, 5.0),
        (["login", "登录", "cookie", "未授权", "401", "passport"],
         ErrorType.LOGIN_EXPIRED, False, 0),
        (["network", "连接", "connection", "ECONN", "socket"],
         ErrorType.NETWORK_ERROR, True, 10.0),
        (["download", "下载", "文件未生成", "no file"],
         ErrorType.DOWNLOAD_FAILED, True, 2.0),
        (["permission", "权限", "forbidden", "403"],
         ErrorType.PERMISSION_DENIED, False, 0),
        (["列名", "column", "KeyError", "数据", "DataFrame"],
         ErrorType.DATA_PROCESS_ERROR, True, 1.0),
    ]

    def __init__(self, llm: Optional[LocalLLMClient] = None):
        self.llm = llm or LocalLLMClient()

    def analyze_error(
        self,
        error_message: str,
        step: Dict,
        context: Optional[Dict] = None,
        use_llm: bool = True,
    ) -> RecoveryStrategy:
        """
        分析错误原因，给出修复策略

        Args:
            error_message: 错误信息
            step: 失败的步骤配置
            context: 执行上下文
            use_llm: 是否使用LLM深度分析（规则匹配失败时才调LLM）

        Returns:
            RecoveryStrategy 修复策略
        """
        context = context or {}
        logger.info(f"[Recovery] 分析错误: {error_message[:100]}")

        # 第一步：规则匹配（快速，不耗token）
        strategy = self._match_rules(error_message, step, context)
        if strategy:
            logger.info(
                f"[Recovery] 规则匹配: type={strategy.error_type.value}, "
                f"retry={strategy.should_retry}"
            )
            return strategy

        # 第二步：LLM深度分析（规则未匹配到）
        if use_llm:
            strategy = self._llm_analyze(error_message, step, context)
            if strategy:
                logger.info(
                    f"[Recovery] LLM分析: type={strategy.error_type.value}, "
                    f"retry={strategy.should_retry}"
                )
                return strategy

        # 兜底：未知错误，不重试
        return RecoveryStrategy(
            should_retry=False,
            error_type=ErrorType.UNKNOWN,
            diagnosis=f"未知错误: {error_message[:200]}",
            need_human=True,
        )

    # ==================== 规则匹配 ====================
    def _match_rules(
        self,
        error: str,
        step: Dict,
        context: Dict,
    ) -> Optional[RecoveryStrategy]:
        """规则匹配（快速，不调LLM）"""
        error_lower = error.lower()

        for keywords, err_type, can_retry, wait in self.ERROR_RULES:
            if any(kw.lower() in error_lower for kw in keywords):
                return self._build_strategy(err_type, can_retry, wait, error, step, context)
        return None

    def _build_strategy(
        self,
        err_type: ErrorType,
        can_retry: bool,
        wait: float,
        error: str,
        step: Dict,
        context: Dict,
    ) -> RecoveryStrategy:
        """根据错误类型构建修复策略"""
        step_type = step.get("type", "")
        step_action = step.get("action", "")

        if err_type == ErrorType.ELEMENT_NOT_FOUND:
            # 元素找不到：可能是页面加载慢，延长超时重试
            modified = self._increase_timeout(step, multiplier=2)
            return RecoveryStrategy(
                should_retry=can_retry,
                max_retries=2,
                wait_seconds=wait,
                error_type=err_type,
                diagnosis=f"元素未找到，可能是页面加载慢或弹窗未出现",
                fix_action="延长超时时间，等待页面完全加载后重试",
                modified_params=modified,
            )

        elif err_type == ErrorType.TIMEOUT:
            # 超时：延长超时 + 指数退避
            modified = self._increase_timeout(step, multiplier=3)
            return RecoveryStrategy(
                should_retry=can_retry,
                max_retries=3,
                wait_seconds=wait,
                error_type=err_type,
                diagnosis="操作超时，可能是网络慢或页面响应慢",
                fix_action="延长超时时间并指数退避重试",
                modified_params=modified,
            )

        elif err_type == ErrorType.LOGIN_EXPIRED:
            # 登录过期：不可自动恢复
            return RecoveryStrategy(
                should_retry=False,
                error_type=err_type,
                diagnosis="登录已过期或Cookie失效",
                fix_action="需要重新登录，已通知用户",
                need_human=True,
            )

        elif err_type == ErrorType.NETWORK_ERROR:
            # 网络错误：指数退避重试
            return RecoveryStrategy(
                should_retry=True,
                max_retries=3,
                wait_seconds=wait,
                error_type=err_type,
                diagnosis="网络连接异常",
                fix_action="指数退避重试（10s/20s/40s）",
            )

        elif err_type == ErrorType.DOWNLOAD_FAILED:
            # 下载失败：重新触发下载
            return RecoveryStrategy(
                should_retry=True,
                max_retries=2,
                wait_seconds=wait,
                error_type=err_type,
                diagnosis="下载未完成，可能是弹窗未确认或路径错误",
                fix_action="重新触发下载，确保保存路径存在",
            )

        elif err_type == ErrorType.DATA_PROCESS_ERROR:
            # 数据处理失败：让LLM重新理解数据
            return RecoveryStrategy(
                should_retry=True,
                max_retries=1,
                wait_seconds=wait,
                error_type=err_type,
                diagnosis="数据处理失败，可能是列名变化或数据格式异常",
                fix_action="LLM重新分析数据结构，适应新的列名",
            )

        elif err_type == ErrorType.PERMISSION_DENIED:
            return RecoveryStrategy(
                should_retry=False,
                error_type=err_type,
                diagnosis="权限不足",
                fix_action="需要管理员权限",
                need_human=True,
            )

        return None

    def _increase_timeout(self, step: Dict, multiplier: float = 2) -> Dict:
        """增大步骤的超时参数"""
        modified = json.loads(json.dumps(step))  # 深拷贝
        params = modified.get("params", {})
        if "timeout" in params:
            params["timeout"] = int(params["timeout"] * multiplier)
        else:
            params["timeout"] = int(15 * multiplier)
        modified["params"] = params
        return modified

    # ==================== LLM深度分析 ====================
    def _llm_analyze(
        self,
        error: str,
        step: Dict,
        context: Dict,
    ) -> Optional[RecoveryStrategy]:
        """LLM深度分析错误原因"""
        system_prompt = """你是自动化任务的异常诊断专家。
用户会给你一个失败的自动化任务信息，你需要：
1. 分析失败的根本原因
2. 判断是否可以通过重试解决
3. 如果可以重试，给出具体的修正建议

返回JSON格式：
{
  "error_type": "element_not_found/timeout/login_expired/network_error/download_failed/data_process_error/unknown",
  "can_retry": true/false,
  "diagnosis": "失败原因分析",
  "fix_action": "修正建议",
  "wait_seconds": 重试前等待秒数,
  "max_retries": 最大重试次数
}"""

        step_info = json.dumps({
            "type": step.get("type"),
            "action": step.get("action"),
            "description": step.get("description", ""),
            "params_keys": list(step.get("params", {}).keys()),
        }, ensure_ascii=False)

        context_info = json.dumps({
            k: str(v)[:100] for k, v in context.items()
            if k in ["current_url", "downloaded_file", "username", "workflow_data_count"]
        }, ensure_ascii=False)

        user_message = f"""失败的步骤信息:
{step_info}

执行上下文:
{context_info}

错误信息:
{error[:500]}

请分析失败原因并给出修复策略。"""

        try:
            reply = self.llm.chat(
                message=user_message,
                system_prompt=system_prompt,
            )

            # 提取JSON
            import re
            json_match = re.search(r'\{[^{}]*\}', reply, re.DOTALL)
            if not json_match:
                logger.warning(f"[Recovery] LLM返回非JSON: {reply[:100]}")
                return None

            analysis = json.loads(json_match.group())

            err_type_str = analysis.get("error_type", "unknown")
            try:
                err_type = ErrorType(err_type_str)
            except ValueError:
                err_type = ErrorType.UNKNOWN

            return RecoveryStrategy(
                should_retry=bool(analysis.get("can_retry", False)),
                max_retries=int(analysis.get("max_retries", 1)),
                wait_seconds=float(analysis.get("wait_seconds", 2)),
                error_type=err_type,
                diagnosis=analysis.get("diagnosis", ""),
                fix_action=analysis.get("fix_action", ""),
                need_human=not analysis.get("can_retry", False),
            )

        except Exception as e:
            logger.error(f"[Recovery] LLM分析失败: {e}")
            return None

    # ==================== 上下文管理 ====================
    def build_retry_context(
        self,
        original_step: Dict,
        strategy: RecoveryStrategy,
        attempt: int,
    ) -> Dict:
        """
        构建重试时的步骤配置

        Args:
            original_step: 原始步骤
            strategy: 修复策略
            attempt: 第几次重试（1, 2, 3...）

        Returns:
            修正后的步骤配置
        """
        import copy
        step = copy.deepcopy(original_step)

        # 应用修正参数
        if strategy.modified_params:
            step.update(strategy.modified_params)

        # 指数退避：每次重试等待时间翻倍
        if attempt > 1:
            wait = strategy.wait_seconds * (2 ** (attempt - 1))
            logger.info(f"[Recovery] 第{attempt}次重试，等待{wait:.1f}秒")

        return step

    def should_continue_retry(
        self,
        attempt: int,
        strategy: RecoveryStrategy,
    ) -> bool:
        """判断是否应该继续重试"""
        if not strategy.should_retry:
            return False
        if attempt >= strategy.max_retries:
            logger.warning(
                f"[Recovery] 已达最大重试次数 {strategy.max_retries}，停止重试"
            )
            return False
        return True

    # ==================== 错误日志 ====================
    def log_recovery(
        self,
        task_id: str,
        step_index: int,
        error: str,
        strategy: RecoveryStrategy,
        attempt: int,
        success: bool,
    ):
        """记录修复日志（供Web端展示）"""
        log_entry = {
            "task_id": task_id,
            "step_index": step_index,
            "error": error[:200],
            "error_type": strategy.error_type.value,
            "diagnosis": strategy.diagnosis,
            "fix_action": strategy.fix_action,
            "attempt": attempt,
            "success": success,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        logger.info(f"[Recovery] 修复记录: {json.dumps(log_entry, ensure_ascii=False)}")

        # 这里可以扩展：写入Redis/MySQL供Web端查询
        try:
            from src.storage import storage_manager
            if storage_manager.is_redis_available:
                storage_manager.redis.client.lpush(
                    "agent:recovery_logs",
                    json.dumps(log_entry, ensure_ascii=False),
                )
                # 只保留最近100条
                storage_manager.redis.client.ltrim("agent:recovery_logs", 0, 99)
        except Exception:
            pass
