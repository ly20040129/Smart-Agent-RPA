# -*- coding: utf-8 -*-
"""
统一通知门面（借鉴旧项目 msgTools：发送前记录意图、发送后记录结果）

把「群聊 Webhook」和「单聊自建应用」收口到一个入口，任何通知都走这里，
统一返回 {success, error, channel}，并带发送日志，方便排查。
"""
from typing import Dict, Optional

from loguru import logger

from src.agent.dingtalk_robot import DingtalkRobot, build_robot
from src.agent.dingtalk_webhook import DingtalkWebhook, build_webhook


class Notifier:
    """统一通知器：群聊 + 单聊"""

    def __init__(self, webhook: DingtalkWebhook, robot: DingtalkRobot):
        self.webhook = webhook
        self.robot = robot

    @property
    def enabled(self) -> bool:
        return self.webhook.enabled or self.robot.enabled

    # ---- 群聊 ----

    def send_group_text(self, content: str, at_mobiles=None, at_all: bool = False) -> Dict:
        return self._dispatch(
            "群聊", "文本", "群聊Webhook",
            lambda: self.webhook.send_text(content, at_mobiles, at_all),
        )

    def send_group_markdown(self, title: str, text: str, at_mobiles=None, at_all: bool = False) -> Dict:
        return self._dispatch(
            "群聊", "Markdown", "群聊Webhook",
            lambda: self.webhook.send_markdown(title, text, at_mobiles, at_all),
        )

    # ---- 单聊 ----

    def send_oto_text(self, content: str, userid: str) -> Dict:
        return self._dispatch(
            "单聊", "文本", userid,
            lambda: self.robot.send_text(content, userid),
        )

    def send_oto_markdown(self, title: str, text: str, userid: str) -> Dict:
        return self._dispatch(
            "单聊", "Markdown", userid,
            lambda: self.robot.send_markdown(title, text, userid),
        )

    def send_oto_file(self, file_path: str, userid: str) -> Dict:
        return self._dispatch(
            "单聊", "文件", userid,
            lambda: self.robot.send_file(file_path, userid),
        )

    # ---- 任务三态通知 ----

    def notify_task_started(self, task_name: str, username: str = "") -> Dict:
        return self.send_group_markdown(
            f"任务开始: {task_name}",
            f"🤖 **任务开始**\n> 任务：{task_name}\n> 触发人：{username or '系统'}",
        )

    def notify_task_success(self, task_name: str, elapsed_sec: float = 0,
                            username: str = "", file_path: str = "") -> Dict:
        text = f"✅ **任务成功**\n> 任务：{task_name}\n> 耗时：{elapsed_sec}秒"
        if file_path:
            text += f"\n> 文件：{file_path}"
        return self.send_group_markdown(f"任务成功: {task_name}", text)

    def notify_task_failed(self, task_name: str, error: str, username: str = "") -> Dict:
        return self.send_group_markdown(
            f"任务失败: {task_name}",
            f"❌ **任务失败**\n> 任务：{task_name}\n\n```\n{error or '(无)'}\n```",
            at_all=True,
        )

    # ---- 内部 ----

    def _dispatch(self, channel: str, kind: str, target: str, send_fn) -> Dict:
        """统一发送：先记意图、再发送、最后记结果"""
        logger.info(f"[通知] 发送前 → {channel}/{kind} → {target}")
        try:
            res = send_fn() or {}
        except Exception as e:
            logger.warning(f"[通知] 发送异常 → {channel}/{kind} → {target}: {e}")
            return {"success": False, "error": str(e), "channel": channel}
        if res.get("success"):
            logger.info(f"[通知] 发送成功 → {channel}/{kind} → {target}")
        else:
            logger.warning(f"[通知] 发送失败 → {channel}/{kind} → {target}: {res.get('error', '')}")
        return {"success": bool(res.get("success")), "error": res.get("error", ""), "channel": channel}


def build_notifier(task_config: Optional[Dict] = None, user_config: Optional[Dict] = None) -> Notifier:
    """按「task_config 覆盖 > user_config > 全局config.yaml」优先级构建"""
    return Notifier(
        webhook=build_webhook(task_config=task_config, user_config=user_config),
        robot=build_robot(user_config=user_config),
    )
