# -*- coding: utf-8 -*-
"""
任务执行器（编排层）

只负责「加载任务 → 加锁 → 调 workflow 函数 → 交付 → 通知」。
直接 import workflow 模块 + 调函数，无注册表分发。
"""
import asyncio
import importlib
import inspect
import sys
import time
from typing import Any, Dict, Optional

from loguru import logger

from sdk.delivery import DeliveryService
from src.agent.notifier import Notifier, build_notifier
from src.agent.task_manager import task_manager
from src.storage import storage_manager


_PROJECT_PREFIXES = ("workflows.", "data_clean.")
# 说明：热更新只针对业务代码（workflows/data_clean）。
# 不重载 sdk./src. 基础设施模块——它们持有全局单例和活动连接
# （如 src.web.api 的 manager 存着所有 WebSocket 连接，reload 会悄悄
# 替换成空实例，导致前端实时日志在任务执行后收不到任何消息）。
# 改了 sdk/src 后请重启服务。
_RELOAD_EXCLUDE = set()


def reload_project_modules() -> dict:
    """重新加载所有项目模块（workflows/data_clean/sdk/src），让改完代码重跑任务即时生效。

    按模块名长度排序重载：浅层包先重载，深层模块后重载，保证依赖顺序正确。
    例：sdk → sdk.entities → sdk.entities.jd_ibay_sales

    排除项：持有 Redis/MySQL 连接或全局单例的模块（reload 会丢状态）。
    """
    importlib.invalidate_caches()

    # 收集所有项目模块，排除连接类模块，按名称长度排序（浅→深）
    to_reload = sorted(
        [n for n in sys.modules
         if n.startswith(_PROJECT_PREFIXES) and n not in _RELOAD_EXCLUDE],
        key=len
    )

    ok, fail = 0, 0
    for name in to_reload:
        mod = sys.modules.get(name)
        if mod is None:
            continue
        try:
            importlib.reload(mod)
            ok += 1
        except Exception as e:
            fail += 1
            logger.warning(f"[HotReload] {name} 重载失败: {e}")

    logger.info(f"[HotReload] 项目模块重载完成: {ok} 成功, {fail} 失败")
    return {"reloaded": ok, "failed": fail}


def reload_workflow(module_name: str) -> dict:
    """手动热更新指定 workflow 模块，供 API 端点调用。

    Returns: {"status": "success"|"failed", "module": module_name, ...}
    """
    importlib.invalidate_caches()
    cached = sys.modules.get(module_name)
    if cached is None:
        # 没加载过，直接 import 即可
        try:
            importlib.import_module(module_name)
            return {"status": "success", "module": module_name, "action": "imported"}
        except Exception as e:
            return {"status": "failed", "module": module_name, "error": str(e)}
    try:
        importlib.reload(cached)
        logger.info(f"[HotReload] 手动重载成功: {module_name}")
        return {"status": "success", "module": module_name, "action": "reloaded"}
    except Exception as e:
        logger.error(f"[HotReload] 重载失败: {module_name} — {e}")
        return {"status": "failed", "module": module_name, "error": str(e)}


def _load_workflow_module(module_name: str):
    """加载 workflow 模块。已缓存则 reload，首次则 import。"""
    importlib.invalidate_caches()
    cached = sys.modules.get(module_name)
    if cached is not None:
        importlib.reload(cached)
        logger.info(f"[HotReload] 重新加载模块: {module_name}")
        return cached
    mod = importlib.import_module(module_name)
    logger.info(f"[HotReload] 首次加载模块: {module_name}")
    return mod


class TaskExecutor:
    """任务执行器（编排层）"""

    def __init__(self):
        self.task_manager = task_manager
        self.delivery_service = DeliveryService()
        self._current_user = None
        self.notifier: Optional[Notifier] = None

    def set_user(self, user_info: Dict):
        self._current_user = user_info

    async def execute_task(self, task_id: str, user_params: Dict = None,
                           job_id: Optional[str] = None) -> Dict[str, Any]:
        # 热更新：每次跑任务前重载所有项目模块，改完代码不重启即生效
        reload_project_modules()

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
        lock_name = f"task:{task_id}:{job_id}" if job_id else f"task:{task_id}"
        lock_acquired = False
        cookie_key = task_config.get("cookie_key", "")
        cookie_use_owner = job_id or task_id
        cookie_use_acquired = False
        result: Dict[str, Any] = {"status": "failed", "error": "任务未正常结束"}
        fail_reason = ""

        self._notify_start(task_config, username)

        try:
            if storage_manager.is_redis_available:
                if not storage_manager.acquire_lock(lock_name, timeout=3600):
                    fail_reason = "相同任务正在执行中，请稍后重试"
                    result = {"status": "failed", "error": fail_reason}
                    return result
                lock_acquired = True

            if cookie_key:
                from sdk.cookie_manager import cookie_manager
                if not cookie_manager.acquire_use(cookie_key, cookie_use_owner):
                    fail_reason = f"Cookie账号 {cookie_key} 正被其他任务使用"
                    result = {"status": "failed", "error": fail_reason}
                    return result
                cookie_use_acquired = True

            # 合并参数
            merged_params = dict(user_params or {})
            merged_params.setdefault("output_dir",
                                     str(task_config.get("output_dir", "")) or None)
            # 工作流靠这个取「当前用户」的配置和上传文件
            # （LocalConfig.get_for_user / TemplateManager.get_template_by_name 都要它）
            merged_params.setdefault("username", username)

            # 调用 workflow 函数
            workflow_module = task_config.get("workflow_module", "")
            workflow_func = task_config.get("workflow_func", "run")
            if not workflow_module:
                return {"status": "failed", "error": "任务配置缺少 workflow_module"}
            logger.info(f"调用 workflow: {workflow_module}.{workflow_func}()")
            mod = _load_workflow_module(workflow_module)
            func = getattr(mod, workflow_func)
            wf_result = await func(merged_params) if inspect.iscoroutinefunction(func) \
                else func(merged_params)

            if isinstance(wf_result, dict) and wf_result.get("status") == "failed":
                result = wf_result
                return result

            # 交付文件
            output_file = wf_result.get("output_file") or ""
            if output_file:
                await self._deliver(task_config, output_file, username)

            elapsed = time.time() - start_time
            result = {
                "status": "success",
                "task_id": task_id,
                "task_name": task_config.get("name"),
                "elapsed_time": round(elapsed, 2),
                "output_file": output_file,
                "workflow_result": wf_result,
            }
            self._notify_success(task_config, username, elapsed, output_file)
            logger.info(f"✅ 任务执行成功，耗时 {elapsed:.1f}秒")
            return result

        except Exception as e:
            fail_reason = str(e)
            logger.error(f"任务执行异常: {fail_reason}")
            result = {"status": "failed", "error": fail_reason}

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
            # 任务进度落库（前端历史页/SQL都可见）
            self._save_history_sql(task_id, task_config, result, username, start_time)

        return result

    def _save_history_sql(self, task_id: str, task_config: dict, result: dict,
                          username: str, start_time: float):
        """把本次执行结果写入 task_history 表（失败不影响主流程）"""
        try:
            from sdk.entities import get_entity
            from sdk.mysql_sdk import MySQL
            from datetime import datetime
            entity = get_entity("task_history")
            MySQL.insert(entity, {
                "task_id": task_id,
                "task_name": task_config.get("name", ""),
                "department": task_config.get("department", ""),
                "status": result.get("status", ""),
                "start_time": datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_time": result.get("elapsed_time") or 0,
                "error_msg": (result.get("error") or "")[:2000],
                "output_files": result.get("output_file") or "",
                "created_by": username,
            })
        except Exception as e:
            logger.warning(f"任务历史写入SQL失败(不影响业务): {e}")

    # ==================== 交付 ====================

    async def _deliver(self, task_config: dict, file_path: str, username: str):
        """交付文件到钉钉 + 本地"""
        try:
            channels = task_config.get("deliver_channels") or ["dingtalk", "local"]
            defaults = task_config.get("_task_defaults", {}) or {}
            dingtalk_userid = task_config.get("dingtalk_userid") or defaults.get("dingtalk_userid", "")
            await self.delivery_service.deliver(
                file_path=file_path,
                user_config=self._current_user.get("config", {}) if self._current_user else {},
                task_name=task_config.get("name", ""),
                channels=channels,
                dingtalk_userid=dingtalk_userid,
            )
        except Exception as e:
            logger.warning(f"文件交付失败（不影响主流程）: {e}")

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
