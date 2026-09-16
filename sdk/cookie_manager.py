# -*- coding: utf-8 -*-
"""
Cookie管理器

负责：cookie的抓取、精简、存取（Redis）
支持多账号：同一平台可以有多个cookie_key（如 jd_shangzhi_店铺A、jd_shangzhi_店铺B）

流程：
  浏览器任务 → start()从Redis读cookie注入 → close()时检测已登录才抓取存回
  API任务    → load()读cookie → 调API → 过期了报错让用户去Web界面刷新
  Web界面    → 点"刷新"按钮 → 打开浏览器登录 → 自动存Redis
"""
import sys
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.storage import storage_manager

_PREFIX = "agent:cookies:"


class CookieManager:
    """Cookie管理器"""

    # 每个平台的核心cookie名 + 登录页URL
    # 核心cookie：登录后才有的cookie，用来判断是否已登录
    PLATFORM_CONFIG: Dict[str, Dict] = {
        "wechat_pay": {
            "login_url": "https://pay.weixin.qq.com/index.php/core/home",
            "cookie_domain": "weixin.qq.com",
            "core_cookies": ["session_key", "verifysession", "merchant_id", "g_ticket"],
            "critical_cookie": "session_key",
            "success_signals": ["退出", "logout", "商户号", "微信支付"],
        },
        "jd_shop": {
            "login_url": "https://passport.jd.com/new/login.aspx",
            "cookie_domain": "jd.com",
            "core_cookies": ["pin", "thor", "pinId", "_pst"],
            "critical_cookie": "thor",
            "success_signals": ["退出", "注销", "商家中心", "我的店铺", "shop.jd.com"],
        },
        "jd_shop_ibay": {
            "login_url": "https://shop.jd.com/jdm/trade/tools/export/ExrotList?_JDMOMID_=1568",
            "cookie_domain": "jd.com",
            "core_cookies": ["pin", "thor", "pinId", "_pst"],
            "critical_cookie": "thor",
            "success_signals": ["退出", "注销", "商家中心", "我的店铺"],
        },
        "jd_shangzhi": {
            "login_url": "https://shop.jd.com/jdm/trade/tools/export/ExrotList?_JDMOMID_=1568",
            "cookie_domain": "jd.com",
            "core_cookies": ["pin", "thor", "pinId", "_pst"],
            "critical_cookie": "thor",
            "success_signals": ["退出", "注销", "商家中心", "商智"],
        },
        "pdd": {
            "login_url": "https://live.pinduoduo.com/n-creator/video/replay-manage",
            "cookie_domain": "pinduoduo.com",
            "core_cookies": ["pdd_user_id", "L_PASS_ID", "L_PASS_TYPE", "windows_app_shop_token_23"],
            "critical_cookie": "L_PASS_ID",
            "success_signals": ["退出登录", "个人中心", "创作者", "达人"],
        },
        # 在这里添加更多平台...
        # 新增平台必选字段：login_url / cookie_domain / core_cookies
        # 新增平台可选字段：
        #   critical_cookie  - 关键鉴权cookie，值长度必须 >= 16（防 placeholder）
        #   success_signals  - 页面成功信号关键词，命中任一即认为已离开登录页
        #   verify_url       - 【可选】真试验证接口URL，命中时会发GET确认未跳登录页
    }

    # 多账号映射存在Redis的key名
    _MAP_KEY = "cookie_key_map"

    @property
    def PLATFORM_COOKIES(self) -> Dict[str, List[str]]:
        """兼容旧代码"""
        return {k: v["core_cookies"] for k, v in self.PLATFORM_CONFIG.items()}

    # ---- 平台解析（支持多账号）----

    def resolve_platform(self, key: str) -> str:
        """
        解析cookie_key对应的平台名
        例：key="jd_shangzhi" → "jd_shangzhi"
            key="jd_shangzhi_店铺A" → "jd_shangzhi"（前缀匹配）
        """
        # 直接匹配
        if key in self.PLATFORM_CONFIG:
            return key
        # Redis映射（register_cookie_key注册的）
        mapping = self._load_key_map()
        if key in mapping and mapping[key] in self.PLATFORM_CONFIG:
            return mapping[key]
        # 前缀匹配：key以"平台名_"或"平台名-"开头
        for platform in self.PLATFORM_CONFIG:
            if key.startswith(platform + "_") or key.startswith(platform + "-"):
                return platform
        return ""

    def get_login_url(self, key: str) -> str:
        platform = self.resolve_platform(key)
        return self.PLATFORM_CONFIG.get(platform, {}).get("login_url", "")

    def get_core_cookies(self, key: str) -> List[str]:
        platform = self.resolve_platform(key)
        return self.PLATFORM_CONFIG.get(platform, {}).get("core_cookies", [])

    def get_cookie_domain(self, key: str) -> str:
        """获取平台cookie域名（用于过滤）"""
        platform = self.resolve_platform(key)
        return self.PLATFORM_CONFIG.get(platform, {}).get("cookie_domain", "")

    # ---- 登录信号配置（都是可选，未配置不报错，走默认兜底）----

    def get_critical_cookie(self, key: str) -> str:
        """关键鉴权cookie名，值长度必须>=16才视为有效（防 placeholder/空 token）"""
        platform = self.resolve_platform(key)
        cfg = self.PLATFORM_CONFIG.get(platform, {})
        return cfg.get("critical_cookie") or ""

    def get_success_signals(self, key: str) -> List[str]:
        """页面成功信号关键词列表，命中任一即认为已离开登录页"""
        platform = self.resolve_platform(key)
        cfg = self.PLATFORM_CONFIG.get(platform, {})
        signals = cfg.get("success_signals") or []
        return list(signals) + ["退出登录", "logout", "我的"]  # 通用保底词

    def get_verify_url(self, key: str) -> str:
        """【可选】真试验证URL，配了就发GET确认未302跳登录页"""
        platform = self.resolve_platform(key)
        return self.PLATFORM_CONFIG.get(platform, {}).get("verify_url") or ""

    def register_cookie_key(self, key: str, platform: str) -> bool:
        """注册自定义cookie_key（多账号场景）"""
        if platform not in self.PLATFORM_CONFIG:
            return False
        mapping = self._load_key_map()
        mapping[key] = platform
        return self._save_key_map(mapping)

    def list_cookie_keys(self) -> List[Dict]:
        """列出所有cookie_key及状态（不返回cookie内容）"""
        all_keys = set(self.PLATFORM_CONFIG.keys())
        all_keys.update(self._load_key_map().keys())
        for d in self.list_all():
            all_keys.add(d.get("domain", ""))

        result = []
        for key in all_keys:
            if not key:
                continue
            ttl = self.ttl(key)
            logged_in = self.is_logged_in(key)
            if ttl > 0 and logged_in:
                status, days = "valid", round(ttl / 86400, 1)
            elif ttl > 0:
                status, days = "expired", round(ttl / 86400, 1)
            else:
                status, days = "none", 0
            result.append({
                "key": key,
                "platform": self.resolve_platform(key),
                "status": status,
                "days_left": days,
            })
        return result

    # ---- 抓取 ----

    async def capture(self, page, key: str, logged_in: bool = None) -> bool:
        """从Playwright Page抓取"""
        ctx = page.context if hasattr(page, 'context') else page
        return await self.capture_from_context(ctx, key, logged_in)

    async def capture_from_context(self, context, key: str, logged_in: bool = None) -> bool:
        """从Playwright Context抓取（必须在事件循环中 await 调用）"""
        try:
            cookies = await context.cookies()
            if not cookies:
                return False
            if logged_in is None:
                logged_in = self._is_logged_in(cookies, key)
            if not logged_in:
                logger.info(f"[Cookie] {key}: 未登录，跳过保存")
                return False
            filtered = self._filter(cookies, key)
            return self._save_to_redis(key, filtered)
        except Exception as e:
            logger.error(f"抓取cookie失败: {e}")
            return False

    def capture_from_drissionpage(self, page, key: str, logged_in: bool = None) -> bool:
        """从DrissionPage抓取（PDD脚本用）"""
        try:
            raw = page.cookies(all_domains=True) if hasattr(page, 'cookies') else []
            cookies = [{"name": c.get("name", ""), "value": c.get("value", ""),
                        "domain": c.get("domain", ""), "path": c.get("path", "/")}
                       for c in raw if isinstance(c, dict)]
            if not cookies:
                return False
            if logged_in is None:
                logged_in = self._is_logged_in(cookies, key)
            if not logged_in:
                logger.info(f"[Cookie] {key}: 未登录，跳过保存")
                return False
            filtered = self._filter(cookies, key)
            return self._save_to_redis(key, filtered)
        except Exception as e:
            logger.error(f"抓取cookie失败(DrissionPage): {e}")
            return False

    # ---- 登录检测 ----

    # 关键鉴权 cookie 的最小长度，防止值是 "1"/"placeholder"/"true" 这种占位
    _CRITICAL_MIN_LEN = 16

    # URL 上出现这些关键词 = 还在登录页，不算登录成功
    _LOGIN_URL_KEYWORDS = (
        "login", "passport", "signin", "sign-in", "login.aspx",
        "登录", "auth", "authorize", "sso",
    )

    def _cookie_pass_hard_check(self, cookies: List[Dict], key: str) -> bool:
        """第一层：cookie 硬门槛（最严格，不通过直接判未登录）"""
        core_names = self.get_core_cookies(key)
        if not core_names:
            return True  # 未配置平台，走宽松兜底

        # 条件1：核心 cookie 至少 2 个有值（继承原规则）
        found = [c["name"] for c in cookies
                 if c.get("name") in core_names and c.get("value")]
        if len(found) < min(2, len(core_names)):
            return False

        # 条件2：关键鉴权 cookie 值长度 >= 16（防 placeholder / 空 token）
        critical = self.get_critical_cookie(key)
        if critical:
            value = next((c.get("value", "") for c in cookies
                          if c.get("name") == critical), "")
            if len(value) < self._CRITICAL_MIN_LEN:
                return False

        return True

    def _check_page_signal(self, url: str, title: str, body_text: str, key: str) -> bool:
        """
        第二层：页面成功信号（只在有浏览器上下文信息时才有意义，否则返回 True 兜底）。
        规则：
          - URL 还包含 login / passport / 登录 关键字 → 还在登录页 = False
          - 否则：title / 正文 命中任一 success_signals 关键词 = True
        注意：传 None / 空串 = 调用方没有这些信息，本层不否决，返回 True 让其他层判断。
        """
        has_url = bool(url)
        has_content = bool(title) or bool(body_text)

        # 先排除：还在登录页 URL（有URL信息才判断）
        if has_url:
            lower = url.lower()
            if any(kw in lower for kw in self._LOGIN_URL_KEYWORDS):
                return False

        # 如果没有页面内容信息 → 本层无法给出正信号，返回 True 兜底（靠其他层）
        if not has_content:
            return True

        signals = self.get_success_signals(key)
        haystack = f"{title or ''}\n{(body_text or '')[:2000]}".lower()
        return any(sig.lower() in haystack for sig in signals)

    def _is_logged_in(self, cookies: List[Dict], key: str) -> bool:
        """
        三层登录判定（同步版，纯 cookie 判断；有浏览器页面信息时请走 check_login_complete 全量）

        第一层：cookie 硬门槛 —— 核心cookie≥2个 + 关键cookie值长度≥16
        第二层：页面成功信号 —— URL不在登录页 + title/正文命中成功关键词
                （同步版拿不到页面信息，第二层默认放行，依赖调用方传参）
        第三层：真试验证 —— 配置了 verify_url 时发GET确认未跳登录页
                （同步版不做，留给 async 入口）
        """
        return self._cookie_pass_hard_check(cookies, key)

    def check_login_complete(
        self,
        cookies: List[Dict],
        key: str,
        url: str = None,
        title: str = None,
        body_text: str = None,
    ) -> Dict[str, Any]:
        """
        全量登录完成判定（在浏览器上下文里调用，拿到页面 URL/title/正文才最准）
        返回 {ok:bool, reason:str, cookie_ok:bool, page_ok:bool}
        调用方打印 reason 就知道为什么过/没过，方便排查
        """
        cookie_ok = self._cookie_pass_hard_check(cookies, key)
        page_ok = self._check_page_signal(url, title, body_text, key)
        verify_url = self.get_verify_url(key)

        reasons = []
        if not cookie_ok:
            critical = self.get_critical_cookie(key)
            if critical:
                reasons.append(f"关键cookie {critical} 值太短/缺失")
            else:
                reasons.append("核心cookie数量不足")
        if not page_ok:
            reasons.append("页面仍在登录页或未发现登录成功信号")

        ok = cookie_ok and page_ok
        # 第三层 verify_url 不在这做（要 async HTTP），由调用方按需发起

        return {
            "ok": ok,
            "reason": "、".join(reasons) if reasons else
                      ("✅ cookie + 页面信号都通过" +
                       (f"（还需{verify_url}真试验证）" if verify_url else "")),
            "cookie_ok": cookie_ok,
            "page_ok": page_ok,
            "verify_url": verify_url,
        }

    def is_logged_in(self, key: str) -> bool:
        """检查Redis中的cookie是否包含登录态"""
        cookies = self.load(key)
        return bool(cookies) and self._is_logged_in(cookies, key)

    # ---- 存取 ----

    def save(self, key: str, cookies: List[Dict], expire_days: int = 30) -> bool:
        filtered = self._filter(cookies, key)
        return self._save_to_redis(key, filtered, expire_days)

    def load(self, key: str) -> List[Dict]:
        if not storage_manager.is_redis_available:
            return []
        return storage_manager.redis.load_cookies(key) or []

    def load_as_string(self, key: str) -> str:
        """转成HTTP header格式：name=value; name=value"""
        return "; ".join(f"{c['name']}={c['value']}" for c in self.load(key)
                         if c.get('name') and c.get('value'))

    def load_as_dict(self, key: str) -> Dict[str, str]:
        """转成字典，给requests.get(cookies=...)用"""
        return {c["name"]: c["value"] for c in self.load(key)
                if c.get("name") and c.get("value")}

    def delete(self, key: str) -> bool:
        if not storage_manager.is_redis_available:
            return False
        try:
            storage_manager.redis.delete_cookies(key)
            logger.info(f"Cookie已删除: {key}")
            return True
        except Exception:
            return False

    def ttl(self, key: str) -> int:
        """剩余秒数，-1=不存在"""
        if not storage_manager.is_redis_available:
            return -1
        return storage_manager.redis.get_cookie_ttl(key)

    def is_valid(self, key: str) -> bool:
        return self.ttl(key) > 0

    def list_all(self) -> List[Dict]:
        if not storage_manager.is_redis_available:
            return []
        return storage_manager.redis.list_cookies()

    def ensure_valid(self, key: str) -> bool:
        """cookie存在且有登录态"""
        return self.is_valid(key) and self.is_logged_in(key)

    # ---- 使用锁（借鉴旧项目 cookieUse：同一账号同时只允许一个任务使用）----

    _USE_LOCK_PREFIX = "cookie_use:"
    _USE_OWNER_PREFIX = "cookie_use_owner:"

    def acquire_use(self, key: str, owner: str, timeout: int = 3600) -> bool:
        """占用某账号的cookie，防止并发使用同一账号。owner 一般传 task_id/job_id。"""
        if not storage_manager.is_redis_available:
            return True
        if not storage_manager.acquire_lock(self._USE_LOCK_PREFIX + key, timeout):
            current = self.current_user(key)
            logger.warning(f"[Cookie] {key}: 正被 {current or '其他任务'} 使用，{owner} 等待中")
            return False
        storage_manager.redis.set(self._USE_OWNER_PREFIX + key, owner, expire=timeout)
        logger.info(f"[Cookie] {key}: 已分配使用锁给 {owner}")
        return True

    def release_use(self, key: str, owner: str) -> bool:
        """释放账号使用锁，仅当前占用者可释放"""
        if not storage_manager.is_redis_available:
            return True
        current = self.current_user(key)
        if current and current != owner:
            logger.warning(f"[Cookie] {key}: 使用锁属于 {current}，{owner} 无权释放")
            return False
        storage_manager.redis.delete(self._USE_OWNER_PREFIX + key)
        return storage_manager.release_lock(self._USE_LOCK_PREFIX + key)

    def current_user(self, key: str) -> str:
        """当前占用该账号的任务"""
        if not storage_manager.is_redis_available:
            return ""
        return storage_manager.redis.get(self._USE_OWNER_PREFIX + key, "") or ""

    # ---- 内部方法 ----

    def _save_to_redis(self, key: str, cookies: List[Dict], expire_days: int = 30) -> bool:
        if not storage_manager.is_redis_available:
            return False
        return storage_manager.redis.save_cookies(key, cookies, expire_days=expire_days)

    def refresh_ttl(self, key: str, expire_days: int = 30) -> bool:
        """仅刷新TTL（成功调用API后续期），不重写内容"""
        if not storage_manager.is_redis_available:
            return False
        return storage_manager.redis.extend_cookie_ttl(key, expire_days=expire_days)

    def _filter(self, cookies: List[Dict], key: str) -> List[Dict]:
        """
        按域名过滤cookie，保留平台相关cookie，丢弃第三方统计/追踪cookie

        策略：
        1. 解析cookie_key对应的平台根域名（如 jd.com）
        2. 保留域名匹配的cookie + 核心cookie（即使域名不匹配也保留）
        3. 同名同域名去重（保留最后一个，即最新值）
        """
        cookie_domain = self.get_cookie_domain(key)
        if not cookie_domain:
            return cookies

        core_names = set(self.get_core_cookies(key))

        # 保留：域名包含平台根域名的cookie，或核心cookie
        filtered = [
            c for c in cookies
            if cookie_domain in c.get("domain", "") or c.get("name", "") in core_names
        ]

        # 同名同域名去重，保留最后一个
        seen = {}
        for c in filtered:
            dedup_key = (c.get("name", ""), c.get("domain", ""))
            seen[dedup_key] = c

        result = list(seen.values())
        if len(result) != len(cookies):
            logger.info(f"[Cookie] {key}: 过滤 {len(cookies)} → {len(result)} 个（域名: {cookie_domain}）")
        return result

    def _load_key_map(self) -> Dict[str, str]:
        if not storage_manager.is_redis_available:
            return {}
        data = storage_manager.redis.get(self._MAP_KEY, {})
        return data if isinstance(data, dict) else {}

    def _save_key_map(self, mapping: Dict[str, str]) -> bool:
        if not storage_manager.is_redis_available:
            return False
        return storage_manager.redis.set(self._MAP_KEY, mapping)


cookie_manager = CookieManager()
