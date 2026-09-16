# -*- coding: utf-8 -*-
"""API / 通知类动作步骤"""
from typing import Any, Dict

from . import notify, workflow

_NOTIFY_ACTIONS = {
    "dingtalk_text", "dingtalk", "text",
    "dingtalk_markdown", "markdown",
    "send_oto_message", "oto_text", "dingtalk_oto",
    "send_oto_markdown", "oto_markdown",
}


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    if action == "run_workflow":
        return await workflow.run(executor, action, params, context)
    if action in _NOTIFY_ACTIONS:
        return await notify.run(executor, action, params, context)
    return {"status": "failed", "error": f"未知API动作: {action}"}
