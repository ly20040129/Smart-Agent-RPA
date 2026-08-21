# -*- coding: utf-8 -*-
"""
京东平台工具类

封装京东所有子平台（京麦、商智、商城等）的通用操作：
- Cookie管理（按cookie_key加载，过滤.jd.com域名）
- 非官方API调用（网页接口，自动注入cookie + 失效检测 + 自动刷新）→ web_api()
- 官方API调用（京东开放平台，app_key/app_secret签名）→ official_api()

官方 vs 非官方（参考 dj_new_server 的 jdFetch / pfetch 分离模式）：
- official_api(): 走京东开放平台网关，签名认证，不依赖cookie
- web_api():      直接调京东网页后台接口，用cookie + 网页请求头

子平台说明：
- 京东京麦: cookie_key = "jd_shop_ibay" / "jd_shop_账号B"
- 京东商智: cookie_key = "jd_shangzhi"
- 京东商城: cookie_key = "jd_shop"

同一京东账号的核心cookie（pin/thor等）设在 .jd.com 域名下，各子平台通用。
不同账号需要各自的cookie_key。
"""
import hashlib
import json
import aiohttp
from typing import Dict, Any, Optional

from sdk.platforms import register_platform, PlatformBase, CookieExpiredError


@register_platform("jd")
class JDPlatform(PlatformBase):
    """京东平台：统一封装Cookie + 官方API + 非官方API + 失效刷新"""

    platform_name = "jd"
    root_domain = ".jd.com"

    # 京东开放平台官方网关
    official_gateway = "https://api.jd.com/routerjson"

    # 京东网页API（非官方）通用请求头
    default_headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "Referer": "https://vcnew.jd.com/",
        "Origin": "https://vcnew.jd.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    }

    def _sign_official(self, params: Dict, app_secret: str) -> str:
        """
        京东开放平台签名算法（MD5）

        规则：
        1. 所有参数按key升序排序
        2. 拼接：app_secret + key1value1 + key2value2 + ... + app_secret
        3. MD5后转大写
        """
        sorted_keys = sorted(params.keys())
        sign_str = app_secret + "".join(
            f"{k}{params[k]}" for k in sorted_keys if k != "sign"
        ) + app_secret
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    def _is_expired(self, resp, text: str) -> bool:
        """
        检测京东API响应是否表示cookie失效

        京东API失效特征：
        - HTTP 401（未授权）
        - HTTP 302（重定向到登录页）
        - 响应前500字符包含 'login'
        - success字段为false且提示登录
        """
        if resp.status == 401 or resp.status == 302:
            return True
        if "login" in text.lower()[:500]:
            return True
        # 检查JSON响应中的success字段
        try:
            result = json.loads(text)
            if isinstance(result, dict) and result.get("success") is False:
                msg = str(result.get("message", "") + result.get("msg", ""))
                if "登录" in msg or "login" in msg.lower():
                    return True
        except Exception:
            pass
        return False

    async def fetch_paged(
        self,
        url: str,
        cookie_key: str,
        body_template: Dict,
        date_field: str = "refDateFrom",
        date_to_field: str = "refDateTo",
        page_size: int = 1000,
        date_from: str = "",
        date_to: str = "",
        auto_refresh: bool = True,
        progress_callback=None,
    ) -> list:
        """
        分页获取京东API数据（通用分页逻辑）

        京东API的分页模式：
        - POST请求，body是JSON数组
        - 返回 {success: true, data: {list: [...], total: N}}

        Args:
            url: API地址
            cookie_key: cookie标识
            body_template: 请求体模板（会自动注入page/pageSize/日期）
            page_size: 每页条数
            date_from: 开始日期
            date_to: 结束日期
            auto_refresh: cookie失效时自动刷新
            progress_callback: 进度回调 callback(step, message)
        Returns:
            所有页的数据列表
        """
        all_data = []
        page = 1
        total = 0

        while True:
            if progress_callback:
                progress_callback(2, f"正在获取第{page}页数据...")

            # 构造请求体
            body = dict(body_template)
            body["pageSize"] = page_size
            body["page"] = page
            if date_from:
                body[date_field] = f"{date_from} 00:00:00"
            if date_to:
                body[date_to_field] = f"{date_to} 23:59:59"

            result = await self.web_api(
                url=url,
                cookie_key=cookie_key,
                method="POST",
                data=json.dumps([body]),
                auto_refresh=auto_refresh,
            )

            # 解析响应
            if not isinstance(result, dict) or result.get("success") is False:
                raise RuntimeError(f"API返回失败: {json.dumps(result, ensure_ascii=False)[:200]}")

            data = result.get("data", {})
            rows = data.get("list") or data.get("rows") or []
            total = data.get("total", 0)

            if not rows:
                break

            all_data.extend(rows)

            if progress_callback:
                progress_callback(3, f"第{page}页获取 {len(rows)} 条，累计 {len(all_data)} 条/共 {total}")

            if len(all_data) >= total or len(rows) < page_size:
                break

            page += 1
            import asyncio
            await asyncio.sleep(2)  # 防风控

        return all_data
