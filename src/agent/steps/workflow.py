# -*- coding: utf-8 -*-
"""自定义 workflow 脚本执行（browser/api/desktop 的 run_workflow 共用）"""
import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Dict

from loguru import logger


def _ensure_root_on_path() -> None:
    root = Path(__file__).resolve().parent.parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    _ensure_root_on_path()

    workflow_module = params.get("module", "")
    workflow_func = params.get("function", "run")
    if not workflow_module:
        return {"status": "failed", "error": "未指定workflow模块(module)"}

    # 参数合并优先级（由低到高）：yaml step.params 写死的值 < 用户每次填的 user_params
    step_params = {k: v for k, v in params.items() if k not in ("module", "function")}
    user_params = dict(step_params)
    user_params.update(context.get("user_params", {}) or {})

    logger.info(f"  Workflow: 调用 {workflow_module}.{workflow_func}()")

    try:
        mod = importlib.import_module(workflow_module)
        func = getattr(mod, workflow_func)
        result = await func(**user_params) if inspect.iscoroutinefunction(func) else func(**user_params)

        if isinstance(result, tuple) and len(result) == 2:
            data_list, file_path = result
            return {"status": "success", "context": {
                "workflow_data_count": len(data_list) if hasattr(data_list, "__len__") else 0,
                "downloaded_file": file_path,
                "api_output_file": file_path,
            }}
        if isinstance(result, str):
            return {"status": "success", "context": {
                "downloaded_file": result,
                "api_output_file": result,
            }}
        return {"status": "success", "context": {"workflow_result": str(result)}}
    except Exception as e:
        logger.error(f"  Workflow失败: {e}")
        return {"status": "failed", "error": f"Workflow调用失败: {e}"}
