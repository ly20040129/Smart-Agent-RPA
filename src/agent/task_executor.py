# -*- coding: utf-8 -*-
"""
任务执行器（编排层）

只负责「加载任务 → 加锁 → 循环步骤 → 自修复 → 存历史 → 成败通知」。
各步骤类型的动作实现都在 src/agent/steps/ 下，通过 STEP_HANDLERS 注册表分发，
避免把所有逻辑堆在单个方法里。
"""
import asyncio
import time
from typing import Any, Dict, Optional

from loguru import logger

from src.agent.delivery_service import DeliveryService
from src.agent.notifier import Notifier, build_notifier
from src.agent.smart_data_processor import SmartDataProcessor
from src.agent.steps import STEP_HANDLERS
from src.agent.steps.base import resolve_placeholders
from src.agent.task_manager import TaskManager
from src.agent.template_manager import TemplateManager
from src.core.config import get_config
from src.storage import storage_manager


class TaskExecutor:
    """任务执行器（编排层）"""

    def __init__(self):
        self.browser_agent = None
        self.smart_desktop = None
        self.data_processor = SmartDataProcessor()
        self.task_manager = TaskManager()
        self.delivery_service = DeliveryService()
        self.template_manager = TemplateManager()
        self.recovery = None
        self._current_user = None
        self.notifier: Optional[Notifier] = None

    def set_user(self, user_info: Dict):
        self._current_user = user_info

    async def execute_task(self, task_id: str, user_params: Dict = None, job_id: Optional[str] = None) -> Dict[str, Any]:
        task_config = self.task_manager.get_task(task_id)
        if not task_config:
            return {"status": "failed", "error": f"任务不存在: {task_id}"}
        if not task_config.get("enabled", True):
            return {"status": "failed", "error": "任务已禁用"}

        user_config = self._current_user.get("config", {}) if self._current_user else {}
        username = self._current_user.get("username", "") if self._current_user else ""
        self.notifier = build_notifier(task_config=task_config, user_config=user_config)

        logger.info(f"{'=' * 60}")
        logger.info(f"开始执行任务: {task_config.get('name', task_id)} (job={job_id or 'direct'})")
        logger.info(f"{'=' * 60}")

        start_time = time.time()
        steps = task_config.get("steps", [])
        context = self._build_context(task_id, task_config, user_params, username, user_config)
        lock_name = f"task:{task_id}:{job_id}" if job_id else f"task:{task_id}"
        lock_acquired = False
        cookie_key = task_config.get("cookie_key", "")
        cookie_use_owner = job_id or task_id
        cookie_use_acquired = False
        result: Dict[str, Any] = {"status": "failed", "error": "任务未正常结束"}
        fail_reason: Optional[str] = None

        self._notify_start(task_config, username)

        try:
            if storage_manager.is_redis_available:
                if not storage_manager.acquire_lock(lock_name, timeout=3600):
                    fail_reason = "相同任务正在执行中，请稍后重试"
                    result = {"status": "failed", "error": fail_reason}
                    return result
                lock_acquired = True

            # cookie 账号使用锁：同一账号同时只允许一个任务使用
            if cookie_key:
                from sdk.cookie_manager import cookie_manager
                if not cookie_manager.acquire_use(cookie_key, cookie_use_owner):
                    fail_reason = f"Cookie账号 {cookie_key} 正被其他任务使用"
                    result = {"status": "failed", "error": fail_reason}
                    return result
                cookie_use_acquired = True

            for i, step in enumerate(steps):
                logger.info(f"--- 步骤 {i + 1}/{len(steps)}: {step.get('description', '')} ---")
                step_result = await self._execute_step(step, context)
                if step_result.get("status") == "failed":
                    step_result = await self._retry_with_recovery(
                        task_id, i + 1, step, context, step_result.get("error", "未知错误"))
                    if step_result.get("status") == "failed":
                        fail_reason = f"步骤{i + 1}失败: {step_result.get('error')}"
                        result = {
                            "status": "failed",
                            "error": fail_reason,
                            "failed_step": i + 1,
                            "recovery_attempted": step_result.get("recovery_attempted", False),
                            "recovery_diagnosis": step_result.get("recovery_diagnosis", ""),
                        }
                        self.task_manager.save_history(task_id, result)
                        return result
                context.update(step_result.get("context", {}))
                logger.info(f"步骤 {i + 1} 完成")

            self._close_desktop()
            elapsed = time.time() - start_time
            output_file = (context.get("processed_file") or context.get("downloaded_file")
                           or context.get("api_output_file") or "")
            result = {
                "status": "success",
                "task_id": task_id,
                "task_name": task_config.get("name"),
                "elapsed_time": round(elapsed, 2),
                "output_file": output_file,
                "context": {k: v for k, v in context.items() if not callable(v)},
            }
            self.task_manager.save_history(task_id, result)
            self._save_history(task_id, task_config, "success", elapsed, len(steps), len(steps), context)
            self._notify_success(task_config, username, elapsed, output_file)
            logger.info(f"✅ 任务执行成功，耗时 {elapsed:.1f}秒")
            return result

        except Exception as e:
            fail_reason = str(e)
            logger.error(f"任务执行异常: {fail_reason}")
            self._close_desktop()
            result = {"status": "failed", "error": fail_reason}
            self.task_manager.save_history(task_id, result)
            self._save_history(task_id, task_config, "failed", time.time() - start_time, error=fail_reason)

        finally:
            if cookie_use_acquired:
                try:
                    from sdk.cookie_manager import cookie_manager
                    cookie_manager.release_use(cookie_key, cookie_use_owner)
                except Exception as _ce:
                    logger.warning(f"释放Cookie使用锁失败(不影响业务): {cookie_key} err={_ce}")
            if storage_manager.is_redis_available and lock_acquired:
                try:
                    storage_manager.release_lock(lock_name)
                except Exception as _le:
                    logger.warning(f"释放任务锁失败(不影响业务): {lock_name} err={_le}")
            if result.get("status") != "success" and (fail_reason or result.get("error")):
                self._notify_failed(task_config, username, fail_reason or str(result.get("error", "")))

        return result

    # ==================== 执行上下文 ====================

    def _build_context(self, task_id: str, task_config: Dict, user_params: Dict, username: str, user_config: Dict) -> Dict:
        context: Dict[str, Any] = {}
        if user_params:
            context["user_params"] = user_params
        if self._current_user:
            context["username"] = username
            context["user_config"] = user_config
        context["_task_defaults"] = {
            "dingtalk_userid": task_config.get("dingtalk_userid") or task_config.get("x-default-userid") or ""
        }
        self._attach_cookie_domain(task_id, task_config, context)
        return context

    def _attach_cookie_domain(self, task_id: str, task_config: Dict, context: Dict) -> None:
        if not (storage_manager.is_redis_available
                and any(s.get("type") == "browser" for s in task_config.get("steps", []))):
            return
        config = get_config()
        cookie_domains = config.storage.get("browser_persistence", {}).get("cookie_domains", {})
        cookie_domain = cookie_domains.get(task_config.get("name", task_id))
        if cookie_domain:
            context["cookie_domain"] = cookie_domain

    # ==================== 通知 ====================

    def _notify_start(self, task_config: Dict, username: str) -> None:
        try:
            if self.notifier and self.notifier.enabled:
                self.notifier.notify_task_started(task_name=task_config.get("name", ""), username=username)
        except Exception as e:
            logger.warning(f"钉钉[开始]通知发送失败，不影响执行: {e}")

    def _notify_success(self, task_config: Dict, username: str, elapsed: float, output_file: str) -> None:
        try:
            if self.notifier and self.notifier.enabled:
                self.notifier.notify_task_success(
                    task_name=task_config.get("name", ""),
                    elapsed_sec=round(elapsed, 1),
                    username=username,
                    file_path=output_file,
                )
        except Exception as e:
            logger.warning(f"钉钉[成功]通知发送失败，不影响执行: {e}")

    def _notify_failed(self, task_config: Dict, username: str, error: str) -> None:
        try:
            if self.notifier and self.notifier.enabled:
                self.notifier.notify_task_failed(task_name=task_config.get("name", ""), error=error, username=username)
        except Exception as e:
            logger.warning(f"钉钉[失败]通知发送失败，不影响执行: {e}")

    # ==================== 历史落库 ====================

    def _save_history(self, task_id: str, task_config: Dict, status: str, elapsed: float,
                      steps_total: int = 0, steps_completed: int = 0,
                      context: Optional[Dict] = None, error: Optional[str] = None) -> None:
        storage_manager.save_task_history(
            task_id=task_id,
            task_name=task_config.get("name", ""),
            status=status,
            elapsed_time=f"{elapsed:.1f}秒",
            steps_total=steps_total,
            steps_completed=steps_completed,
            context={k: str(v) for k, v in (context or {}).items() if not callable(v)} if context else None,
            error_message=error,
        )

    def _close_desktop(self) -> None:
        if self.smart_desktop:
            try:
                self.smart_desktop.close()
            except Exception:
                pass
            self.smart_desktop = None

    # ==================== 步骤分发与自修复 ====================

    async def _execute_step(self, step: Dict, context: Dict) -> Dict[str, Any]:
        step_type = step.get("type")
        action = step.get("action")
        params = resolve_placeholders(step.get("params", {}), context)
        handler = STEP_HANDLERS.get(step_type)
        if not handler:
            return {"status": "failed", "error": f"未知步骤类型: {step_type}"}
        logger.info(f"  类型: {step_type}, 动作: {action}")
        return await handler(self, action, params, context)

    def _get_recovery(self):
        if not self.recovery:
            try:
                from src.agent.smart_recovery import SmartRecovery
                self.recovery = SmartRecovery()
            except Exception as e:
                logger.warning(f"异常自修复模块加载失败: {e}")
        return self.recovery

    async def _retry_with_recovery(self, task_id: str, step_index: int, step: Dict,
                                   context: Dict, error_msg: str) -> Dict[str, Any]:
        recovery = self._get_recovery()
        if not recovery:
            return {"status": "failed", "error": error_msg, "recovery_attempted": False}

        strategy = recovery.analyze_error(error_msg, step, context)
        logger.info(f"[Recovery] 诊断: {strategy.diagnosis} | 可重试: {strategy.should_retry}")

        if not strategy.should_retry:
            recovery.log_recovery(task_id, step_index, error_msg, strategy, 0, False)
            return {
                "status": "failed",
                "error": f"{error_msg}（诊断: {strategy.diagnosis}）",
                "recovery_attempted": True,
                "recovery_diagnosis": strategy.diagnosis,
                "need_human": strategy.need_human,
            }

        for attempt in range(1, strategy.max_retries + 1):
            wait_time = strategy.wait_seconds * (2 ** (attempt - 1))
            if wait_time > 0:
                logger.info(f"[Recovery] 等待 {wait_time:.1f}秒后重试")
                await asyncio.sleep(wait_time)

            await self._reset_session_if_needed(strategy.error_type, context)
            step_result = await self._execute_step(
                recovery.build_retry_context(step, strategy, attempt), context)

            if step_result.get("status") == "success":
                logger.info(f"[Recovery] ✅ 第{attempt}次重试成功")
                recovery.log_recovery(task_id, step_index, error_msg, strategy, attempt, True)
                return step_result

            logger.warning(f"[Recovery] 第{attempt}次重试仍失败: {step_result.get('error', '')}")
            if not recovery.should_continue_retry(attempt, strategy):
                break

        recovery.log_recovery(task_id, step_index, error_msg, strategy, strategy.max_retries, False)
        return {
            "status": "failed",
            "error": f"{error_msg}（已重试{strategy.max_retries}次仍失败）",
            "recovery_attempted": True,
            "recovery_diagnosis": strategy.diagnosis,
            "recovery_fix_action": strategy.fix_action,
            "need_human": strategy.need_human,
        }

    async def _reset_session_if_needed(self, error_type, context: Dict) -> None:
        from src.agent.smart_recovery import ErrorType
        if error_type == ErrorType.LOGIN_EXPIRED:
            logger.info("[Recovery] 登录过期，清除会话状态")
            context.pop("logged_in", None)
