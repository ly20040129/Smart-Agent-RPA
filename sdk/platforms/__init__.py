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
from loguru import logger

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
            logger.warning(f"[Platforms] 加载 {mod_name} 失败: {e}")
    logger.info(f"[Platforms] 已注册 {len(_PLATFORMS)} 个平台: {list(_PLATFORMS.keys())}")


class CookieExpiredError(Exception):
    """Cookie失效异常，提示需要刷新"""
    pass


class PlatformBase:
    """平台工具类基类：子类需实现 root_domain、default_headers、_is_expired、_sign_official"""

    platform_name: str = ""       # 平台名（装饰器自动设置）
    root_domain: str = ""        # 根域名，用于过滤cookie，如 ".jd.com"
    default_headers: Dict = {}   # 非官方API默认请求头
    official_gateway: str = ""   # 官方API网关，空=不支持官方接口

    # ---- Cookie 管理常量 ----
    _PROBE_CACHE_SECONDS = 8 * 3600   # 探活结果缓存8小时 ≈ 每天最多探3次
    _NOTIFY_EXPIRED_TTL = 5 * 60      # 「Cookie失效」通知5分钟内去重
    _NOTIFY_WARNING_TTL = 12 * 3600   # 「即将过期」预警12小时内去重
    _WARNING_DAYS = 7                 # TTL低于7天 → 触发即将过期预警
    _RENEW_DAYS = 30                  # 每次成功调用后续期30天
    _SKIP_PROBE_IF_NEWER_THAN_SEC = 30 * 60   # 30分钟内刚保存的cookie跳过探活（信任手动刷新成果）

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

    # ---------- 轻量探活：访问login_url验证cookie，结果缓存8小时 ----------
    async def probe_cookie(self, cookie_key: str) -> bool:
        """
        任务前轻量探活：访问 login_url 判断cookie是否真的有效。

        ⚠️ 重要：返回值只是「建议」，最终法官是 web_api 第三步的真实API + _is_expired。
        调用方收到 False 时只应该打 warning，不应该直接删 cookie / 抛异常。

        跳过探活的两种情况（直接放行返回 True）：
          A) 8 小时探活缓存命中
          B) 30 分钟内刚保存的 cookie（TTL 很接近 30 天）→ 信任手动刷新成果

        返回 False 的语义：疑似失效，建议上层留意，但不阻塞业务。
        返回 True 的语义：探活通过 / 跳过了，正常继续。
        """
        from src.storage import storage_manager

        # 0) 极新cookie（30分钟内刚保存）→ 跳过探活，信任它
        #    save_cookies 默认写 30*86400 = 2592000 秒，只要 TTL >= 2592000 - 1800 就是30分钟内
        ttl = cookie_manager.ttl(cookie_key)
        if ttl > 0 and ttl >= self._RENEW_DAYS * 86400 - self._SKIP_PROBE_IF_NEWER_THAN_SEC:
            logger.debug(f"[{self.platform_name}] Cookie <30分钟刚保存，跳过探活: {cookie_key} (TTL={ttl}s)")
            return True

        # 1) 有缓存 → 直接放行
        cache_key = f"cookie_probe_ok:{cookie_key}"
        if storage_manager.is_redis_available:
            hit = storage_manager.redis.get(cache_key)
            if hit:
                return True

        login_url = cookie_manager.get_login_url(cookie_key)
        if not login_url:
            return True  # 没配置login_url → 不拦业务，放行

        cookie_header = self.get_cookie_header(cookie_key)
        if not cookie_header:
            return False  # 没cookie → 探活失败

        try:
            headers = {"User-Agent": self.default_headers.get("User-Agent", "")}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    login_url, headers=headers, cookies=cookie_manager.load_as_dict(cookie_key),
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    # 3xx跳登录/授权 → 失效
                    if resp.status in (301, 302, 303, 307, 308):
                        loc = str(resp.headers.get("Location", "")).lower()
                        if any(k in loc for k in ("login", "passport", "auth", "signin")):
                            return False
                    if resp.status in (401, 403):
                        return False
                    # 页面片段含「未登录/请登录」→ 失效
                    text = await resp.text()
                    head = text[:500]
                    if "未登录" in head or "请登录" in head or "login required" in head.lower():
                        return False
        except Exception as e:
            # 网络异常不阻塞业务 → 放行，让真实API自己去判断
            logger.debug(f"[{self.platform_name}] 探活请求异常（放行）: {cookie_key}, {e}")
            return True

        # 探活成功 → 写缓存8小时 + 刷新TTL 30天（确认真实有效才续，防止失效cookie被反复续命）
        if storage_manager.is_redis_available:
            storage_manager.redis.set(cache_key, "1", expire=self._PROBE_CACHE_SECONDS)
        cookie_manager.refresh_ttl(cookie_key, expire_days=self._RENEW_DAYS)
        return True

    # ---------- 通知去重：返回 True=应该发，False=重复发跳过 ----------
    def _dedup_notify(self, suffix: str, cookie_key: str, ttl_seconds: int) -> bool:
        """复用 mark_submit_dedup 的 SETNX 语义做通知去重"""
        from src.storage import storage_manager
        if not storage_manager.is_redis_available:
            return True
        dedup_key = f"cookie_notify:{suffix}:{cookie_key}"
        return storage_manager.redis.mark_submit_dedup(dedup_key, "1", ttl_seconds)

    # ---------- TTL 检查：低于阈值发「即将过期」预警 ----------
    def _check_ttl_and_warn(self, cookie_key: str):
        """每次web_api前检查，TTL < 7天就发提醒（12小时内最多1次）"""
        ttl = cookie_manager.ttl(cookie_key)
        if ttl <= 0:
            return
        days_left = ttl / 86400
        if days_left >= self._WARNING_DAYS:
            return
        if not self._dedup_notify("warning", cookie_key, self._NOTIFY_WARNING_TTL):
            return
        try:
            from src.agent.dingtalk_webhook import build_webhook
            webhook = build_webhook()
            if webhook.enabled:
                webhook.send_text(
                    f"⚠️ Cookie即将过期提醒\n"
                    f"平台: {self.platform_name}\n"
                    f"Key: {cookie_key}\n"
                    f"剩余: {days_left:.1f}天\n"
                    f"建议尽快去Web界面重新登录刷新"
                )
                logger.info(f"已发送Cookie即将过期提醒: {cookie_key} ({days_left:.1f}天)")
        except Exception as e:
            logger.warning(f"发送Cookie即将过期通知失败: {e}")

    async def refresh_cookie(self, cookie_key: str, timeout: int = 300) -> bool:
        """触发浏览器登录刷新cookie，返回是否成功"""
        from sdk.browser_sdk import Browser

        login_url = cookie_manager.get_login_url(cookie_key)
        if not login_url:
            logger.warning(f"[{self.platform_name}] 未配置login_url: {cookie_key}")
            return False

        try:
            async with Browser(cookie_key=cookie_key, headless=False) as b:
                await b.open(login_url)
                logger.info(f"[{self.platform_name}] 浏览器已打开，等待登录: {cookie_key}")
                success = await b.wait_login_auto(timeout=timeout, interval=3)
                if success:
                    logger.info(f"[{self.platform_name}] Cookie刷新成功: {cookie_key}")
                else:
                    logger.warning(f"[{self.platform_name}] Cookie刷新超时: {cookie_key}")
                return success
        except Exception as e:
            logger.error(f"[{self.platform_name}] Cookie刷新失败: {e}")
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
        params: dict = None,
        data: dict = None,
        headers: dict = None,
        auto_refresh: bool = True,
    ) -> dict:
        """
        非官方网页API调用：自动注入cookie，失效时通知+抛异常（不阻塞等待登录）

        全流程（4步防护）：
          ① TTL预警检查：TTL<7天 → 发「即将过期」提醒（12小时去重）
          ② 轻量探活【建议性质】：疑似失效只打warning，不删cookie不抛异常；
             同时满足<30分钟新cookie或8h缓存命中→直接跳过探活
          ③ 真实API请求 + 响应过期检测【最终法官】
          ④ 成功调用：TTL续期30天（从这一刻起算）

        cookie过期时处理（只有真实API检测才会触发）：
          1. 删除失效cookie
          2. 发送钉钉通知（5分钟去重）
          3. 抛出 CookieExpiredError，由上层任务捕获处理
        """
        # ① 先看TTL：低于阈值发即将过期提醒（此时cookie还没被load续期，看到的是真实TTL）
        self._check_ttl_and_warn(cookie_key)

        # ② 轻量探活【只是建议，不当法官】→ 返回False只打warning，仍继续调真实API
        #    （探活请求可能被导出页/CSRF误判，最终以真实 API 的 _is_expired 为准）
        probe_ok = await self.probe_cookie(cookie_key)
        if not probe_ok:
            logger.warning(
                f"[{self.platform_name}] Cookie探活疑似失效（不删cookie，继续用真实API验证）: "
                f"{cookie_key}"
            )

        # ③ 真实API请求 + 过期检测【最终法官：只有这里判定过期才会删+通知+抛异常】
        result = await self._do_request(url, cookie_key, method, params, data, headers)
        resp, text = result

        if self._is_expired(resp, text):
            logger.warning(f"[{self.platform_name}] Cookie失效(API响应检测): {cookie_key}")
            cookie_manager.delete(cookie_key)
            if auto_refresh:
                self._notify_cookie_expired(cookie_key)
            raise CookieExpiredError(
                f"[{self.platform_name}] Cookie已失效，请去Web界面刷新: {cookie_key}"
            )

        # ④ 成功调用 → 从这一刻起TTL续期30天
        cookie_manager.refresh_ttl(cookie_key, expire_days=self._RENEW_DAYS)
        return self._parse_json(text)

    def _notify_cookie_expired(self, cookie_key: str):
        """Cookie失效时发送钉钉通知（5分钟内同一key只发一次，避免重复刷屏）"""
        # 去重：5分钟内发过就跳过
        if not self._dedup_notify("expired", cookie_key, self._NOTIFY_EXPIRED_TTL):
            logger.debug(f"Cookie失效通知去重（5分钟内已发过，跳过）: {cookie_key}")
            return
        try:
            from src.agent.dingtalk_webhook import build_webhook
            webhook = build_webhook()
            if webhook.enabled:
                webhook.send_text(
                    f"⚠️ Cookie失效提醒\n平台: {self.platform_name}\nKey: {cookie_key}\n请去Web界面刷新Cookie"
                )
                logger.info(f"已发送钉钉Cookie失效通知: {cookie_key}")
        except Exception as e:
            logger.warning(f"发送Cookie失效通知失败: {e}")

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
