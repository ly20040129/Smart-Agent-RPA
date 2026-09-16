# -*- coding: utf-8 -*-
"""通知步骤（通过 executor.notifier 统一发送，群聊 + 单聊）"""
from typing import Any, Dict

from loguru import logger


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    notifier = executor.notifier
    if not notifier or not notifier.enabled:
        logger.info("📢 通知跳过：未配置钉钉")
        return {"status": "success", "skipped": True, "warning": "钉钉未配置"}

    message = params.get("message", "任务通知")
    logger.info(f"📢 通知(action={action}): {message}")

    try:
        if action in ("dingtalk_text", "dingtalk", "text"):
            res = notifier.send_group_text(
                content=message,
                at_mobiles=params.get("at_mobiles"),
                at_all=bool(params.get("at_all", False)),
            )
            return _result(res)

        if action in ("dingtalk_markdown", "markdown"):
            res = notifier.send_group_markdown(
                title=params.get("title") or "智能体平台通知",
                text=params.get("text") or message,
                at_mobiles=params.get("at_mobiles"),
                at_all=bool(params.get("at_all", False)),
            )
            return _result(res)

        if action in ("send_oto_message", "oto_text", "dingtalk_oto"):
            return _oto(notifier, params, context, lambda uid: notifier.send_oto_text(message, uid))

        if action in ("send_oto_markdown", "oto_markdown"):
            return _oto(notifier, params, context,
                        lambda uid: notifier.send_oto_markdown(
                            params.get("title") or "通知", params.get("text") or message, uid))

        return {"status": "success"}
    except Exception as e:
        logger.warning(f"通知步骤执行异常(不影响主流程): {e}")
        return {"status": "failed", "error": str(e)}


def _result(res: Dict) -> Dict[str, Any]:
    if res.get("success"):
        return {"status": "success", "context": {"notify_result": res}}
    return {"status": "failed", "error": res.get("error", "发送失败")}


def _resolve_userid(params: Dict, context: Dict) -> str:
    defaults = (context or {}).get("_task_defaults", {}) or {}
    return (params.get("dingtalk_userid") or defaults.get("dingtalk_userid") or "").strip()


def _oto(notifier, params: Dict, context: Dict, send_fn) -> Dict[str, Any]:
    userid = _resolve_userid(params, context)
    if not userid:
        return {"status": "failed", "error": "缺少 dingtalk_userid（step.params 或 yaml 顶层）"}
    if not notifier.robot.enabled:
        return {"status": "failed", "error": "单聊机器人未配置(delivery.dingtalk.app_key/app_secret)"}
    res = send_fn(userid)
    return _result(res)
