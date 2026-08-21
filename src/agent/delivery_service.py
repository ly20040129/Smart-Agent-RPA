# -*- coding: utf-8 -*-
"""交付服务 - 本地/钉钉/邮件"""
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

    async def deliver(self, file_path: str, user_config: Dict, task_name: str = "",
                      dingtalk_userid: str = None, channels: List[str] = None) -> Dict:
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}
        if not channels:
            channels = user_config.get("delivery", {}).get("default_channels", ["local"])

        results = {}
        for ch in channels:
            if ch == "local":
                results["local"] = await self._save_local(file_path, user_config, task_name)
            elif ch == "dingtalk":
                results["dingtalk"] = await self._send_dingtalk(file_path, user_config, dingtalk_userid)
            elif ch == "email":
                results["email"] = await self._send_email(file_path, user_config)
            else:
                results[ch] = {"success": False, "error": f"未知渠道: {ch}"}
        return results

    async def _save_local(self, file_path: str, user_config: Dict, task_name: str) -> Dict:
        download_root = user_config.get("download_root", "")
        if not download_root:
            download_root = os.path.join(str(Path.home()), "Downloads", "智能体平台")
        os.makedirs(download_root, exist_ok=True)
        ext = os.path.splitext(file_path)[1]
        filename = f"{task_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        dest = os.path.join(download_root, filename)
        shutil.copy2(file_path, dest)
        logger.info(f"本地保存成功: {dest}")
        return {"success": True, "path": dest}

    async def _send_dingtalk(self, file_path: str, user_config: Dict, userid: str) -> Dict:
        app = build_app(user_config)
        if not app.enabled:
            from src.core.config import get_config
            cfg = get_config().config_data.get("delivery", {}).get("dingtalk", {})
            if cfg.get("app_key"):
                app = DingTalkApp(cfg.get("app_key"), cfg.get("app_secret"), cfg.get("agent_id"))
        if not app.enabled:
            return {"success": False, "error": "钉钉自建应用未配置"}
        return app.send_file(file_path, userid)

    async def _send_email(self, file_path: str, user_config: Dict) -> Dict:
        cfg = user_config.get("email_settings", {})
        smtp_server = cfg.get("smtp_server")
        smtp_port = int(cfg.get("smtp_port", 465))
        sender = cfg.get("sender")
        password = cfg.get("password")
        recipients = cfg.get("recipients", [])
        if isinstance(recipients, str):
            recipients = [r.strip() for r in recipients.split(",") if r.strip()]
        if not all([smtp_server, sender, password, recipients]):
            return {"success": False, "error": "邮件配置不完整"}

        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = f"智能体平台 - {os.path.basename(file_path)}"
        msg.attach(MIMEText(f"附件为任务生成的文件：{os.path.basename(file_path)}", 'plain', 'utf-8'))

        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
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
            logger.info(f"邮件发送成功: {os.path.basename(file_path)}")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
