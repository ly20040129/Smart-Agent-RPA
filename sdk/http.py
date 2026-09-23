# -*- coding: utf-8 -*-
"""
HTTP 请求工具（对标 dj_new_server 的 mtTools.pfetch）

职责三件事，从头读到尾就是全部逻辑：
  1. 从 cookie_manager 取 cookie 注入请求头
  2. 发请求，解析 JSON 返回
  3. 响应判定为登录失效 → 删cookie + 抛 CookieExpiredError

cookie 失效后怎么处理（通知/重试/更新状态）写在 workflow 里，
不藏在这里 —— 出了问题看 workflow 就够了。

用法：
    from sdk.jd import web_api

    data = await web_api(
        url="https://vcf.jd.com/api/finance/saleBill/list",
        cookie_key="jd_shop_ibay",
        data='[{"bizType":"4","page":1}]',
    )
"""
import json
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import aiohttp
from loguru import logger

from sdk.cookie_manager import cookie_manager

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")


class CookieExpiredError(Exception):
    """Cookie失效（无cookie或响应被判定为未登录）"""


async def pfetch(url, cookie_key=None, method="GET", params=None, data=None,
                 headers=None, is_expired=None, timeout=30) -> dict:
    """
    带 cookie 的网页 API 请求。

    Args:
        is_expired: 平台失效判定函数 is_expired(status, text)，
                    返回 True 则删cookie并抛 CookieExpiredError（见 sdk/jd.py 等）
    Returns:
        解析后的 JSON（非JSON响应返回 {"raw": 原文}）
    """
    final_headers = {
        "accept": "application/json, text/plain, */*",
        "User-Agent": UA,
    }
    if headers:
        final_headers.update(headers)

    if cookie_key:
        cookie_header = cookie_manager.load_as_string(cookie_key)
        if not cookie_header:
            raise CookieExpiredError(f"无可用Cookie: {cookie_key}（请先在Web界面登录）")
        final_headers["cookie"] = cookie_header

    async with aiohttp.ClientSession() as session:
        async with session.request(
            method.upper(), url,
            params=params, data=data, headers=final_headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            text = await resp.text()

    if is_expired and is_expired(resp.status, text):
        logger.warning(f"[HTTP] Cookie失效: {cookie_key} ({url})")
        if cookie_key:
            cookie_manager.delete(cookie_key)
        raise CookieExpiredError(f"Cookie已失效，请去Web界面刷新: {cookie_key}")

    # 成功调用 → TTL 续期30天
    if cookie_key:
        cookie_manager.refresh_ttl(cookie_key)

    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


async def notify_expired(cookie_key: str):
    """Cookie失效钉钉通知（workflow 里按需调用，不自动发）"""
    try:
        from sdk.dingtalk_webhook import build_webhook
        webhook = build_webhook()
        if webhook.enabled:
            webhook.send_text(f"⚠️ Cookie失效: {cookie_key}\n请去Web界面重新登录")
            logger.info(f"已发送Cookie失效通知: {cookie_key}")
    except Exception as e:
        logger.warning(f"发送Cookie失效通知失败: {e}")
