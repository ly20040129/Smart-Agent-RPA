# -*- coding: utf-8 -*-
"""
交付服务 - 将处理后的数据文件交付给用户

支持的交付渠道：
1. local - 本地保存（根据用户配置的路径和文件名模板）
2. dingtalk - 通过钉钉Webhook发送到群
3. email - 通过SMTP发送邮件附件
"""
import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from loguru import logger


class DeliveryService:
    """交付服务"""
    
    def __init__(self):
        pass
    
    async def deliver(self, file_path: str, user_config: Dict[str, Any], task_name: str = "", 
                      channels: List[str] = None) -> Dict[str, Any]:
        """
        交付文件到指定渠道
        
        Args:
            file_path: 文件路径
            user_config: 用户配置（包含download_root、delivery等）
            task_name: 任务名称（用于文件名模板）
            channels: 交付渠道列表，为None时使用用户配置的默认渠道
            
        Returns:
            各渠道交付结果
        """
        results = {}
        
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}
        
        if channels is None:
            channels = user_config.get("delivery", {}).get("default_channels", ["local"])
        
        for channel in channels:
            try:
                if channel == "local":
                    results["local"] = await self._deliver_local(file_path, user_config, task_name)
                elif channel == "dingtalk":
                    results["dingtalk"] = await self._deliver_dingtalk(file_path, user_config)
                elif channel == "email":
                    results["email"] = await self._deliver_email(file_path, user_config)
                else:
                    results[channel] = {"success": False, "error": f"未知渠道: {channel}"}
            except Exception as e:
                logger.error(f"交付[{channel}]失败: {e}")
                results[channel] = {"success": False, "error": str(e)}
        
        return results
    
    async def _deliver_local(self, file_path: str, user_config: Dict, task_name: str) -> Dict:
        """本地保存"""
        download_root = user_config.get("download_root", "")
        filename_pattern = user_config.get("filename_pattern", "{name}_{date}.{ext}")
        
        if not download_root:
            download_root = os.path.join(str(Path.home()), "Downloads", "智能体平台")
        
        # 创建目录
        os.makedirs(download_root, exist_ok=True)
        
        # 生成文件名
        now = datetime.now()
        original_name = os.path.basename(file_path)
        name_without_ext = os.path.splitext(original_name)[0]
        ext = os.path.splitext(original_name)[1]
        
        filename = filename_pattern.replace("{name}", task_name or name_without_ext)
        filename = filename.replace("{date}", now.strftime("%Y%m%d"))
        filename = filename.replace("{time}", now.strftime("%H%M%S"))
        filename = filename.replace("{ext}", ext.lstrip("."))
        
        # 避免重复
        dest_path = os.path.join(download_root, filename)
        counter = 1
        while os.path.exists(dest_path):
            base = os.path.splitext(filename)[0]
            dest_path = os.path.join(download_root, f"{base}_{counter}{ext}")
            counter += 1
        
        # 复制文件
        import shutil
        shutil.copy2(file_path, dest_path)
        
        logger.info(f"✅ 本地保存成功: {dest_path}")
        return {"success": True, "path": dest_path}
    
    async def _deliver_dingtalk(self, file_path: str, user_config: Dict) -> Dict:
        """钉钉发送（通过Webhook上传文件）"""
        webhook = user_config.get("dingtalk_webhook", "")
        if not webhook:
            return {"success": False, "error": "未配置钉钉Webhook"}
        
        import urllib.request
        import urllib.parse
        
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # 读取文件内容
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # 构造multipart请求
        boundary = f"----WebKitFormBoundary{datetime.now().timestamp()}"
        body = b""
        
        # 文件部分
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += file_content
        body += b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        
        req = urllib.request.Request(
            webhook,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            }
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("errcode") == 0:
                    logger.info(f"✅ 钉钉发送成功: {file_name}")
                    return {"success": True, "result": result}
                else:
                    return {"success": False, "error": result.get("errmsg", "未知错误")}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _deliver_email(self, file_path: str, user_config: Dict) -> Dict:
        """邮件发送"""
        email_cfg = user_config.get("email_settings", {})
        smtp_server = email_cfg.get("smtp_server", "")
        smtp_port = email_cfg.get("smtp_port", 465)
        sender = email_cfg.get("sender", "")
        password = email_cfg.get("password", "")
        recipients = email_cfg.get("recipients", [])
        
        if not all([smtp_server, sender, password, recipients]):
            return {"success": False, "error": "邮件配置不完整"}
        
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = f"智能体平台 - 文件交付: {os.path.basename(file_path)}"
        
        # 正文
        body = f"""您好，

智能体平台已完成任务执行，附件为生成的数据文件：
文件名：{os.path.basename(file_path)}
生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

此邮件由智能体平台自动发送。
"""
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # 附件
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
