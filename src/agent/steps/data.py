# -*- coding: utf-8 -*-
"""数据处理步骤"""
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


async def _process_data(executor, params: Dict, context: Dict) -> Dict[str, Any]:
    module_name = params.get("module", "")
    function_name = params.get("function", "process")
    if not module_name:
        return {"status": "failed", "error": "未指定清洗模块(module)"}

    _ensure_root_on_path()

    input_file = params.get("input_file") or context.get("downloaded_file") or context.get("api_output_file")
    if not input_file:
        return {"status": "failed", "error": "没有可清洗的输入文件"}

    logger.info(f"  数据清洗: {module_name}.{function_name}() 输入: {input_file}")

    try:
        func = getattr(importlib.import_module(module_name), function_name)
        kwargs = {"input_file": input_file, "context": context, "params": params}
        result = await func(**kwargs) if inspect.iscoroutinefunction(func) else func(**kwargs)

        output_file = result[1] if isinstance(result, tuple) and len(result) == 2 else (
            result if isinstance(result, str) else None)
        if output_file:
            return {"status": "success", "context": {"processed_file": output_file, "downloaded_file": output_file}}
        return {"status": "success", "context": {"data_result": str(result)}}
    except Exception as e:
        logger.error(f"  清洗失败: {e}")
        return {"status": "failed", "error": f"数据清洗失败: {e}"}


async def _process_excel(executor, params: Dict, context: Dict) -> Dict[str, Any]:
    file_path = params.get("file_path") or context.get("downloaded_file")
    if not file_path:
        return {"status": "failed", "error": "未找到要处理的文件"}

    result = executor.data_processor.process_excel(
        file_path=file_path,
        task_description=params.get("task_description", ""),
        output_path=params.get("output_path"),
    )
    if result.get("status") == "success":
        return {"status": "success", "context": {
            "data_result": {k: v for k, v in result.items() if k != "data"}}}
    return {"status": "failed", "error": result.get("error")}


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    if action == "process_data":
        return await _process_data(executor, params, context)
    if action == "process_excel":
        return await _process_excel(executor, params, context)
    return {"status": "failed", "error": f"未知数据动作: {action}"}
