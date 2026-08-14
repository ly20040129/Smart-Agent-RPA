# -*- coding: utf-8 -*-
"""
钉钉通知模块 - 发送文本/Markdown 消息（任务开始/成功/失败）

与 delivery_service 的区别：
- delivery_service: 发送文件附件
- dingtalk_notifier: 发送文本消息通知
"""
import json
import time
import hmac
import base64
import hashlib
import urllib.parse
import urllib.request
from typing import Dict, Optional
from loguru import logger


class DingTalkNotifier:
    """
    钉钉机器人通知器（只发消息，不发文件）

    用法：
        notifier = DingTalkNotifier(webhook="https://oapi.dingtalk.com/robot/send?access_token=xxx")
        notifier.send_text("任务执行完成")
        notifier.send_markdown("标题", "### 内容")
    """

    def __init__(self, webhook: str = "", secret: str = "", timeout: int = 10):
        self.webhook = webhook
        self.secret = secret
        self.timeout = timeout

    # ============================================================
    # 核心方法
    # ============================================================

    def send_text(self, content: str, at_all: bool = False) -> Dict:
        """发送纯文本消息"""
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {"isAtAll": at_all}
        }
        return self._post(payload)

    def send_markdown(self, title: str, text: str, at_all: bool = False) -> Dict:
        """发送 Markdown 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {"isAtAll": at_all}
        }
        return self._post(payload)

    # ============================================================
    # 业务快捷方法
    # ============================================================

    def notify_task_started(self, task_name: str, username: str = "", **extra) -> Dict:
        """任务开始通知"""
        text = f"🤖 **任务开始执行**\n\n> 任务：{task_name}\n> 触发人：{username or '系统定时'}\n> 时间：{self._now()}"
        return self.send_markdown(f"任务开始: {task_name}", self._add_extra(text, extra))

    def notify_task_success(self, task_name: str, file_path: str = "", elapsed_sec: float = 0, **extra) -> Dict:
        """任务成功通知"""
        text = f"✅ **任务执行成功**\n\n> 任务：{task_name}\n> 耗时：{elapsed_sec}秒\n> 时间：{self._now()}"
        if file_path:
            text += f"\n> 文件：{file_path}"
        return self.send_markdown(f"任务成功: {task_name}", self._add_extra(text, extra))

    def notify_task_failed(self, task_name: str, error: str = "", **extra) -> Dict:
        """任务失败通知"""
        text = f"❌ **任务执行失败**\n\n> 任务：{task_name}\n> 时间：{self._now()}\n\n错误：\n```\n{error or '(无)'}\n```"
        return self.send_markdown(f"任务失败: {task_name}", self._add_extra(text, extra), at_all=True)

    # ============================================================
    # 内部方法
    # ============================================================

    def _post(self, payload: Dict) -> Dict:
        """发送 HTTP 请求到钉钉"""
        if not self.webhook:
            return {"success": False, "error": "未配置 webhook"}

        url = self._build_signed_url()
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode())
                if result.get("errcode") == 0:
                    return {"success": True}
                return {"success": False, "error": result.get("errmsg", "未知错误")}
        except Exception as e:
            logger.warning(f"钉钉发送失败: {e}")
            return {"success": False, "error": str(e)}

    def _build_signed_url(self) -> str:
        """加签模式：生成带签名的 URL"""
        url = self.webhook
        if not self.secret:
            return url

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(self.secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}timestamp={timestamp}&sign={sign}"

    def _now(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _add_extra(self, text: str, extra: Dict) -> str:
        for k, v in extra.items():
            text += f"\n> {k}: {v}"
        return text


# ============================================================
# 构建函数：从 config.yaml 读取配置
# ============================================================
def build_notifier(
    task_config: Optional[Dict] = None,
    user_config: Optional[Dict] = None,
) -> DingTalkNotifier:
    """
    从配置构建通知器，优先级：task_config > user_config > config.yaml
    """
    webhook = ""
    secret = ""

    # 1. task_config
    if task_config:
        webhook = task_config.get("dingtalk_webhook", "")
        secret = task_config.get("dingtalk_secret", "")

    # 2. user_config
    if not webhook and user_config:
        webhook = user_config.get("delivery", {}).get("dingtalk_webhook", "")
        secret = user_config.get("delivery", {}).get("dingtalk_secret", "")
        if not webhook:
            webhook = user_config.get("dingtalk_webhook", "")
            secret = user_config.get("dingtalk_secret", "")

    # 3. config.yaml 全局配置
    if not webhook:
        try:
            from src.core.config import get_config
            config = get_config()
            dingtalk = config.get("notifications", {}).get("dingtalk", {})
            webhook = dingtalk.get("webhook", "")
            secret = dingtalk.get("secret", "")
        except:
            pass

    return DingTalkNotifier(webhook=webhook, secret=secret)