# -*- coding: utf-8 -*-
"""
交付服务 - 把文件交付给用户
支持：本地保存 / 钉钉发送 / 邮件发送
"""
import os
import json
import shutil
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from loguru import logger
import requests


class DeliveryService:
    """交付服务"""

    async def deliver(self, file_path: str, user_config: Dict, task_name: str = "",
                      dingtalk_userid: str = None, channels: List[str] = None) -> Dict:
        """
        统一入口：把文件交付到指定渠道

        参数:
            file_path: 要发送的文件路径
            user_config: 用户配置（包含钉钉AppKey等）
            task_name: 任务名称（用于本地保存的文件名）
            dingtalk_userid: 钉钉用户ID（发给谁）
            channels: 交付渠道列表，如 ["local", "dingtalk"]
        """
        results = {}

        # 文件不存在就直接返回
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}

        # 默认渠道：本地保存
        if not channels:
            channels = user_config.get("delivery", {}).get("default_channels", ["local"])

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
    # 1. 本地保存
    # ============================================================
    async def _save_local(self, file_path: str, user_config: Dict, task_name: str) -> Dict:
        """保存到本地文件夹"""
        # 确定保存目录
        download_root = user_config.get("download_root", "")
        if not download_root:
            download_root = os.path.join(str(Path.home()), "Downloads", "智能体平台")

        os.makedirs(download_root, exist_ok=True)

        # 生成文件名：任务名_日期.扩展名
        now = datetime.now()
        ext = os.path.splitext(file_path)[1]
        filename = f"{task_name}_{now.strftime('%Y%m%d_%H%M%S')}{ext}"
        dest_path = os.path.join(download_root, filename)

        # 复制文件
        shutil.copy2(file_path, dest_path)
        logger.info(f"✅ 本地保存成功: {dest_path}")
        return {"success": True, "path": dest_path}

    # ============================================================
    # 2. 钉钉发送（自建应用）
    # ============================================================
    async def _send_dingtalk(self, file_path: str, user_config: Dict, userid: str) -> Dict:
        """通过钉钉自建应用发送文件"""
        # 读取配置
        dingtalk_cfg = user_config.get("delivery", {}).get("dingtalk", {})
        app_key = dingtalk_cfg.get("app_key")
        app_secret = dingtalk_cfg.get("app_secret")
        agent_id = dingtalk_cfg.get("agent_id")

        # 检查必填项
        if not app_key or not app_secret:
            return {"success": False, "error": "缺少钉钉 AppKey/AppSecret"}
        if not agent_id:
            return {"success": False, "error": "缺少钉钉 AgentId"}
        if not userid:
            return {"success": False, "error": "请指定钉钉用户ID (userid)"}

        # 1) 获取 access_token
        token_resp = requests.get(
            "https://oapi.dingtalk.com/gettoken",
            params={"appkey": app_key, "appsecret": app_secret}
        )
        if token_resp.status_code != 200:
            return {"success": False, "error": f"获取token失败: {token_resp.text}"}

        token_data = token_resp.json()
        if token_data.get("errcode") != 0:
            return {"success": False, "error": f"获取token失败: {token_data.get('errmsg')}"}

        access_token = token_data.get("access_token")

        # 2) 上传文件到钉盘
        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            upload_resp = requests.post(
                "https://oapi.dingtalk.com/media/upload",
                params={"access_token": access_token, "type": "file"},
                files={"media": (file_name, f, "application/octet-stream")}
            )

        upload_data = upload_resp.json()
        if upload_data.get("errcode") != 0:
            return {"success": False, "error": f"上传文件失败: {upload_data.get('errmsg')}"}

        media_id = upload_data.get("media_id")

        # 3) 发送文件消息给用户
        send_resp = requests.post(
            "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2",
            params={"access_token": access_token},
            json={
                "agent_id": int(agent_id),
                "userid_list": userid,          # 多个用逗号分隔，如 "id1,id2"
                "msg": {
                    "msgtype": "file",
                    "file": {"media_id": media_id}
                }
            }
        )

        send_data = send_resp.json()
        if send_data.get("errcode") != 0:
            return {"success": False, "error": f"发送文件失败: {send_data.get('errmsg')}"}

        logger.info(f"✅ 钉钉文件发送成功: {file_name}")
        return {"success": True, "media_id": media_id}

    # ============================================================
    # 3. 邮件发送
    # ============================================================
    async def _send_email(self, file_path: str, user_config: Dict) -> Dict:
        """通过邮件发送文件"""
        email_cfg = user_config.get("email_settings", {})
        smtp_server = email_cfg.get("smtp_server")
        smtp_port = email_cfg.get("smtp_port", 465)
        sender = email_cfg.get("sender")
        password = email_cfg.get("password")
        recipients = email_cfg.get("recipients", [])

        if not all([smtp_server, sender, password, recipients]):
            return {"success": False, "error": "邮件配置不完整"}

        # 构造邮件
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = f"智能体平台 - {os.path.basename(file_path)}"

        body = f"附件为任务生成的文件：{os.path.basename(file_path)}"
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # 添加附件
        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{file_name}"')
        msg.attach(part)

        # 发送
        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                server.starttls()

            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
            server.quit()

            logger.info(f"✅ 邮件发送成功: {file_name}")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}