# -*- coding: utf-8 -*-
"""
钉钉统一模块

两种机器人，分开放在同一个文件里：

  ┌─────────────────┬──────────────────┬─────────────────┐
  │     类名        │    DingTalkWebhook │   DingTalkApp   │
  ├─────────────────┼──────────────────┼─────────────────┤
  │  机器人类型      │  Webhook机器人     │  自建应用机器人   │
  │  能做什么        │  发文本/Markdown   │  发文件附件       │
  │  配置            │  webhook + secret │  app_key+secret  │
  │  API入口         │  oapi/webhook     │  oapi/gettoken   │
  └─────────────────┴──────────────────┴─────────────────┘

用法：
    from src.agent.dingtalk import DingTalkWebhook, DingTalkApp

    # 1. Webhook机器人发消息
    wh = DingTalkWebhook(webhook="https://oapi.dingtalk.com/robot/send?access_token=xxx")
    wh.send_text("任务完成")
    wh.send_markdown("标题", "### 内容")

    # 2. 自建应用发文件
    app = DingTalkApp(app_key="xxx", app_secret="xxx", agent_id=123)
    app.send_file("D:/report.xlsx", userid="user123")
"""
import json
import time
import hmac
import base64
import hashlib
import urllib.parse
import urllib.request
import os
from typing import Dict, Optional, List
from loguru import logger
import requests


# ============================================================
# 1. DingTalkWebhook — Webhook机器人
# ============================================================
class DingTalkWebhook:
    """通过Webhook发送文本/Markdown消息"""

    def __init__(self, webhook: str = "", secret: str = "", timeout: int = 10):
        self.webhook = webhook
        self.secret = secret
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.webhook)

    def send_text(self, content: str, at_mobiles: List[str] = None, at_all: bool = False) -> Dict:
        """发送纯文本消息"""
        return self._post({
            "msgtype": "text",
            "text": {"content": content},
            "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all}
        })

    def send_markdown(self, title: str, text: str, at_mobiles: List[str] = None, at_all: bool = False) -> Dict:
        """发送Markdown消息"""
        return self._post({
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all}
        })

    # ---- 业务快捷方法 ----
    def notify_task_started(self, task_name: str, username: str = "") -> Dict:
        return self.send_markdown(
            f"任务开始: {task_name}",
            f"🤖 **任务开始**\n\n> 任务：{task_name}\n> 触发人：{username or '系统'}\n> 时间：{self._now()}"
        )

    def notify_task_success(self, task_name: str, elapsed_sec: float = 0, username: str = "", file_path: str = "") -> Dict:
        text = f"✅ **任务成功**\n\n> 任务：{task_name}\n> 耗时：{elapsed_sec}秒\n> 时间：{self._now()}"
        if file_path:
            text += f"\n> 文件：{file_path}"
        return self.send_markdown(f"任务成功: {task_name}", text)

    def notify_task_failed(self, task_name: str, error: str, username: str = "") -> Dict:
        return self.send_markdown(
            f"任务失败: {task_name}",
            f"❌ **任务失败**\n\n> 任务：{task_name}\n> 时间：{self._now()}\n\n```\n{error or '(无)'}\n```",
            at_all=True
        )

    # ---- 内部方法 ----
    def _post(self, payload: Dict) -> Dict:
        if not self.webhook:
            return {"success": False, "skipped": True, "error": "未配置webhook"}
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
            logger.warning(f"钉钉webhook发送失败: {e}")
            return {"success": False, "error": str(e)}

    def _build_signed_url(self) -> str:
        if not self.secret:
            return self.webhook
        timestamp = str(round(time.time() * 1000))
        sign_str = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(self.secret.encode(), sign_str.encode(), hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        sep = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{sep}timestamp={timestamp}&sign={sign}"

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 2. DingTalkApp — 自建应用机器人
# ============================================================
class DingTalkApp:
    """通过钉钉自建应用发送文件给指定用户"""

    def __init__(self, app_key: str = "", app_secret: str = "", agent_id: str = "", timeout: int = 30):
        self.app_key = app_key
        self.app_secret = app_secret
        self.agent_id = agent_id
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.app_key and self.app_secret and self.agent_id)

    def send_file(self, file_path: str, userid: str) -> Dict:
        """发送文件给钉钉用户"""
        if not self.enabled:
            return {"success": False, "error": "钉钉自建应用配置不完整(需app_key+app_secret+agent_id)"}
        if not userid:
            return {"success": False, "error": "请指定接收人userid"}
        if not os.path.exists(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}

        # 1) 获取 access_token
        token = self._get_access_token()
        if not token:
            return {"success": False, "error": "获取access_token失败"}

        # 2) 上传文件到钉盘
        media_id = self._upload_media(token, file_path)
        if not media_id:
            return {"success": False, "error": "上传文件到钉盘失败"}

        # 3) 发送文件消息
        ok = self._send_file_msg(token, media_id, userid)
        if ok:
            logger.info(f"钉钉文件发送成功: {os.path.basename(file_path)}")
            return {"success": True, "media_id": media_id}
        return {"success": False, "error": "发送文件消息失败"}

    # ---- 内部方法 ----
    def _get_access_token(self) -> Optional[str]:
        resp = requests.get(
            "https://oapi.dingtalk.com/gettoken",
            params={"appkey": self.app_key, "appsecret": self.app_secret},
            timeout=self.timeout
        )
        data = resp.json()
        if data.get("errcode") != 0:
            logger.error(f"获取access_token失败: {data.get('errmsg')}")
            return None
        return data.get("access_token")

    def _upload_media(self, token: str, file_path: str) -> Optional[str]:
        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            resp = requests.post(
                "https://oapi.dingtalk.com/media/upload",
                params={"access_token": token, "type": "file"},
                files={"media": (file_name, f, "application/octet-stream")},
                timeout=self.timeout
            )
        data = resp.json()
        if data.get("errcode") != 0:
            logger.error(f"上传文件失败: {data.get('errmsg')}")
            return None
        return data.get("media_id")

    def _send_file_msg(self, token: str, media_id: str, userid: str) -> bool:
        resp = requests.post(
            "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2",
            params={"access_token": token},
            json={
                "agent_id": int(self.agent_id),
                "userid_list": userid,
                "msg": {"msgtype": "file", "file": {"media_id": media_id}}
            },
            timeout=self.timeout
        )
        data = resp.json()
        if data.get("errcode") != 0:
            logger.error(f"发送文件消息失败: {data.get('errmsg')}")
            return False
        return True


# ============================================================
# 构建函数：从配置中读取并实例化
# ============================================================
def build_webhook(task_config: Dict = None, user_config: Dict = None) -> DingTalkWebhook:
    """
    构建 Webhook 通知器
    优先级：task_config > user_config > config.yaml全局
    """
    webhook = ""
    secret = ""

    if task_config:
        webhook = task_config.get("dingtalk_webhook", "")
        secret = task_config.get("dingtalk_secret", "")

    if not webhook and user_config:
        webhook = user_config.get("delivery", {}).get("dingtalk_webhook", "")
        secret = user_config.get("delivery", {}).get("dingtalk_secret", "")
        if not webhook:
            webhook = user_config.get("dingtalk_webhook", "")
            secret = user_config.get("dingtalk_secret", "")

    if not webhook:
        try:
            from src.core.config import get_config
            cfg = get_config().config_data.get("notifications", {}).get("dingtalk", {})
            webhook = cfg.get("webhook", "")
            secret = cfg.get("secret", "")
        except Exception:
            pass

    return DingTalkWebhook(webhook=webhook, secret=secret)


def build_app(user_config: Dict = None) -> DingTalkApp:
    """
    构建自建应用机器人
    从 user_config 或 config.yaml 读取 app_key/app_secret/agent_id
    """
    cfg = {}
    if user_config:
        cfg = user_config.get("delivery", {}).get("dingtalk", {})

    if not cfg.get("app_key"):
        try:
            from src.core.config import get_config
            cfg = get_config().config_data.get("delivery", {}).get("dingtalk", {})
        except Exception:
            pass

    return DingTalkApp(
        app_key=cfg.get("app_key", ""),
        app_secret=cfg.get("app_secret", ""),
        agent_id=cfg.get("agent_id", ""),
    )
