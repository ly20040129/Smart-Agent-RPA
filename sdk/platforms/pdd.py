# -*- coding: utf-8 -*-
"""
拼多多平台工具类

封装拼多多商家后台的Cookie管理 + API调用 + 失效刷新

官方 vs 非官方（参考 dj_new_server 的分离模式）：
- official_api(): 拼多多开放平台接口，client_id/client_secret签名，无需cookie
- web_api():      拼多多商家后台网页接口，用cookie + 网页请求头
"""
import hashlib
import hmac
import json
from typing import Dict

from sdk.platforms import register_platform, PlatformBase


@register_platform("pdd")
class PDDPlatform(PlatformBase):
    """拼多多平台：Cookie管理 + 官方API + 非官方API + 失效刷新"""

    platform_name = "pdd"
    root_domain = ".pdd.com"  # 拼多多主域名，cookie可能也在.yangkeduo.com下

    # 拼多多开放平台官方网关
    official_gateway = "https://gw-api.pinduoduo.com/api/router"

    default_headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    }

    def _sign_official(self, params: Dict, app_secret: str) -> str:
        """
        拼多多开放平台签名算法（HMAC-SHA256）

        规则：
        1. 所有参数按key升序排序
        2. 拼接：key1value1key2value2...
        3. HMAC-SHA256(拼接串, app_secret) → 十六进制小写
        """
        sorted_keys = sorted(params.keys())
        sign_str = "".join(
            f"{k}{params[k]}" for k in sorted_keys if k != "sign"
        )
        return hmac.new(
            app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _is_expired(self, resp, text: str) -> bool:
        """
        检测拼多多API响应是否表示cookie失效

        PDD失效特征：
        - HTTP 401/302
        - 响应含 'login' 或 '登录'
        - 返回特定错误码
        """
        if resp.status in (401, 302, 403):
            return True
        low_text = text.lower()[:800]
        if "login" in low_text or "登录" in text[:200] or "认证失败" in text:
            return True
        # 检查PDD特有错误响应
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                err_no = result.get("error") or result.get("err_no") or result.get("code")
                if err_no and str(err_no) in ("1001", "1002", "1003"):
                    return True
        except Exception:
            pass
        return False
