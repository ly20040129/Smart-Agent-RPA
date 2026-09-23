# -*- coding: utf-8 -*-
"""
京东平台 API 工具（参照 dj_new_server jdTools 模式：官方 / 非官方两条路，各一个入口）

官方接口 official_api：京东开放平台网关，app_key/app_secret 签名，不依赖cookie
非官方接口 web_api：   网页接口，cookie认证（自动域过滤+失效检测）
                       平台通用头内置；子平台特殊头（如商智的设备指纹）调用处传 headers 覆盖

cookie_key 对照：
    jd_shop_ibay    京麦（艾贝自营仓导出）
    jd_shangzhi     京东商智
    jd_shop         京东商城后台
同一账号核心cookie（pin/thor）在 .jd.com 域下通用，不同账号各用各的key。

用法：
    from sdk.jd import web_api, fetch_paged

    # 任何京东网页接口——cookie过滤、p-pin、设备指纹全自动，只传url和参数
    data = await web_api(url, cookie_key="jd_shangzhi", method="GET", params={...})
    data = await web_api(url, cookie_key="jd_shop_ibay", data='[{"bizType":"4"}]')

    # 官方开放平台
    data = await official_api(action, app_key, app_secret, params)
"""
import asyncio
import hashlib
import json
from datetime import datetime

from sdk.http import pfetch

# 京东网页接口通用头（京麦 vcnew 等）
HEADERS = {
    "content-type": "application/json;charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
    "Referer": "https://vcnew.jd.com/",
    "Origin": "https://vcnew.jd.com",
}


def is_expired(status: int, text: str) -> bool:
    """
    京东API登录失效特征：
    - HTTP 401 / 302
    - 响应前500字符含 'login'
    - success=false 且提示登录
    """
    if status in (401, 302):
        return True
    if "login" in text.lower()[:500]:
        return True
    try:
        result = json.loads(text)
        if isinstance(result, dict) and result.get("success") is False:
            msg = str(result.get("message", "")) + str(result.get("msg", ""))
            if "登录" in msg or "login" in msg.lower():
                return True
    except Exception:
        pass
    return False


# ================================================================
# 自动头：web_api 自动注入，调用处不用管
#   cookie：domain=.jd.com 域过滤（全量会超网关上限 400）
#   p-pin：账号名URL编码，从cookie的pin取（京东通用惯例，换账号自动跟）
# 复制fetch时headers里带的 cookie / p-pin 会被自动忽略替换，其他头原样生效
# ================================================================

def _auto_headers(cookie_key: str) -> dict:
    from sdk.cookie_manager import cookie_manager

    pin = ""
    for c in cookie_manager.load(cookie_key):
        if c.get("name") == "pin" and c.get("value"):
            pin = c["value"]
            break
    return {"p-pin": pin} if pin else {}


# 复制fetch带来的、由web_api自动管理的头（调用处的值会被忽略）
_SKIP_COPIED = {"cookie", "p-pin"}


def _from_fetch_opts(opts: dict) -> dict:
    """把fetch第二参数（{headers, body, method}）翻译成请求参数"""
    headers = {k: v for k, v in (opts.get("headers") or {}).items()
               if k.lower() not in _SKIP_COPIED}
    body = opts.get("body")
    return {
        "method": (opts.get("method") or "GET").upper(),
        "data": body if body not in (None, "") else None,
        "headers": headers,
    }


# ==================== 非官方接口（网页接口，cookie认证）====================

async def web_api(url, opts=None, cookie_key=None, method=None, params=None,
                  data=None, headers=None, timeout=30) -> dict:
    """
    京东网页接口（cookie认证），失效抛 CookieExpiredError。

    两种用法：

    ① 复制fetch直贴（推荐）——JS的fetch(url, {...})第二参数原样传进来：
        await web_api(
            "https://sz.jd.com/sz/api/xxx.ajax?date=2026-09-22&...",
            {
                "headers": {"accept": "...", "user-mnp": "...", ...},  # 原样粘贴
                "body": None,                                            # 原样粘贴
                "method": "GET",                                         # 原样粘贴
            },
            cookie_key="jd_shangzhi",
        )
        headers里的 cookie/p-pin 自动忽略（换成最新的），其余头原样生效。

    ② 关键字参数（程序化构造请求时用）：
        await web_api(url, cookie_key, method="GET", params={...}, headers={...})

    自动注入：.jd.com 域过滤cookie + p-pin。
    """
    from sdk.cookie_manager import cookie_manager

    # 复制fetch风格：opts 优先；程序化风格：关键字参数
    if isinstance(opts, dict):
        f = _from_fetch_opts(opts)
        method = f["method"]
        data = f["data"]
        headers = {**f["headers"], **(headers or {})}
    method = method or "POST"

    cookie_str = "; ".join(
        f"{c['name']}={c['value']}"
        for c in cookie_manager.load(cookie_key)
        if c.get("domain") == ".jd.com" and c.get("name") and c.get("value")
    )
    if not cookie_str:
        from sdk.http import CookieExpiredError
        raise CookieExpiredError(f"无可用Cookie: {cookie_key}（请先在Web界面登录）")

    # 请求头直塞 cookie，绕过 pfetch 的全量注入；动态头（p-pin/指纹）自动注入
    final_headers = {**HEADERS, **_auto_headers(cookie_key),
                     **(headers or {}), "cookie": cookie_str}

    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.request(
            method.upper(), url, params=params, data=data,
            headers=final_headers, timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            text = await resp.text()

    if is_expired(resp.status, text):
        from loguru import logger
        from sdk.http import CookieExpiredError
        logger.warning(f"[JD] Cookie失效: {cookie_key} ({url})")
        cookie_manager.delete(cookie_key)
        raise CookieExpiredError(f"Cookie已失效，请去Web界面刷新: {cookie_key}")

    cookie_manager.refresh_ttl(cookie_key)
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


async def fetch_paged(url, cookie_key, body_template,
                      date_field="refDateFrom", date_to_field="refDateTo",
                      page_size=1000, date_from="", date_to="",
                      progress_callback=None) -> list:
    """
    分页拉取京东数据（通用分页逻辑）。

    京东API的分页模式：
    - POST，请求体是JSON数组：[{...page, pageSize, 日期}]
    - 返回 {success: true, data: {list: [...], total: N}}
    """
    all_data = []
    page = 1
    total = 0

    while True:
        body = dict(body_template)
        body["pageSize"] = page_size
        body["page"] = page
        if date_from:
            body[date_field] = f"{date_from} 00:00:00"
        if date_to:
            body[date_to_field] = f"{date_to} 23:59:59"

        result = await web_api(url=url, cookie_key=cookie_key, data=json.dumps([body]))

        if not isinstance(result, dict) or result.get("success") is False:
            raise RuntimeError(f"API返回失败: {json.dumps(result, ensure_ascii=False)[:200]}")

        data = result.get("data", {})
        rows = data.get("list") or data.get("rows") or []
        total = data.get("total", 0)

        if not rows:
            break

        all_data.extend(rows)

        if progress_callback:
            progress_callback(3, f"第{page}页获取 {len(rows)} 条，累计 {len(all_data)}/{total}")

        if len(all_data) >= total or len(rows) < page_size:
            break

        page += 1
        await asyncio.sleep(2)  # 防风控

    return all_data


# ==================== 官方接口（开放平台，签名认证，无需cookie）====================

OFFICIAL_GATEWAY = "https://api.jd.com/routerjson"


def _sign_official(params: dict, app_secret: str) -> str:
    """
    京东开放平台签名（MD5）：
    参数按key升序 → app_secret + k1v1 + k2v2 + ... + app_secret → MD5 大写
    """
    sign_str = app_secret + "".join(
        f"{k}{params[k]}" for k in sorted(params) if k != "sign"
    ) + app_secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


async def official_api(action: str, app_key: str, app_secret: str,
                        params: dict = None, method: str = "POST",
                        extra_sys: dict = None, timeout=30) -> dict:
    """京东开放平台接口（app_key/app_secret签名，不依赖cookie）"""
    import aiohttp

    sys_params = {
        "app_key": app_key,
        "method": action,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "1.0",
        "sign_method": "md5",
    }
    if extra_sys:
        sys_params.update(extra_sys)

    all_params = {**sys_params, **(params or {})}
    all_params["sign"] = _sign_official(all_params, app_secret)

    async with aiohttp.ClientSession() as session:
        async with session.request(
            method.upper(), OFFICIAL_GATEWAY,
            data=all_params,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            text = await resp.text()

    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}
