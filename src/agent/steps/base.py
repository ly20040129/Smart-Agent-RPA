# -*- coding: utf-8 -*-
"""步骤执行的基础工具"""
import re
from typing import Any, Dict


def resolve_placeholders(params: Any, context: Dict) -> Any:
    """递归替换参数中的 ${param} 占位符为用户输入的值"""
    if not params:
        return params
    user_params = (context or {}).get("user_params", {}) or {}

    def _sub(s: str) -> str:
        if not isinstance(s, str):
            return s

        def _m(mo):
            k = mo.group(1)
            return str(user_params[k]) if k in user_params else mo.group(0)

        return re.sub(r"\$\{(\w+)\}", _m, s)

    if isinstance(params, dict):
        return {k: resolve_placeholders(v, context) for k, v in params.items()}
    if isinstance(params, list):
        return [resolve_placeholders(v, context) for v in params]
    if isinstance(params, str):
        return _sub(params)
    return params


def ok(**context) -> Dict[str, Any]:
    """构造成功结果"""
    return {"status": "success", "context": context} if context else {"status": "success"}


def fail(error: str) -> Dict[str, Any]:
    """构造失败结果"""
    return {"status": "failed", "error": error}
