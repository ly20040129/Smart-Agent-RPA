# -*- coding: utf-8 -*-
"""loop 步骤 —— 借鉴旧项目 baseTask 的批量循环：对列表逐条执行子步骤，错误隔离"""
import ast
import re
from typing import Any, Dict, List

from loguru import logger


def _resolve_items(params: Dict, context: Dict) -> List:
    items = params.get("items")
    if isinstance(items, (list, tuple)):
        return list(items)
    if not isinstance(items, str):
        return []
    s = items.strip()
    m = re.fullmatch(r"\$\{(\w+)\}", s)
    if m:
        key = m.group(1)
        val = context.get(key, (context.get("user_params") or {}).get(key))
        return list(val) if isinstance(val, (list, tuple)) else []
    try:
        val = ast.literal_eval(s)
    except Exception:
        return []
    return list(val) if isinstance(val, (list, tuple)) else []


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    items = _resolve_items(params, context)
    sub_steps = params.get("steps") or []
    item_key = params.get("item_key", "item")
    continue_on_error = bool(params.get("continue_on_error", True))

    if not items:
        return {"status": "failed", "error": "loop 步骤缺少可遍历的 items 列表"}
    if not sub_steps:
        return {"status": "failed", "error": "loop 步骤缺少 steps 子步骤"}

    results: List[Dict] = []
    for idx, item in enumerate(items):
        logger.info(f"  loop 第 {idx + 1}/{len(items)} 项")
        item_context = dict(context)
        item_context[item_key] = item
        try:
            for sub in sub_steps:
                sub_result = await executor._execute_step(sub, item_context)
                if sub_result.get("status") == "failed":
                    raise RuntimeError(sub_result.get("error", "子步骤失败"))
                item_context.update(sub_result.get("context", {}))
            results.append({"index": idx, "status": "success", "item": item})
        except Exception as e:
            logger.warning(f"  loop 第 {idx + 1} 项失败: {e}")
            results.append({"index": idx, "status": "failed", "item": item, "error": str(e)})
            if not continue_on_error:
                return {"status": "failed", "error": f"loop 第 {idx + 1} 项失败: {e}",
                        "context": {"loop_results": results}}

    failed = [r for r in results if r["status"] == "failed"]
    context_updates = {"loop_results": results, "loop_total": len(items), "loop_failed": len(failed)}
    if failed and continue_on_error:
        return {"status": "success", "context": context_updates,
                "warning": f"{len(failed)}/{len(items)} 项失败，已跳过"}
    return {"status": "success", "context": context_updates}
