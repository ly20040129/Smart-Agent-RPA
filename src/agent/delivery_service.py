# -*- coding: utf-8 -*-
"""
交付服务 - 把文件交付给用户
渠道：本地保存 / 钉钉(自建应用发文件) / 邮件

钉钉发消息用 DingTalkWebhook，钉钉发文件用 DingTalkApp，
两个类都在 src/agent/dingtalk.py 里。
"""
import os
import shutil
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from loguru import logger

from src.agent.dingtalk import DingTalkApp, build_app


class DeliveryService:
    """交付服务"""

    async def deliver(self, file_path: str, user_config: Dict, task_name: str = "",
                      dingtalk_userid: str = None, channels: List[str] = None) -> Dict:
        """统一入口：把文件交付到指定渠道"""
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}

        if not channels:
            channels = user_config.get("delivery", {}).get("default_channels", ["local"])

        results = {}
        for channel in channels:
            if channel == "local":
                results["local"] = await self._save_local(file_path, user_config, task_name)
            elif channel == "dingtalk":
                results["dingtalk"] = await self._send_dingtalk(file_path, user_config, dingtalk_userid)
            elif channel == "email":
                results["email"] = await self._send_email(file_path, user_config)
            else:
                results[channel] = {"success": False, "error": f"未知渠道: {channel}"}
        return results

    # ============================================================
    # 本地保存
    # ============================================================
    async def _save_local(self, file_path: str, user_config: Dict, task_name: str) -> Dict:
        download_root = user_config.get("download_root", "")
        if not download_root:
            download_root = os.path.join(str(Path.home()), "Downloads", "智能体平台")
        os.makedirs(download_root, exist_ok=True)

        now = datetime.now()
        ext = os.path.splitext(file_path)[1]
        filename = f"{task_name}_{now.strftime('%Y%m%d_%H%M%S')}{ext}"
        dest = os.path.join(download_root, filename)
        shutil.copy2(file_path, dest)
        logger.info(f"本地保存成功: {dest}")
        return {"success": True, "path": dest}

    # ============================================================
    # 钉钉发送文件（调用 DingTalkApp）
    # ============================================================
    async def _send_dingtalk(self, file_path: str, user_config: Dict, userid: str) -> Dict:
        app = build_app(user_config)
        if not app.enabled:
            # 降级：尝试从全局 config.yaml 读
            from src.core.config import get_config
            cfg = get_config().config_data.get("delivery", {}).get("dingtalk", {})
            if cfg.get("app_key"):
                app = DingTalkApp(cfg.get("app_key"), cfg.get("app_secret"), cfg.get("agent_id"))
        if not app.enabled:
            return {"success": False, "error": "钉钉自建应用未配置(app_key/app_secret/agent_id)"}
        return app.send_file(file_path, userid)

    # ============================================================
    # 邮件发送
    # ============================================================
    async def _send_email(self, file_path: str, user_config: Dict) -> Dict:
        email_cfg = user_config.get("email_settings", {})
        smtp_server = email_cfg.get("smtp_server")
        smtp_port = int(email_cfg.get("smtp_port", 465))
        sender = email_cfg.get("sender")
        password = email_cfg.get("password")
        recipients = email_cfg.get("recipients", [])
        if isinstance(recipients, str):
            recipients = [r.strip() for r in recipients.split(",") if r.strip()]

        if not all([smtp_server, sender, password, recipients]):
            return {"success": False, "error": "邮件配置不完整"}

        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = f"智能体平台 - {os.path.basename(file_path)}"
        msg.attach(MIMEText(f"附件为任务生成的文件：{os.path.basename(file_path)}", 'plain', 'utf-8'))

        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{file_name}"')
        msg.attach(part)

        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
            server.quit()
            logger.info(f"邮件发送成功: {file_name}")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
