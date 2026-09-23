# -*- coding: utf-8 -*-
"""
微信支付（公众号商户平台）API 工具（纯函数平铺，无类无注册表）

cookie_key: wechat_pay

用法：
    from sdk.wechat_pay import web_api

    data = await web_api(url, cookie_key="wechat_pay", data={...})
"""
import json

from sdk.http import pfetch

HEADERS = {
    "content-type": "application/json;charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
    "Referer": "https://pay.weixin.qq.com/",
}


def is_expired(status: int, text: str) -> bool:
    """
    微信支付登录失效特征：
    - HTTP 401 / 302 / 403
    - 响应含 'login' / 登录跳转特征
    - ret_code 表示会话失效
    """
    if status in (401, 302, 403):
        return True
    low_text = text.lower()[:500]
    if "login" in low_text or "请登录" in text[:200]:
        return True
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            ret_code = result.get("ret_code")
            if ret_code and str(ret_code) in ("-1", "10001", "10010"):
                return True
    except Exception:
        pass
    return False


async def web_api(url, cookie_key, method="POST", params=None, data=None,
                  headers=None, timeout=30) -> dict:
    """微信支付网页接口（cookie认证），失效抛 CookieExpiredError"""
    return await pfetch(
        url, cookie_key=cookie_key, method=method, params=params, data=data,
        headers={**HEADERS, **(headers or {})},
        is_expired=is_expired, timeout=timeout,
    )
