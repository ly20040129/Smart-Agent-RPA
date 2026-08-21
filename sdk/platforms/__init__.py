# -*- coding: utf-8 -*-
"""
平台工具类基础架构

每个平台一个工具类，封装 Cookie管理 + API调用 + 失效刷新
- official_api(): 官方开放平台接口（需app_key/app_secret签名，无需cookie）
- web_api():      非官方网页接口（用cookie，自动失效检测+刷新）
- @register_platform 自动注册，新增平台只加文件不改核心代码
"""
import sys
from pathlib import Path
import pkgutil
import importlib
import asyncio
import aiohttp
from typing import Optional, Dict, Any, List

# 确保项目根目录在 path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sdk.cookie_manager import cookie_manager

# 平台注册表
_PLATFORMS = {}


def register_platform(name: str):
    """
    平台注册装饰器

    用法：
        @register_platform("jd")
        class JDPlatform(PlatformBase):
            ...
    """
    def decorator(cls):
        cls.platform_name = name
        _PLATFORMS[name] = cls()
        return cls
    return decorator


def get_platform(name: str):
    """获取已注册的平台工具类实例"""
    return _PLATFORMS.get(name)


def list_platforms():
    """列出所有已注册的平台 {name: instance}"""
    return dict(_PLATFORMS)


def init_platforms():
    """
    启动时自动扫描 sdk/platforms/ 下所有模块并注册

    在应用启动时调用：
        from sdk.platforms import init_platforms
        init_platforms()
    """
    import sdk.platforms as pkg
    for _, mod_name, _ in pkgutil.iter_modules(pkg.__path__):
        if mod_name.startswith("_"):
            continue
        try:
            importlib.import_module(f"sdk.platforms.{mod_name}")
        except Exception as e:
            print(f"[Platforms] 加载 {mod_name} 失败: {e}")
    print(f"[Platforms] 已注册 {len(_PLATFORMS)} 个平台: {list(_PLATFORMS.keys())}")


class CookieExpiredError(Exception):
    """Cookie失效异常，提示需要刷新"""
    pass


class PlatformBase:
    """平台工具类基类：子类需实现 root_domain、default_headers、_is_expired、_sign_official"""

    platform_name: str = ""       # 平台名（装饰器自动设置）
    root_domain: str = ""        # 根域名，用于过滤cookie，如 ".jd.com"
    default_headers: Dict = {}   # 非官方API默认请求头
    official_gateway: str = ""   # 官方API网关，空=不支持官方接口

    # ==================== Cookie 管理 ====================

    def get_cookie(self, cookie_key: str) -> List[Dict]:
        """获取cookie列表"""
        return cookie_manager.load(cookie_key) or []

    def get_cookie_header(self, cookie_key: str) -> str:
        """获取cookie字符串（HTTP Cookie header格式）"""
        cookies = self.get_cookie(cookie_key)
        if not cookies:
            return ""
        # 只保留本平台域名的cookie
        domain_cookies = [c for c in cookies if self.root_domain in c.get("domain", "")]
        if not domain_cookies:
            # fallback: 返回全部
            domain_cookies = cookies
        return "; ".join(f"{c['name']}={c['value']}" for c in domain_cookies)

    def is_cookie_valid(self, cookie_key: str) -> bool:
        """检查cookie是否有效"""
        return cookie_manager.ensure_valid(cookie_key)

    async def refresh_cookie(self, cookie_key: str, timeout: int = 300) -> bool:
        """触发浏览器登录刷新cookie，返回是否成功"""
        from sdk.browser_sdk import Browser

        login_url = cookie_manager.get_login_url(cookie_key)
        if not login_url:
            print(f"[{self.platform_name}] 未配置login_url: {cookie_key}")
            return False

        try:
            async with Browser(cookie_key=cookie_key, headless=False) as b:
                await b.open(login_url)
                print(f"[{self.platform_name}] 浏览器已打开，等待登录: {cookie_key}")
                success = await b.wait_login_auto(timeout=timeout, interval=3)
                if success:
                    print(f"[{self.platform_name}] Cookie刷新成功: {cookie_key}")
                else:
                    print(f"[{self.platform_name}] Cookie刷新超时: {cookie_key}")
                return success
        except Exception as e:
            print(f"[{self.platform_name}] Cookie刷新失败: {e}")
            return False

    # ==================== 官方API（开放平台，签名认证，无需cookie） ====================

    async def official_api(
        self, action: str, app_key: str, app_secret: str,
        params: Optional[Dict] = None, method: str = "POST",
        extra_sys: Optional[Dict] = None,
    ) -> dict:
        """官方开放平台接口调用：用app_key/app_secret签名，不依赖cookie"""
        if not self.official_gateway:
            raise NotImplementedError(f"[{self.platform_name}] 未配置official_gateway")

        from datetime import datetime
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
        all_params["sign"] = self._sign_official(all_params, app_secret)

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method.upper(), self.official_gateway,
                data=all_params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                return self._parse_json(await resp.text())

    def _sign_official(self, params: Dict, app_secret: str) -> str:
        """官方API签名算法，子类按平台规则实现"""
        raise NotImplementedError(f"[{self.platform_name}] 未实现 _sign_official()")

    # ==================== 非官方API（网页接口，cookie认证，自动失效检测+刷新） ====================

    async def web_api(
        self,
        url: str,
        cookie_key: str,
        method: str = "GET",
        params: Dict = None,
        data: Any = None,
        headers: Dict = None,
        auto_refresh: bool = True,
    ) -> dict:
        """非官方网页API调用：自动注入cookie，失效时检测+刷新+重试一次"""
        result = await self._do_request(url, cookie_key, method, params, data, headers)
        resp, text = result

        # 检测cookie失效
        if self._is_expired(resp, text):
            print(f"[{self.platform_name}] Cookie失效: {cookie_key}")
            cookie_manager.delete(cookie_key)

            if auto_refresh:
                # 触发浏览器刷新
                refreshed = await self.refresh_cookie(cookie_key)
                if refreshed:
                    # 刷新成功，重试一次
                    print(f"[{self.platform_name}] Cookie已刷新，重试API...")
                    result = await self._do_request(url, cookie_key, method, params, data, headers)
                    resp, text = result
                    if not self._is_expired(resp, text):
                        return self._parse_json(text)
                    # 重试后仍然失效
                    raise CookieExpiredError(
                        f"[{self.platform_name}] 刷新后仍然失效，请检查: {cookie_key}"
                    )
            else:
                raise CookieExpiredError(
                    f"[{self.platform_name}] Cookie已失效，请去Web界面刷新: {cookie_key}"
                )

        return self._parse_json(text)

    async def _do_request(self, url, cookie_key, method, params, data, headers):
        """执行HTTP请求"""
        cookie_header = self.get_cookie_header(cookie_key)
        if not cookie_header:
            raise CookieExpiredError(
                f"[{self.platform_name}] 无可用Cookie: {cookie_key}"
            )

        # 合并请求头
        final_headers = dict(self.default_headers)
        final_headers["cookie"] = cookie_header
        if headers:
            final_headers.update(headers)

        async with aiohttp.ClientSession() as session:
            method_upper = method.upper()
            async with session.request(
                method_upper, url,
                params=params, data=data, headers=final_headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                text = await resp.text()
                return resp, text

    def _is_expired(self, resp, text: str) -> bool:
        """判断响应是否表示cookie失效，子类必须实现"""
        raise NotImplementedError("子类必须实现 _is_expired()")

    def _parse_json(self, text: str) -> dict:
        """解析JSON响应"""
        import json
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}
