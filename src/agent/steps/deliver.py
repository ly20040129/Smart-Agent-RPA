# -*- coding: utf-8 -*-
"""文件交付步骤"""
from typing import Any, Dict

from loguru import logger


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    if action != "deliver_file":
        return {"status": "failed", "error": f"未知交付动作: {action}"}

    file_path = params.get("file_path") or context.get("downloaded_file") or context.get("api_output_file")
    if not file_path:
        return {"status": "failed", "error": "没有可交付的文件"}

    username = context.get("username", "")
    user_config = context.get("user_config", {})
    template_name = params.get("template_name")
    if template_name and username:
        template_path = executor.template_manager.get_template_by_name(username, template_name)
        if template_path:
            logger.info(f"  使用模板: {template_name}")
            context["template_path"] = str(template_path)

    defaults = (context or {}).get("_task_defaults", {}) or {}
    dingtalk_userid = params.get("dingtalk_userid") or defaults.get("dingtalk_userid")
    result = await executor.delivery_service.deliver(
        file_path=file_path,
        user_config=user_config,
        task_name=params.get("task_name", ""),
        channels=params.get("channels"),
        dingtalk_userid=dingtalk_userid,
    )

    success_ch = [k for k, v in result.items() if isinstance(v, dict) and v.get("success")]
    failed_ch = [k for k, v in result.items() if isinstance(v, dict) and not v.get("success")]
    if success_ch:
        logger.info(f"  交付成功: {', '.join(success_ch)}")
    if failed_ch:
        logger.warning(f"  交付失败: {', '.join(failed_ch)}")
    return {"status": "success", "context": {"deliver_result": result, "delivered_channels": success_ch}}
