# -*- coding: utf-8 -*-
"""
拼多多平台 API 工具（纯函数平铺，无类无注册表）

cookie_key: pdd（拼多多商家/创作者后台）

用法：
    from sdk.pdd import web_api

    data = await web_api(url, cookie_key="pdd", data={...})
"""
import json

from sdk.http import pfetch

HEADERS = {
    "content-type": "application/json;charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
    "Referer": "https://live.pinduoduo.com/",
}


def is_expired(status: int, text: str) -> bool:
    """
    PDD登录失效特征：
    - HTTP 401 / 302 / 403
    - 响应含 'login' / '登录' / '认证失败'
    - 特定错误码 1001/1002/1003
    """
    if status in (401, 302, 403):
        return True
    low_text = text.lower()[:800]
    if "login" in low_text or "登录" in text[:200] or "认证失败" in text:
        return True
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            err_no = result.get("error") or result.get("err_no") or result.get("code")
            if err_no and str(err_no) in ("1001", "1002", "1003"):
                return True
    except Exception:
        pass
    return False


async def web_api(url, cookie_key, method="POST", params=None, data=None,
                  headers=None, timeout=30) -> dict:
    """拼多多网页接口（cookie认证），失效抛 CookieExpiredError"""
    return await pfetch(
        url, cookie_key=cookie_key, method=method, params=params, data=data,
        headers={**HEADERS, **(headers or {})},
        is_expired=is_expired, timeout=timeout,
    )
