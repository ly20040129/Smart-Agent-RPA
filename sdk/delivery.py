# -*- coding: utf-8 -*-
"""
交付服务 —— 把任务产出的文件按渠道分发出去

渠道：
    local     保存到用户本机下载目录
    dingtalk  钉钉单聊发给具体人（调 sdk/dingtalk.py 的 DingtalkRobot）
    email     邮件附件发送

用法（workflow 里）：
    from sdk.delivery import DeliveryService

    res = await DeliveryService().deliver(
        file_path="D:/报表.xlsx",
        user_config=user_params,
        task_name="京东出库",
        dingtalk_userid="178329xxx",
        channels=["local", "dingtalk"],
    )
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

from sdk.dingtalk_robot import build_robot


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
        # build_robot 内部已按「user_config.delivery.dingtalk -> 全局 delivery.dingtalk」读好
        robot = build_robot(user_config)
        if not robot.enabled:
            return {"success": False, "error": "单聊机器人未配置(delivery.dingtalk.app_key/app_secret)"}
        if not userid:
            return {"success": False, "error": "缺少接收人 dingtalk_userid（在任务yaml params 里配置）"}
        return robot.send_file(file_path, userid)

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
