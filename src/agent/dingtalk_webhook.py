# -*- coding: utf-8 -*-
"""
钉钉【群聊 Webhook 机器人】

用途：在群里发 文本 / Markdown 通知（任务开始/成功/失败、告警等）
特点：只能群聊，不能单聊给某个人；支持 @所有人 / @指定手机号
凭证：webhook URL + secret（钉钉群 → 群设置 → 机器人 → 添加自定义机器人 → 加签模式里拿）
配置：config.yaml -> notifications.dingtalk 节点（app_key/app_secret 放这里没用，别混）
"""
import json
import time
import hmac
import base64
import hashlib
import urllib.parse
import urllib.request
from typing import Dict, Optional, List
from loguru import logger


_MOBILE_WEBHOOK = False  # 没用到的全局，留着防lint报错


class DingtalkWebhook:
    """群聊Webhook机器人"""

    def __init__(self, webhook: str = "", secret: str = "", timeout: int = 10):
        self.webhook = (webhook or "").strip()
        self.secret = (secret or "").strip()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        """是否配置好了 webhook"""
        return bool(self.webhook)

    @property
    def kind(self) -> str:
        return "群聊Webhook"

    # ------------------------------------------------------------------
    # 对外发消息的方法
    # ------------------------------------------------------------------
    def send_text(self, content: str, at_mobiles: List[str] = None, at_all: bool = False) -> Dict:
        return self._post({
            "msgtype": "text",
            "text": {"content": content},
            "at": {"atMobiles": at_mobiles or [], "isAtAll": bool(at_all)},
        })

    def send_markdown(self, title: str, text: str, at_mobiles: List[str] = None, at_all: bool = False) -> Dict:
        return self._post({
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {"atMobiles": at_mobiles or [], "isAtAll": bool(at_all)},
        })

    def notify_task_started(self, task_name: str, username: str = "") -> Dict:
        return self.send_markdown(
            f"任务开始: {task_name}",
            f"🤖 **任务开始**\n> 任务：{task_name}\n> 触发人：{username or '系统'}\n> 时间：{self._now()}"
        )

    def notify_task_success(self, task_name: str, elapsed_sec: float = 0, username: str = "", file_path: str = "") -> Dict:
        text = f"✅ **任务成功**\n> 任务：{task_name}\n> 耗时：{elapsed_sec}秒\n> 时间：{self._now()}"
        if file_path:
            text += f"\n> 文件：{file_path}"
        return self.send_markdown(f"任务成功: {task_name}", text)

    def notify_task_failed(self, task_name: str, error: str, username: str = "") -> Dict:
        return self.send_markdown(
            f"任务失败: {task_name}",
            f"❌ **任务失败**\n> 任务：{task_name}\n> 时间：{self._now()}\n\n```\n{error or '(无)'}\n```",
            at_all=True,
        )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _post(self, payload: Dict) -> Dict:
        if not self.webhook:
            logger.info("群聊Webhook机器人未配置(缺少webhook)，跳过发送")
            return {"success": False, "skipped": True, "error": "未配置webhook"}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._signed_url(), data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                r = json.loads(resp.read().decode())
                if r.get("errcode") == 0:
                    return {"success": True}
                return {"success": False, "error": r.get("errmsg", "未知错误")}
        except Exception as e:
            logger.warning(f"群聊Webhook发送失败: {e}")
            return {"success": False, "error": str(e)}

    def _signed_url(self) -> str:
        """加签模式（钉钉要求安全设置选加签）"""
        if not self.secret:
            return self.webhook
        ts = str(round(time.time() * 1000))
        sig = urllib.parse.quote_plus(base64.b64encode(
            hmac.new(self.secret.encode(), f"{ts}\n{self.secret}".encode(), hashlib.sha256).digest()
        ))
        sep = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{sep}timestamp={ts}&sign={sig}"

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")


# ================================================================
# 构建实例：按「task_config 覆盖 > user_config > 全局config.yaml」优先级读
# 【只】从 notifications.dingtalk 读，绝对不去 delivery 节点找。
# ================================================================

def build_webhook(task_config: Dict = None, user_config: Dict = None) -> DingtalkWebhook:
    webhook = ""
    secret = ""

    if task_config:
        webhook = str(task_config.get("dingtalk_webhook") or "")
        secret = str(task_config.get("dingtalk_secret") or "")

    if not webhook and user_config:
        # 1) 标准嵌套格式 user_config.notifications.dingtalk.{webhook,secret}
        dt = ((user_config.get("notifications") or {}).get("dingtalk") or {})
        webhook = str(dt.get("webhook") or "")
        secret = str(dt.get("secret") or "")
        # 2) 兼容扁平写法 user_config.dingtalk_webhook
        if not webhook:
            webhook = str(user_config.get("dingtalk_webhook") or "")
            secret = str(user_config.get("dingtalk_secret") or "")

    # 3) 全局 config.yaml 的 notifications.dingtalk
    if not webhook:
        try:
            from src.core.config import get_config
            dt = ((get_config().config_data.get("notifications") or {}).get("dingtalk") or {})
            webhook = str(dt.get("webhook") or "")
            secret = str(dt.get("secret") or "")
        except Exception:
            pass

    return DingtalkWebhook(webhook=webhook, secret=secret)
