# -*- coding: utf-8 -*-
"""
钉钉【自建应用单聊机器人】

用途：给具体人发 1 对 1 消息（文本 / Markdown / 文件）
特点：单聊，消息出现在"人与机器人"的会话窗口里（不是"工作通知"！）
凭证：app_key + app_secret（钉钉开发者后台 → 你的自建应用 → 凭证与基础信息里拿）
接收人：钉钉 userid（长得像一串数字，如 "1783298686946923"），在每个任务 yaml 的 params.dingtalk_userid 里写
配置：config.yaml -> delivery.dingtalk 节点
"""
import json
import os
import threading
import time
from typing import Dict, Optional
from loguru import logger
import requests


_MIME = {
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls':  'application/vnd.ms-excel',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.doc':  'application/msword',
    '.pdf':  'application/pdf',
    '.txt':  'text/plain',
    '.csv':  'text/csv',
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.zip':  'application/zip',
    '.rar':  'application/x-rar-compressed',
}


class DingtalkRobot:
    """自建应用单聊机器人（发给具体钉钉 userid）"""

    def __init__(self, app_key: str = "", app_secret: str = "", agent_id: str = "", robot_code: str = "", timeout: int = 30):
        self.app_key = (app_key or "").strip()
        self.app_secret = (app_secret or "").strip()
        self.agent_id = (agent_id or "").strip()  # 保留兼容，实际不使用
        self.robot_code = (robot_code or "").strip()
        self.timeout = timeout
        self._access_token: Optional[str] = None
        self._access_token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self._token_refresh_margin = 300

    @property
    def enabled(self) -> bool:
        """只要 app_key + app_secret 齐了就能用，不需要 agent_id"""
        return bool(self.app_key and self.app_secret)

    @property
    def kind(self) -> str:
        return "单聊自建应用"

    # ------------------------------------------------------------------
    # 对外主接口：3 个发送方法，都要求 userid
    # ------------------------------------------------------------------
    def send_text(self, content: str, userid: str) -> Dict:
        """单聊发纯文本"""
        prep = self._check_ready(userid)
        if prep: return prep
        tok = self._v2_token()
        if not tok: return {"success": False, "error": "获取accessToken失败"}
        ok, info = self._batch(tok, "sampleText", {"content": content or ""}, userid)
        if ok:
            logger.info(f"[钉钉单聊] 文本 → {userid} OK")
            return {"success": True, "info": info}
        return {"success": False, "error": f"发送失败: {info}"}

    def send_markdown(self, title: str, text: str, userid: str) -> Dict:
        """单聊发 Markdown"""
        prep = self._check_ready(userid)
        if prep: return prep
        tok = self._v2_token()
        if not tok: return {"success": False, "error": "获取accessToken失败"}
        ok, info = self._batch(tok, "sampleMarkdown", {"title": title or "通知", "text": text or ""}, userid)
        if ok:
            logger.info(f"[钉钉单聊] Markdown[{title}] → {userid} OK")
            return {"success": True, "info": info}
        return {"success": False, "error": f"发送失败: {info}"}

    def send_file(self, file_path: str, userid: str) -> Dict:
        """单聊发文件（Excel/PDF/图片等常见格式都支持）"""
        prep = self._check_ready(userid, file_path=file_path)
        if prep: return prep

        # 只获取一次新版 accessToken；上传旧版媒体接口与新版发送接口共用同一 Token
        tok = self._v2_token()
        if not tok: return {"success": False, "error": "获取accessToken失败"}
        media_id = self._upload(tok, file_path)
        if not media_id: return {"success": False, "error": "上传文件失败"}

        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower().lstrip('.') or 'file'
        ok, info = self._batch(tok, "sampleFile", {
            "mediaId": media_id, "fileName": fname, "fileType": ext,
        }, userid)
        if ok:
            logger.info(f"[钉钉单聊] 文件 {fname} → {userid} OK")
            return {"success": True, "info": info}
        return {"success": False, "error": f"发送失败: {info}"}

    def send_group_text(self, content: str, open_conversation_id: str, robot_code: str = "") -> Dict:
        """向指定群发送纯文本；该服务端接口暂不支持 @。"""
        prep = self._check_group_ready(open_conversation_id, robot_code)
        if prep: return prep
        tok = self._v2_token()
        if not tok: return {"success": False, "error": "获取accessToken失败"}
        ok, info = self._group_send(
            tok, "sampleText", {"content": content or ""},
            open_conversation_id, robot_code,
        )
        if ok:
            logger.info("[钉钉群聊] 文本发送成功")
            return {"success": True, "info": info}
        return {"success": False, "error": f"发送失败: {info}"}

    def send_group_file(self, file_path: str, open_conversation_id: str, robot_code: str = "") -> Dict:
        """上传文件并向指定群发送 sampleFile 消息。"""
        prep = self._check_group_ready(open_conversation_id, robot_code, file_path)
        if prep: return prep
        tok = self._v2_token()
        if not tok: return {"success": False, "error": "获取accessToken失败"}
        media_id = self._upload(tok, file_path)
        if not media_id: return {"success": False, "error": "上传文件失败"}
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower().lstrip('.') or 'file'
        ok, info = self._group_send(
            tok, "sampleFile",
            {"mediaId": media_id, "fileName": fname, "fileType": ext},
            open_conversation_id, robot_code,
        )
        if ok:
            logger.info(f"[钉钉群聊] 文件 {fname} 发送成功")
            return {"success": True, "info": info}
        return {"success": False, "error": f"发送失败: {info}"}

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _check_ready(self, userid: str, file_path: str = None) -> Optional[Dict]:
        if not self.enabled:
            return {"success": False, "error": "单聊机器人未配置(delivery.dingtalk.app_key + app_secret)"}
        if not (userid or "").strip():
            return {"success": False, "error": "缺少接收人 dingtalk_userid（单聊必须指定具体人）"}
        if file_path and not os.path.exists(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}
        return None

    def _check_group_ready(self, open_conversation_id: str, robot_code: str = "", file_path: str = None) -> Optional[Dict]:
        if not self.enabled:
            return {"success": False, "error": "机器人未配置(delivery.dingtalk.app_key + app_secret)"}
        if not (open_conversation_id or "").strip():
            return {"success": False, "error": "缺少 open_conversation_id"}
        if not ((robot_code or self.robot_code) or "").strip():
            return {"success": False, "error": "缺少 robot_code（不能用 AppKey 代替）"}
        if file_path and not os.path.exists(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}
        return None

    # --- token（统一使用新版接口获取，并在实例内线程安全缓存）---
    def _v2_token(self) -> Optional[str]:
        now = time.time()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token

        with self._token_lock:
            now = time.time()
            if self._access_token and now < self._access_token_expires_at:
                return self._access_token

            try:
                r = requests.post(
                    "https://api.dingtalk.com/v1.0/oauth2/accessToken",
                    json={"appKey": self.app_key, "appSecret": self.app_secret},
                    timeout=self.timeout,
                )
            except Exception as e:
                logger.error(f"v2 token 网络错误: {e}"); return None
            if r.status_code != 200:
                logger.error(f"v2 token HTTP {r.status_code}: {r.text}"); return None

            try:
                body = r.json()
            except Exception:
                logger.error(f"v2 token 响应不是合法JSON: {r.text[:200]}")
                return None

            tok = body.get("accessToken")
            if not tok:
                logger.error(f"v2 token 返回空: {r.text}")
                return None

            try:
                expire_in = max(int(body.get("expireIn") or 7200), 1)
            except (TypeError, ValueError):
                expire_in = 7200
            refresh_margin = min(self._token_refresh_margin, max(expire_in // 10, 1))
            self._access_token = tok
            self._access_token_expires_at = time.time() + max(expire_in - refresh_margin, 1)
            return tok

    # --- 上传 / 发送 ---
    def _upload(self, access_token: str, file_path: str) -> Optional[str]:
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower()
        mime = _MIME.get(ext, "application/octet-stream")
        try:
            with open(file_path, 'rb') as f:
                r = requests.post(
                    "https://oapi.dingtalk.com/media/upload",
                    params={"access_token": access_token, "type": "file"},
                    # files 的 key 必须是 media，写 file 会报 errcode=40035
                    files={"media": (fname, f, mime)},
                    timeout=self.timeout,
                )
        except Exception as e:
            logger.error(f"上传文件网络错误: {e}"); return None
        if r.status_code != 200:
            logger.error(f"上传 HTTP {r.status_code}: {r.text}"); return None
        d = r.json()
        if d.get("errcode") != 0:
            logger.error(f"上传失败: {d}"); return None
        return d.get("media_id")

    def _batch(self, v2_tok: str, msg_key: str, msg_param: Dict, userid: str):
        """
        机器人单聊批量发送 batchSend（text/markdown/file 统一走这里）
        正确格式：Header 传 token；userIds 是数组；msgParam 是 JSON 字符串
        """
        try:
            r = requests.post(
                "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend",
                headers={"x-acs-dingtalk-access-token": v2_tok},
                json={
                    "robotCode": self.app_key,
                    "userIds": [str(userid).strip()],
                    "msgKey": msg_key,
                    "msgParam": json.dumps(msg_param, ensure_ascii=False),
                },
                timeout=self.timeout,
            )
        except Exception as e:
            return False, f"网络错误: {e}"
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text}"
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        inv = body.get("invalidStaffIdList") or []
        fc = body.get("flowControlledStaffIdList") or []
        if str(userid).strip() in inv:
            return False, f"userid无效（没安装机器人/不存在）: invalid={inv}  full={body}"
        if str(userid).strip() in fc:
            return False, f"被限流: flow={fc}  full={body}"
        return True, body

    def _group_send(self, v2_tok: str, msg_key: str, msg_param: Dict,
                    open_conversation_id: str, robot_code: str = ""):
        """企业内部应用机器人向指定群发送消息。

        注意：/v1.0/robot/groupMessages/send 暂不支持 @；需要 @ 时应使用
        SessionWebhook 或互动卡片能力，不要向本接口追加 atUserIds/atAll。
        """
        code = (robot_code or self.robot_code or "").strip()
        payload = {
            "robotCode": code,
            "openConversationId": str(open_conversation_id).strip(),
            "msgKey": msg_key,
            "msgParam": json.dumps(msg_param, ensure_ascii=False),
        }
        try:
            r = requests.post(
                "https://api.dingtalk.com/v1.0/robot/groupMessages/send",
                headers={"x-acs-dingtalk-access-token": v2_tok},
                json=payload,
                timeout=self.timeout,
            )
        except Exception as e:
            return False, f"网络错误: {e}"
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text}"
        try:
            return True, r.json()
        except Exception:
            return True, {"raw": r.text[:200]}


# ================================================================
# 构建实例：按「user_config.delivery.dingtalk -> 全局config.yaml delivery.dingtalk」优先级读
# 【只】从 delivery 节点读，绝对不去 notifications 里找。
# ================================================================

def build_robot(user_config: Dict = None) -> DingtalkRobot:
    cfg: Dict = {}
    if user_config:
        cfg = ((user_config.get("delivery") or {}).get("dingtalk") or {})

    if not cfg.get("app_key"):
        try:
            from src.core.config import get_config
            cfg = ((get_config().config_data.get("delivery") or {}).get("dingtalk") or {})
        except Exception:
            pass

    return DingtalkRobot(
        app_key=str(cfg.get("app_key") or ""),
        app_secret=str(cfg.get("app_secret") or ""),
        agent_id=str(cfg.get("agent_id") or ""),
        robot_code=str(cfg.get("robot_code") or ""),
    )
