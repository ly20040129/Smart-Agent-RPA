# -*- coding: utf-8 -*-
"""
钉钉多维表工具类

直接用工作表名称操作，不需要查 sheet_id。
传入 userId（纯数字）自动转 unionId。

凭证：app_key + app_secret，复用 delivery.dingtalk 配置（与单聊机器人同一个自建应用）

用法：
    from sdk.dingtalk_ai_table import DingTalkAITable

    table = DingTalkAITable(operator_id="your_userid")
    records = table.list_records(base_id="your_base_id", sheet_name="数据表1")
    table.update_records(base_id="your_base_id", sheet_name="数据表1", records=[
        {"id": "rec_xxx", "fields": {"状态": "已上传"}}
    ])
"""
import time
import uuid
from typing import Dict, List, Any

import requests
from loguru import logger


class DingTalkAITable:
    _BASE_URL = "https://api.dingtalk.com/v1.0"
    _TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"

    def __init__(self, app_key: str = "", app_secret: str = "", operator_id: str = ""):
        # 凭证复用 delivery.dingtalk（与单聊机器人同一个自建应用）
        if not app_key or not app_secret:
            from src.core.config import get_config
            cfg = get_config().config_data["delivery"]["dingtalk"]
            app_key = app_key or cfg["app_key"]
            app_secret = app_secret or cfg["app_secret"]
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self._raw_operator_id = operator_id
        self.operator_id = ""
        self._token = ""
        self._token_expires_at = 0

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        resp = requests.post(
            self._TOKEN_URL,
            json={"appKey": self.app_key, "appSecret": self.app_secret},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["accessToken"]
        self._token_expires_at = time.time() + data.get("expireIn", 7200) - 60
        logger.debug(f"[AITable] token 刷新成功，有效期 {data.get('expireIn', 7200)}s")
        return self._token

    def _ensure_operator_id(self) -> str:
        if self.operator_id:
            return self.operator_id
        raw = self._raw_operator_id
        if not raw:
            raise ValueError("[AITable] operator_id 未设置")
        if raw.isdigit():
            logger.debug(f"[AITable] userId={raw} → 转换 unionId...")
            token = self._ensure_token()
            resp = requests.post(
                "https://oapi.dingtalk.com/topapi/v2/user/get",
                params={"access_token": token},
                json={"userid": raw, "language": "zh_CN"},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                if data.get("errcode") == 0:
                    self.operator_id = data["result"]["unionid"]
                    logger.info(f"[AITable] userId={raw} → unionId={self.operator_id}")
                else:
                    raise ValueError(f"userId 转 unionId 失败: {data}")
            else:
                raise ValueError(f"userId 转 unionId 失败: {resp.status_code} {resp.text}")
        else:
            self.operator_id = raw
        return self.operator_id

    def _request(self, method: str, path: str, body: Any = None, params: Dict = None) -> dict:
        token = self._ensure_token()
        operator_id = self._ensure_operator_id()
        url = f"{self._BASE_URL}{path}"
        headers = {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}
        if params and "operatorId" in params:
            params["operatorId"] = operator_id
        resp = requests.request(method, url, json=body, headers=headers, params=params, timeout=30)
        # 401 令牌过期：强制刷新 token 后重试一次
        if resp.status_code == 401:
            logger.warning(f"[AITable] 401 令牌过期，刷新 token 重试: {method} {path}")
            self._token = ""
            self._token_expires_at = 0
            token = self._ensure_token()
            headers["x-acs-dingtalk-access-token"] = token
            resp = requests.request(method, url, json=body, headers=headers, params=params, timeout=30)
        if not resp.ok:
            logger.error(f"[AITable] {method} {path} → {resp.status_code}: {resp.text}")
            resp.raise_for_status()
        return resp.json()

    # ==================== 记录操作 ====================

    def list_records(self, base_id: str, sheet_name: str, max_records: int = 20,
                     filter_conditions: Dict = None, next_token: str = None) -> dict:
        path = f"/notable/bases/{base_id}/sheets/{sheet_name}/records/list"
        params = {"operatorId": self._raw_operator_id}
        body = {"maxResults": max_records}
        if filter_conditions:
            body["filter"] = filter_conditions
        if next_token:
            body["nextToken"] = next_token
        return self._request("POST", path, body=body, params=params)

    def get_record(self, base_id: str, sheet_name: str, record_id: str) -> dict:
        path = f"/notable/bases/{base_id}/sheets/{sheet_name}/records/{record_id}"
        return self._request("GET", path, params={"operatorId": self._raw_operator_id})

    def insert_records(self, base_id: str, sheet_name: str, records: List[Dict]) -> dict:
        path = f"/notable/bases/{base_id}/sheets/{sheet_name}/records"
        body = {"records": records}
        params = {"operatorId": self._raw_operator_id, "clientToken": str(uuid.uuid4())}
        result = self._request("POST", path, body=body, params=params)
        logger.info(f"[AITable] 新增 {len(records)} 条记录 → {sheet_name}")
        return result

    def update_records(self, base_id: str, sheet_name: str, records: List[Dict]) -> dict:
        path = f"/notable/bases/{base_id}/sheets/{sheet_name}/records"
        body = {"records": records}
        params = {"operatorId": self._raw_operator_id}
        result = self._request("PUT", path, body=body, params=params)
        logger.info(f"[AITable] 更新 {len(records)} 条记录 → {sheet_name}")
        return result

    def delete_records(self, base_id: str, sheet_name: str, record_ids: List[str]) -> dict:
        path = f"/notable/bases/{base_id}/sheets/{sheet_name}/records/delete"
        body = {"recordIds": record_ids}
        params = {"operatorId": self._raw_operator_id}
        result = self._request("POST", path, body=body, params=params)
        logger.info(f"[AITable] 删除 {len(record_ids)} 条记录 → {sheet_name}")
        return result

    # ==================== 数据表操作 ====================

    def list_sheets(self, base_id: str) -> dict:
        path = f"/notable/bases/{base_id}/sheets"
        return self._request("GET", path, params={"operatorId": self._raw_operator_id})

    def get_sheet(self, base_id: str, sheet_name: str) -> dict:
        path = f"/notable/bases/{base_id}/sheets/{sheet_name}"
        return self._request("GET", path, params={"operatorId": self._raw_operator_id})
