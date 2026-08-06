# -*- coding: utf-8 -*-
"""
任务执行器 - 读取任务配置，按步骤执行

这是连接"任务配置"和"智能执行"的桥梁：
  配置: 步骤1 打开URL → 步骤2 扫码登录 → 步骤3 点击下载 → 步骤4 处理数据
  执行: SmartBrowser.navigate → SmartBrowser.smart_login → SmartBrowser.smart_download → SmartDataProcessor.process_excel
"""
import asyncio
import time
from typing import Dict, Any, Optional
from loguru import logger

from src.agent.smart_browser import SmartBrowser
from src.agent.smart_data_processor import SmartDataProcessor
from src.agent.task_manager import TaskManager
from src.storage import storage_manager
from src.core.config import get_config
from src.agent.delivery_service import DeliveryService
from src.agent.template_manager import TemplateManager


class TaskExecutor:
    """
    任务执行器

    根据任务配置中的步骤，调用对应的智能模块执行
    """

    def __init__(self):
        self.smart_browser: Optional[SmartBrowser] = None
        self.smart_desktop = None  # 智能桌面自动化（按需初始化）
        self.data_processor = SmartDataProcessor()
        self.task_manager = TaskManager()
        self.delivery_service = DeliveryService()
        self.template_manager = TemplateManager()
        self.recovery = None  # 智能异常自修复（按需初始化）
        self._current_user = None

    async def execute_task(self, task_id: str, user_params: Dict = None) -> Dict[str, Any]:
        """
        执行指定任务

        Args:
            task_id: 任务ID

        Returns:
            执行结果
        """
        # 获取任务配置
        task_config = self.task_manager.get_task(task_id)
        if not task_config:
            return {"status": "failed", "error": f"任务不存在: {task_id}"}

        if not task_config.get("enabled", True):
            return {"status": "failed", "error": "任务已禁用"}

        logger.info(f"{'='*60}")
        logger.info(f"开始执行任务: {task_config.get('name', task_id)}")
        logger.info(f"{'='*60}")

        start_time = time.time()
        context = {}  # 步骤间共享数据
        if user_params:
            context["user_params"] = user_params
        # 设置用户信息用于交付步骤
        if self._current_user:
            context["username"] = self._current_user.get("username", "")
            context["user_config"] = self._current_user.get("config", {})

        try:
            steps = task_config.get("steps", [])

            # 设置cookie持久化（仅当任务包含浏览器步骤时）
            has_browser_step = any(s.get('type') == 'browser' for s in steps)
            if has_browser_step and storage_manager.is_redis_available:
                config = get_config()
                cookie_domains = config.storage.get('browser_persistence', {}).get('cookie_domains', {})
                task_name = task_config.get('name', task_id)
                cookie_domain = cookie_domains.get(task_name)
                if cookie_domain and self.smart_browser:
                    self.smart_browser.browser.set_cookie_domain(cookie_domain)

            # 获取分布式锁，防止重复执行
            if storage_manager.is_redis_available:
                if storage_manager.acquire_lock(f"task:{task_id}", timeout=3600):
                    logger.info(f"已获取任务锁: {task_id}")
                else:
                    # 锁被占用，可能是上次任务异常退出未释放。强制清理后重试一次
                    logger.warning(f"任务锁被占用，尝试强制清理: {task_id}")
                    storage_manager.release_lock(f"task:{task_id}")
                    if storage_manager.acquire_lock(f"task:{task_id}", timeout=3600):
                        logger.info(f"已获取任务锁（强制清理后）: {task_id}")
                    else:
                        return {"status": "failed", "error": "任务正在执行中（锁被占用且无法清理）"}

            for i, step in enumerate(steps):
                logger.info(f"--- 步骤 {i+1}/{len(steps)}: {step.get('description', '')} ---")

                step_result = await self._execute_step(step, context)

                # 步骤失败时尝试智能自修复
                if step_result.get("status") == "failed":
                    error_msg = step_result.get("error", "未知错误")
                    logger.warning(f"步骤 {i+1} 失败: {error_msg}")

                    # 尝试自动修复并重试
                    step_result = await self._retry_with_recovery(
                        task_id, i + 1, step, context, error_msg
                    )

                    if step_result.get("status") == "failed":
                        result = {
                            "status": "failed",
                            "error": f"步骤{i+1}失败: {step_result.get('error')}",
                            "failed_step": i + 1,
                            "recovery_attempted": step_result.get("recovery_attempted", False),
                            "recovery_diagnosis": step_result.get("recovery_diagnosis", ""),
                        }
                        self.task_manager.save_history(task_id, result)
                        return result

                # 保存步骤结果到上下文
                context.update(step_result.get("context", {}))

                logger.info(f"步骤 {i+1} 完成")

            # 关闭浏览器
            if self.smart_browser:
                await self.smart_browser.close()
            # 关闭桌面自动化
            if self.smart_desktop:
                self.smart_desktop.close()
                self.smart_desktop = None

            elapsed = time.time() - start_time
            result = {
                "status": "success",
                "task_id": task_id,
                "task_name": task_config.get("name"),
                "elapsed_time": round(elapsed, 2),
                "context": {k: v for k, v in context.items() if not callable(v)}
            }

            self.task_manager.save_history(task_id, result)

            # 保存到MySQL
            if storage_manager.is_redis_available:
                storage_manager.save_task_history(
                    task_id=task_id,
                    task_name=task_config.get('name', ''),
                    status='success',
                    elapsed_time=f"{elapsed:.1f}秒",
                    steps_total=len(steps),
                    steps_completed=len(steps),
                    context={k: str(v) for k, v in context.items() if not callable(v)}
                )
                # 释放锁
                storage_manager.release_lock(f"task:{task_id}")

            logger.info(f"✅ 任务执行成功，耗时 {elapsed:.1f}秒")
            return result

        except Exception as e:
            logger.error(f"任务执行异常: {e}")
            if self.smart_browser:
                await self.smart_browser.close()
            if self.smart_desktop:
                try:
                    self.smart_desktop.close()
                except Exception:
                    pass
                self.smart_desktop = None

            result = {"status": "failed", "error": str(e)}
            self.task_manager.save_history(task_id, result)

            # 保存失败记录到MySQL
            if storage_manager.is_redis_available:
                storage_manager.save_task_history(
                    task_id=task_id,
                    task_name=task_config.get('name', ''),
                    status='failed',
                    elapsed_time=f"{time.time() - start_time:.1f}秒",
                    error_message=str(e)
                )
                storage_manager.release_lock(f"task:{task_id}")

            return result

    def _resolve_params_placeholders(self, params: Any, context: Dict) -> Any:
        """
        递归替换参数中的 ${param} 占位符为用户输入的值
        支持 dict、list、str 嵌套结构
        """
        import re
        if not params:
            return params
        user_params = context.get('user_params', {}) if context else {}

        def _sub(s: str) -> str:
            if not isinstance(s, str):
                return s
            def _m(mo):
                k = mo.group(1)
                return str(user_params[k]) if k in user_params else mo.group(0)
            return re.sub(r'\$\{(\w+)\}', _m, s)

        if isinstance(params, dict):
            return {k: self._resolve_params_placeholders(v, context) for k, v in params.items()}
        elif isinstance(params, list):
            return [self._resolve_params_placeholders(v, context) for v in params]
        elif isinstance(params, str):
            return _sub(params)
        else:
            return params

    def _get_recovery(self):
        """懒加载智能异常自修复模块"""
        if not self.recovery:
            try:
                from src.agent.smart_recovery import SmartRecovery
                self.recovery = SmartRecovery()
            except Exception as e:
                logger.warning(f"异常自修复模块加载失败: {e}")
        return self.recovery

    async def _retry_with_recovery(
        self,
        task_id: str,
        step_index: int,
        step: Dict,
        context: Dict,
        error_msg: str,
    ) -> Dict[str, Any]:
        """
        智能自修复重试

        流程：
        1. 调用 SmartRecovery 分析错误
        2. 如果可重试，按策略修正后重试
        3. 记录修复日志
        """
        recovery = self._get_recovery()
        if not recovery:
            return {
                "status": "failed",
                "error": error_msg,
                "recovery_attempted": False,
            }

        # 分析错误
        strategy = recovery.analyze_error(error_msg, step, context)

        logger.info(
            f"[Recovery] 诊断结果: {strategy.diagnosis} | "
            f"可重试: {strategy.should_retry} | 需人工: {strategy.need_human}"
        )

        if not strategy.should_retry:
            # 不可自动修复
            recovery.log_recovery(task_id, step_index, error_msg, strategy, 0, False)
            return {
                "status": "failed",
                "error": f"{error_msg}（诊断: {strategy.diagnosis}）",
                "recovery_attempted": True,
                "recovery_diagnosis": strategy.diagnosis,
                "need_human": strategy.need_human,
            }

        # 按策略重试
        max_attempts = strategy.max_retries
        for attempt in range(1, max_attempts + 1):
            logger.info(f"[Recovery] 第{attempt}/{max_attempts}次重试...")

            # 指数退避等待
            wait_time = strategy.wait_seconds * (2 ** (attempt - 1))
            if wait_time > 0:
                logger.info(f"[Recovery] 等待 {wait_time:.1f}秒后重试")
                await asyncio.sleep(wait_time)

            # 构建修正后的步骤
            retry_step = recovery.build_retry_context(step, strategy, attempt)

            # 重置可能的错误状态（如浏览器/桌面会话）
            await self._reset_session_if_needed(strategy.error_type, context)

            # 重新执行
            step_result = await self._execute_step(retry_step, context)

            if step_result.get("status") == "success":
                logger.info(f"[Recovery] ✅ 第{attempt}次重试成功")
                recovery.log_recovery(task_id, step_index, error_msg, strategy, attempt, True)
                return step_result

            logger.warning(f"[Recovery] 第{attempt}次重试仍失败: {step_result.get('error', '')}")

            if not recovery.should_continue_retry(attempt, strategy):
                break

        # 所有重试都失败
        recovery.log_recovery(task_id, step_index, error_msg, strategy, max_attempts, False)
        return {
            "status": "failed",
            "error": f"{error_msg}（已重试{max_attempts}次仍失败）",
            "recovery_attempted": True,
            "recovery_diagnosis": strategy.diagnosis,
            "recovery_fix_action": strategy.fix_action,
            "need_human": strategy.need_human,
        }

    async def _reset_session_if_needed(self, error_type, context: Dict):
        """根据错误类型重置会话状态"""
        from src.agent.smart_recovery import ErrorType
        if error_type == ErrorType.LOGIN_EXPIRED:
            # 登录过期：清除cookie标记，下次会重新登录
            logger.info("[Recovery] 登录过期，清除会话状态")
            context.pop("logged_in", None)
            # 关闭浏览器让下次重新打开
            if self.smart_browser:
                try:
                    await self.smart_browser.close()
                    self.smart_browser = None
                except Exception:
                    pass

    async def _execute_step(self, step: Dict, context: Dict) -> Dict[str, Any]:
        """执行单个步骤"""
        step_type = step.get("type")
        action = step.get("action")
        params = step.get("params", {})
        description = step.get("description", "")

        # 替换参数中的 ${param} 占位符
        params = self._resolve_params_placeholders(params, context)

        logger.info(f"  类型: {step_type}, 动作: {action}")

        if step_type == "browser":
            return await self._execute_browser_step(action, params, context)
        elif step_type == "desktop":
            return await self._execute_desktop_step(action, params, context)
        elif step_type == "data":
            return await self._execute_data_step(action, params, context)
        elif step_type == "api":
            return await self._execute_api_step(action, params, context)
        elif step_type == "deliver":
            return await self._execute_deliver_step(action, params, context)
        elif step_type == "notify":
            return await self._execute_notify_step(action, params, context)
        else:
            return {"status": "failed", "error": f"未知步骤类型: {step_type}"}

    async def _execute_desktop_step(
        self,
        action: str,
        params: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        """
        执行桌面应用自动化步骤

        支持的action：
          - start_app:      启动应用并绑定窗口
          - smart_click:    LLM智能点击（用自然语言描述点哪里）
          - smart_fill:     LLM智能填写输入框
          - smart_select:   LLM智能选择下拉框
          - smart_wait:     LLM智能等待条件满足
          - smart_export:   LLM智能导出文件
          - click_button:   按文本点击按钮（原生）
          - fill_input:     按标签填写输入框（原生）
          - select_menu:    多级菜单选择（原生）
          - export_file:    通用导出（原生）
          - press_key:      按键
          - wait_window:    等待窗口出现
          - run_workflow:   调用自定义workflow脚本
        """
        # 按需初始化智能桌面（延迟导入，避免未装uiautomation时影响其他任务）
        if not self.smart_desktop:
            try:
                from src.agent.smart_desktop import SmartDesktop
                self.smart_desktop = SmartDesktop()
            except ImportError as e:
                return {"status": "failed", "error": f"桌面自动化模块未安装: {e}"}

        # action=start_app：启动应用
        if action == "start_app":
            app_path = params.get("app_path", "")
            app_name = params.get("app_name", "")
            wait = params.get("wait_seconds", 5)
            try:
                self.smart_desktop.start(app_name=app_name or None)
                if app_path:
                    await asyncio.to_thread(self.smart_desktop.desktop.start_app, app_path, "", wait)
                return {"status": "success", "context": {"desktop_app": app_name or app_path}}
            except Exception as e:
                return {"status": "failed", "error": f"启动应用失败: {e}"}

        # action=smart_*：LLM驱动的智能方法
        elif action == "smart_click":
            intent = params.get("intent", "")
            timeout = params.get("timeout", 10)
            ok = await asyncio.to_thread(self.smart_desktop.smart_click, intent, timeout)
            return {"status": "success" if ok else "failed", "error": "" if ok else f"智能点击失败: {intent}"}

        elif action == "smart_fill":
            intent = params.get("intent", "")
            value = params.get("value", "")
            timeout = params.get("timeout", 10)
            ok = await asyncio.to_thread(self.smart_desktop.smart_fill, intent, value, timeout)
            return {"status": "success" if ok else "failed", "error": "" if ok else f"智能填充失败: {intent}"}

        elif action == "smart_select":
            intent = params.get("intent", "")
            value = params.get("value", "")
            timeout = params.get("timeout", 10)
            ok = await asyncio.to_thread(self.smart_desktop.smart_select, intent, value, timeout)
            return {"status": "success" if ok else "failed", "error": "" if ok else f"智能选择失败: {intent}"}

        elif action == "smart_wait":
            condition = params.get("condition", "")
            timeout = params.get("timeout", 30)
            ok = await asyncio.to_thread(self.smart_desktop.smart_wait, condition, timeout)
            return {"status": "success" if ok else "failed", "error": "" if ok else f"等待超时: {condition}"}

        elif action == "smart_export":
            intent = params.get("intent", "")
            save_path = params.get("save_path", "")
            timeout = params.get("timeout", 60)
            path = await asyncio.to_thread(self.smart_desktop.smart_export, intent, save_path, timeout)
            if path:
                return {"status": "success", "context": {"downloaded_file": path}}
            return {"status": "failed", "error": f"导出失败: {intent}"}

        # action=原生方法
        elif action == "click_button":
            text = params.get("text", "")
            timeout = params.get("timeout", 5)
            ok = await asyncio.to_thread(self.smart_desktop.desktop.click_button, text, False, timeout)
            return {"status": "success" if ok else "failed"}

        elif action == "fill_input":
            label = params.get("label", "")
            value = params.get("value", "")
            ok = await asyncio.to_thread(self.smart_desktop.desktop.fill_input, label, value)
            return {"status": "success" if ok else "failed"}

        elif action == "select_menu":
            menu_path = params.get("menu_path", [])
            if isinstance(menu_path, str):
                menu_path = [menu_path]
            ok = await asyncio.to_thread(self.smart_desktop.desktop.select_menu, menu_path)
            return {"status": "success" if ok else "failed"}

        elif action == "export_file":
            save_path = params.get("save_path", "")
            trigger = params.get("trigger_button", "导出")
            timeout = params.get("timeout", 30)
            path = await asyncio.to_thread(
                self.smart_desktop.desktop.export_file, save_path, trigger, True, "保存", timeout
            )
            if path:
                return {"status": "success", "context": {"downloaded_file": path}}
            return {"status": "failed", "error": "导出失败"}

        elif action == "press_key":
            key = params.get("key", "Enter")
            ok = await asyncio.to_thread(self.smart_desktop.desktop.press_key, key)
            return {"status": "success" if ok else "failed"}

        elif action == "wait_window":
            title = params.get("title", "")
            timeout = params.get("timeout", 30)
            ok = await asyncio.to_thread(self.smart_desktop.desktop.wait_window, title, timeout)
            return {"status": "success" if ok else "failed", "error": "" if ok else f"窗口未出现: {title}"}

        elif action == "run_workflow":
            # 桌面任务调用自定义workflow脚本（同browser/api共用此方法）
            return await self._execute_workflow_step(params, context)

        return {"status": "failed", "error": f"未知桌面动作: {action}"}

    async def _execute_browser_step(
        self,
        action: str,
        params: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        """执行浏览器步骤"""

        # 按需初始化浏览器
        if not self.smart_browser:
            self.smart_browser = SmartBrowser()
            await self.smart_browser.start(headless=False)

        if action == "navigate":
            url = params.get("url", "")
            await self.smart_browser.navigate(url)
            return {"status": "success", "context": {"current_url": url}}

        elif action == "login":
            login_url = params.get("url", "")
            success_hint = params.get("success_hint", "页面显示用户信息")
            timeout = params.get("timeout", 300)

            if login_url:
                await self.smart_browser.navigate(login_url)

            success = await self.smart_browser.smart_login(
                login_url=params.get("url", self.smart_browser.browser.page.url if self.smart_browser.browser.page else ""),
                success_hint=success_hint,
                timeout=timeout
            )

            if success:
                return {"status": "success"}
            return {"status": "failed", "error": "登录超时"}

        elif action == "click":
            intent = params.get("intent", "")
            timeout = params.get("timeout", 10000)
            success = await self.smart_browser.smart_click(intent, timeout=timeout)
            if success:
                return {"status": "success"}
            return {"status": "failed", "error": f"点击失败: {intent}"}

        elif action == "download":
            intent = params.get("intent", "")
            timeout = params.get("timeout", 60000)
            file_path = await self.smart_browser.smart_download(intent, timeout=timeout)

            if file_path:
                return {"status": "success", "context": {"downloaded_file": file_path}}
            return {"status": "failed", "error": f"下载失败: {intent}"}

        elif action == "wait":
            condition = params.get("condition", "")
            timeout = params.get("timeout", 30)
            success = await self.smart_browser.smart_wait(condition, timeout=timeout)
            if success:
                return {"status": "success"}
            return {"status": "failed", "error": f"等待超时: {condition}"}

        elif action == "fill":
            intent = params.get("intent", "")
            value = params.get("value", "")
            success = await self.smart_browser.smart_fill(intent, value)
            if success:
                return {"status": "success"}
            return {"status": "failed", "error": f"填充失败: {intent}"}

        elif action == "run_workflow":
            # 浏览器任务调用自定义workflow脚本（如 jd_ibay_self.py）
            # workflow脚本内部自己管理浏览器操作，不用反复改task_executor
            return await self._execute_workflow_step(params, context)

        return {"status": "failed", "error": f"未知浏览器动作: {action}"}

    async def _execute_workflow_step(
        self,
        params: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        """
        执行自定义workflow脚本（browser和api类型共用）

        workflow脚本是一个Python模块，提供async def run(...)或async def run_api(...)函数。
        用户在Web界面填的参数会通过 **user_params 传给该函数。
        """
        import sys
        from pathlib import Path
        import importlib
        import inspect

        # 确保项目根目录在path中
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        workflow_module = params.get("module", "")
        workflow_func = params.get("function", "run")
        user_params = context.get("user_params", {})

        if not workflow_module:
            return {"status": "failed", "error": "未指定workflow模块(module)"}

        logger.info(f"  Workflow: 调用 {workflow_module}.{workflow_func}()")
        logger.info(f"  用户参数: {user_params}")

        try:
            mod = importlib.import_module(workflow_module)
            func = getattr(mod, workflow_func)

            # 调用异步函数，传入用户参数
            if inspect.iscoroutinefunction(func):
                result = await func(**user_params)
            else:
                result = func(**user_params)

            # result 可能是 (data_list, file_path) 元组，或单个文件路径字符串
            if isinstance(result, tuple) and len(result) == 2:
                data_list, file_path = result
                logger.info(f"  Workflow完成: 获取 {len(data_list) if hasattr(data_list, '__len__') else '?'} 条数据，保存到 {file_path}")
                return {
                    "status": "success",
                    "context": {
                        "workflow_data_count": len(data_list) if hasattr(data_list, '__len__') else 0,
                        "downloaded_file": file_path,
                        "api_output_file": file_path
                    }
                }
            elif isinstance(result, str):
                logger.info(f"  Workflow完成: 输出文件 {result}")
                return {
                    "status": "success",
                    "context": {
                        "downloaded_file": result,
                        "api_output_file": result
                    }
                }
            else:
                logger.info(f"  Workflow完成: {result}")
                return {"status": "success", "context": {"workflow_result": str(result)}}

        except Exception as e:
            logger.error(f"  Workflow失败: {e}")
            return {"status": "failed", "error": f"Workflow调用失败: {e}"}

    async def _execute_data_step(
        self,
        action: str,
        params: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        """执行数据处理步骤"""

        if action == "process_data":
            # 调用 data_processors 模块中的清洗函数
            import importlib
            import sys
            from pathlib import Path
            
            module_name = params.get("module", "")
            function_name = params.get("function", "process")
            
            if not module_name:
                return {"status": "failed", "error": "未指定清洗模块(module)"}
            
            # 确保项目根目录在path中
            root = str(Path(__file__).resolve().parent.parent.parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            
            # 获取输入文件：优先params指定的，其次context中的
            input_file = params.get("input_file") or context.get("downloaded_file") or context.get("api_output_file")
            if not input_file:
                return {"status": "failed", "error": "没有可清洗的输入文件"}
            
            logger.info(f"  数据清洗: {module_name}.{function_name}()")
            logger.info(f"  输入文件: {input_file}")
            
            try:
                mod = importlib.import_module(module_name)
                func = getattr(mod, function_name)
                
                import inspect
                kwargs = {
                    "input_file": input_file,
                    "context": context,
                    "params": params,
                }
                if inspect.iscoroutinefunction(func):
                    result = await func(**kwargs)
                else:
                    result = func(**kwargs)
                
                # result 可以是文件路径字符串，或 (data, file_path) 元组
                output_file = None
                if isinstance(result, str):
                    output_file = result
                elif isinstance(result, tuple) and len(result) == 2:
                    output_file = result[1]
                
                if output_file:
                    logger.info(f"  清洗完成，输出: {output_file}")
                    return {
                        "status": "success",
                        "context": {
                            "processed_file": output_file,
                            "downloaded_file": output_file  # 更新供交付步骤使用
                        }
                    }
                else:
                    logger.info(f"  清洗完成")
                    return {"status": "success", "context": {"data_result": str(result)}}
                    
            except Exception as e:
                logger.error(f"  清洗失败: {e}")
                return {"status": "failed", "error": f"数据清洗失败: {e}"}

        if action == "process_excel":
            # 文件路径：优先用参数指定的，其次用上一步下载的
            file_path = params.get("file_path") or context.get("downloaded_file")
            if not file_path:
                return {"status": "failed", "error": "未找到要处理的文件"}

            task_desc = params.get("task_description", "")
            output_path = params.get("output_path")

            result = self.data_processor.process_excel(
                file_path=file_path,
                task_description=task_desc,
                output_path=output_path
            )

            if result.get("status") == "success":
                return {
                    "status": "success",
                    "context": {
                        "data_result": {k: v for k, v in result.items() if k != "data"}
                    }
                }
            return {"status": "failed", "error": result.get("error")}

        return {"status": "failed", "error": f"未知数据动作: {action}"}

    async def _execute_api_step(
        self,
        action: str,
        params: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        """执行API调用步骤"""
        if action == "run_workflow":
            # API任务调用自定义workflow脚本，复用browser的通用workflow执行逻辑
            return await self._execute_workflow_step(params, context)

        return {"status": "failed", "error": f"未知API动作: {action}"}

    def set_user(self, user_info: Dict):
        self._current_user = user_info

    async def _execute_deliver_step(
        self,
        action: str,
        params: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        if action == "deliver_file":
            file_path = params.get("file_path") or context.get("downloaded_file") or context.get("api_output_file")
            if not file_path:
                return {"status": "failed", "error": "没有可交付的文件"}
            
            username = context.get("username", "")
            user_config = context.get("user_config", {})
            template_name = params.get("template_name")
            if template_name and username:
                template_path = self.template_manager.get_template_by_name(username, template_name)
                if template_path:
                    logger.info(f"  使用模板: {template_name}")
                    context["template_path"] = str(template_path)
            
            channels = params.get("channels")
            task_name = params.get("task_name", "")
            result = await self.delivery_service.deliver(
                file_path=file_path,
                user_config=user_config,
                task_name=task_name,
                channels=channels
            )
            success_ch = [k for k, v in result.items() if isinstance(v, dict) and v.get("success")]
            failed_ch = [k for k, v in result.items() if isinstance(v, dict) and not v.get("success")]
            if success_ch:
                logger.info(f"  交付成功: {', '.join(success_ch)}")
            if failed_ch:
                logger.warning(f"  交付失败: {', '.join(failed_ch)}")
            return {"status": "success", "context": {"deliver_result": result, "delivered_channels": success_ch}}
        return {"status": "failed", "error": f"未知交付动作: {action}"}

    async def _execute_notify_step(
        self,
        action: str,
        params: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        """执行通知步骤"""
        # TODO: 接入Web推送/企业微信/钉钉
        message = params.get("message", "任务完成")
        logger.info(f"📢 通知: {message}")
        return {"status": "success"}
