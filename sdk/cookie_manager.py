# -*- coding: utf-8 -*-
"""
Cookie管理器 - 通用cookie抓取、精简、存取

核心逻辑：
  1. 浏览器任务执行前：load() 从Redis读cookie注入浏览器
  2. 浏览器任务执行中：打开页面后检测是否已登录
     → 已登录 → 跳过登录，继续执行
     → 未登录 → 等用户扫码登录，登录成功后抓取cookie存入Redis
  3. 浏览器关闭时：只在已登录状态下才抓取cookie（避免把未登录的坏cookie覆盖好cookie）
  4. API任务执行前：load() 读cookie → 调API
     → 如果API返回登录过期错误 → 抛出明确提示"请去Web界面刷新cookie"
  5. Web界面有"刷新cookie"按钮：打开浏览器→用户登录→后台自动检测→存Redis

多账号支持：
  cookie_key 可以是任意名称（任务名、账号名等），通过 platform 关联登录配置。
  解析顺序：直接匹配PLATFORM_CONFIG → Redis映射 → 前缀匹配
  例：cookie_key="jd_shangzhi_店铺A" → 自动解析到 platform="jd_shangzhi"

用法：
  from sdk.cookie_manager import cookie_manager

  # 浏览器任务中
  cookies = cookie_manager.load("wechat_pay")
  # ... 任务执行 ...
  # 关闭浏览器前检查是否已登录才保存
  cookie_manager.capture_from_context(ctx, "wechat_pay", logged_in=True)

  # API任务中
  cookies = cookie_manager.load("jd_shop_ibay")
  if not cookies:
      raise RuntimeError("Cookie不存在，请去Web界面刷新cookie")

  # 检查是否有效
  cookie_manager.is_valid("wechat_pay")

  # 多账号：注册一个自定义cookie_key
  cookie_manager.register_cookie_key("jd_shangzhi_店铺B", "jd_shangzhi")
  cookies = cookie_manager.load("jd_shangzhi_店铺B")

  一句话：自定义周期检测cookies，可以自定义刷新指定的cookies，只要任务可以正常执行就抓取整个正常的cookies，
  并对cookies存写进行简化，通过platfrom_config管理各个任务的cookies（平台多，账号多，一个平台多个渠道）

"""
import sys
import json
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.storage import storage_manager


class CookieManager:
    """Cookie管理器 - 抓取、精简、存取"""

    # ============================================================
    # 每个平台的核心cookie名 + 登录页URL
    #
    # 核心cookie：登录后才出现的cookie，用它们判断是否已登录
    # 登录页URL：Web界面"刷新cookie"按钮打开这个页面让用户登录
    # ============================================================
    PLATFORM_CONFIG: Dict[str, Dict] = {
        "wechat_pay": {
            "login_url": "https://pay.weixin.qq.com/index.php/core/home/login?return_url=https%3A%2F%2Fpay.weixin.qq.com%2Findex.php%2Fcore%2Fhome%2Fheader%3Fmenu%3D14103",
            # tgw_l7_route 是负载均衡cookie，访问即设置，不是登录态cookie，已移除
            "core_cookies": ["session_key", "verifysession", "merchant_id", "g_ticket"],
        },
        "jd_shop": {
            "login_url": "https://passport.jd.com/new/login.aspx",
            "core_cookies": ["pin", "thor", "pinId", "_pst"],
        },
        "jd_shop_ibay": {
            "login_url": "https://shop.jd.com/jdm/trade/tools/export/ExprotList?_JDMOMID_=1568",
            # __jdu 是设备追踪cookie，访问即设置，不是登录态cookie，已移除
            "core_cookies": ["pin", "thor", "pinId", "_pst"],
        },
        "jd_shangzhi": {
            "login_url": "https://shop.jd.com/jdm/trade/tools/export/ExprotList?_JDMOMID_=1568",
            "core_cookies": ["pin", "thor", "pinId", "_pst"],
        },
        "pdd": {
            "login_url": "https://live.pinduoduo.com/n-creator/video/replay-manage",
            "core_cookies": ["pdd_user_id", "L_PASS_ID", "L_PASS_TYPE", "windows_app_shop_token_23"],
        },
        # 在这里添加更多平台...后续直接在这里管理cookeis
    }

    # ============================================================
    # 配置访问 + 平台解析（支持多账号）
    # ============================================================

    @property
    def PLATFORM_COOKIES(self) -> Dict[str, List[str]]:
        """兼容旧代码：返回 {platform: [core_cookie_names]}"""
        return {k: v["core_cookies"] for k, v in self.PLATFORM_CONFIG.items()}

    def resolve_platform(self, key: str) -> str:
        """
        解析cookie_key对应的平台名
        解析顺序：
          1. 直接匹配PLATFORM_CONFIG（如 key="jd_shangzhi" → "jd_shangzhi"）
          2. Redis映射（通过register_cookie_key注册的）
          3. 前缀匹配（如 key="jd_shangzhi_店铺A" → "jd_shangzhi"）
        返回平台名，未找到返回空串
        """
        # 1. 直接匹配
        if key in self.PLATFORM_CONFIG:
            return key

        # 2. Redis映射
        mapping = self._load_key_map()
        if key in mapping:
            platform = mapping[key]
            if platform in self.PLATFORM_CONFIG:
                return platform

        # 3. 前缀匹配：key 以 "{platform}_" 或 "{platform}-" 开头
        for platform in self.PLATFORM_CONFIG:
            if key.startswith(platform + "_") or key.startswith(platform + "-"):
                return platform

        return ""

    def get_login_url(self, key: str) -> str:
        """获取cookie_key对应平台的登录页URL"""
        platform = self.resolve_platform(key)
        cfg = self.PLATFORM_CONFIG.get(platform, {})
        return cfg.get("login_url", "")

    def get_core_cookies(self, key: str) -> List[str]:
        """获取cookie_key对应平台的核心cookie名列表"""
        platform = self.resolve_platform(key)
        cfg = self.PLATFORM_CONFIG.get(platform, {})
        return cfg.get("core_cookies", [])

    def register_cookie_key(self, key: str, platform: str) -> bool:
        """
        注册一个自定义cookie_key，关联到某个平台
        用于多账号场景：同一平台不同账号用不同的cookie_key

        Args:
            key: cookie_key名称（如 "jd_shangzhi_店铺B"）
            platform: 平台名（必须在PLATFORM_CONFIG中，如 "jd_shangzhi"）
        """
        if platform not in self.PLATFORM_CONFIG:
            logger.warning(f"未知平台: {platform}，无法注册cookie_key")
            return False

        mapping = self._load_key_map()
        mapping[key] = platform
        return self._save_key_map(mapping)

    def unregister_cookie_key(self, key: str) -> bool:
        """删除一个自定义cookie_key的注册"""
        mapping = self._load_key_map()
        if key in mapping:
            del mapping[key]
            self._save_key_map(mapping)
            # 同时删除Redis中的cookie
            self.delete(key)
            return True
        return False

    def list_cookie_keys(self) -> List[Dict]:
        """
        列出所有cookie_key及其状态
        来源：PLATFORM_CONFIG中的平台 + Redis中注册的自定义key + Redis中已有cookie的key
        不返回cookie内容，只返回状态
        """
        all_keys = set()

        # 1. PLATFORM_CONFIG 中的平台（直接作为cookie_key）
        for platform in self.PLATFORM_CONFIG:
            all_keys.add(platform)

        # 2. Redis映射中的自定义key
        mapping = self._load_key_map()
        all_keys.update(mapping.keys())

        # 3. Redis中已有cookie的key
        for domain in self.list_all():
            all_keys.add(domain.get("domain", ""))

        result = []
        for key in all_keys:
            if not key:
                continue
            platform = self.resolve_platform(key)
            ttl = self.ttl(key)
            logged_in = self.is_logged_in(key)

            if ttl > 0 and logged_in:
                status = "valid"
                days_left = round(ttl / 86400, 1)   #86400是一天的时间，用于计算cookies还有多久到期
            elif ttl > 0 and not logged_in:
                status = "expired"
                days_left = round(ttl / 86400, 1)
            else:
                status = "none"
                days_left = 0

            result.append({
                "key": key,
                "platform": platform,
                "login_url": self.get_login_url(key),
                "status": status,
                "days_left": days_left,
            })

        return result

    # ============================================================
    # Redis映射存取（内部）
    # ============================================================

    _MAP_KEY = "cookie_key_map"

    def _load_key_map(self) -> Dict[str, str]:
        """从Redis读取 cookie_key → platform 的映射"""
        if not storage_manager.is_redis_available:
            return {}
        data = storage_manager.redis.get(self._MAP_KEY, {})
        return data if isinstance(data, dict) else {}

    def _save_key_map(self, mapping: Dict[str, str]) -> bool:
        """保存 cookie_key → platform 的映射到Redis"""
        if not storage_manager.is_redis_available:
            return False
        return storage_manager.redis.set(self._MAP_KEY, mapping)

    # ============================================================
    # 抓取cookie（从浏览器页面）
    # ============================================================

    def capture(self, page, key: str, logged_in: bool = None) -> bool:
        """
        从Playwright页面抓取cookie

        Args:
            page: Playwright的Page对象
            key: 平台标识
            logged_in: 是否已登录
                True = 确认已登录，抓取并保存
                False = 确认未登录，不保存（避免覆盖好cookie）
                None = 自动检测（看核心cookie是否存在）
        """
        try:
            context = page.context if hasattr(page, 'context') else page
            cookies = context.cookies()

            if not cookies:
                logger.warning(f"页面没有cookie: {key}")
                return False

            # 自动检测登录状态
            if logged_in is None:
                logged_in = self._is_logged_in(cookies, key)

            if not logged_in:
                logger.info(f"[Cookie] {key}: 未登录，跳过保存（不覆盖现有cookie）")
                return False

            # 已登录，精简并保存
            filtered = self._filter(cookies, key)
            return self._save_to_redis(key, filtered)

        except Exception as e:
            logger.error(f"抓取cookie失败: {e}")
            return False

    def capture_from_context(self, context, key: str, logged_in: bool = None) -> bool:
        """从Playwright BrowserContext抓取cookie"""
        try:
            cookies = context.cookies()
            if not cookies:
                logger.warning(f"Context没有cookie: {key}")
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

#这里的drissionpage主要针对逆向，因此调用了该浏览器，可以做替换

    def capture_from_drissionpage(self, page, key: str, logged_in: bool = None) -> bool:
        """从DrissionPage抓取cookie"""
        try:
            raw_cookies = page.cookies(all_domains=True) if hasattr(page, 'cookies') else []
            cookies = []
            for c in raw_cookies:
                if isinstance(c, dict):
                    cookies.append({
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", ""),
                        "path": c.get("path", "/"),
                    })

            if not cookies:
                logger.warning(f"DrissionPage没有cookie: {key}")
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

    # ============================================================
    # 登录检测
    # ============================================================

    def _is_logged_in(self, cookies: List[Dict], key: str) -> bool:
        """
        检测是否已登录：看核心cookie是否有足够的数量存在

        逻辑：核心cookie列表中至少找到2个（或全部，如果总数少于2）才算已登录
        避免单个cookie（如设备追踪cookie）误判为已登录
        """
        core_names = self.get_core_cookies(key)
        if not core_names:
            # 没配置核心cookie，无法判断，保守起见认为已登录
            return True

        # 计算找到了多少个核心cookie
        cookie_names = {c.get("name", "") for c in cookies}
        found = [c for c in core_names if c in cookie_names]
        # 检查找到的cookie是否有值（排除空值cookie）
        found_with_value = []
        for c in cookies:
            name = c.get("name", "")
            value = c.get("value", "")
            if name in core_names and value:
                found_with_value.append(name)

        # 至少找到2个（或全部，如果核心cookie总数少于2）
        threshold = min(2, len(core_names))
        return len(found_with_value) >= threshold

    def is_logged_in(self, key: str) -> bool:
        """
        检查Redis中的cookie是否包含登录态

        用法（API任务执行前检查）：
            if not cookie_manager.is_logged_in("jd_shangzhi"):
                raise RuntimeError("Cookie不存在或未登录，请去Web界面刷新cookie")
        """
        cookies = self.load(key)
        if not cookies:
            return False
        return self._is_logged_in(cookies, key)

    # ============================================================
    # 存取（Redis）
    # ============================================================

    def save(self, key: str, cookies: List[Dict], expire_days: int = 30) -> bool:
        """手动保存cookie"""
        filtered = self._filter(cookies, key)
        return self._save_to_redis(key, filtered, expire_days)

    def load(self, key: str) -> List[Dict]:
        """读取cookie"""
        if not storage_manager.is_redis_available:
            return []
        return storage_manager.redis.load_cookies(key) or []

    def load_as_string(self, key: str) -> str:
        """
        读取cookie并转成HTTP header字符串（name=value; name=value）
        API任务用这个最方便
        """
        cookies = self.load(key)
        if not cookies:
            return ""
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get('name') and c.get('value'))

    def load_as_dict(self, key: str) -> Dict[str, str]:
        """
        读取cookie并转成字典 {name: value}
        requests.get(cookies=...) 用这个
        """
        cookies = self.load(key)
        if not cookies:
            return {}
        return {c["name"]: c["value"] for c in cookies if c.get("name") and c.get("value")}

    def delete(self, key: str) -> bool:
        """删除cookie"""
        if not storage_manager.is_redis_available:
            return False
        try:
            storage_manager.redis.delete_cookies(key)
            logger.info(f"Cookie已删除: {key}")
            return True
        except Exception:
            return False

    def ttl(self, key: str) -> int:
        """查看cookie剩余有效时间（秒），-1=不存在"""
        if not storage_manager.is_redis_available:
            return -1
        return storage_manager.redis.get_cookie_ttl(key)

    def is_valid(self, key: str) -> bool:
        """Redis中的cookie是否还在（没过期）"""
        return self.ttl(key) > 0

    def list_all(self) -> List[Dict]:
        """列出所有cookie状态"""
        if not storage_manager.is_redis_available:
            return []
        return storage_manager.redis.list_cookies()

    def ensure_valid(self, key: str) -> bool:
        """
        检查cookie是否存在且包含登录态

        用法（API任务执行前）：
            if not cookie_manager.ensure_valid("jd_shangzhi"):
                raise RuntimeError("Cookie不存在或已过期，请去Web界面刷新cookie")
        """
        if not self.is_valid(key):
            return False
        return self.is_logged_in(key)

    # ============================================================
    # 内部方法
    # ============================================================

    def _save_to_redis(self, key: str, cookies: List[Dict], expire_days: int = 30) -> bool:
        if not storage_manager.is_redis_available:
            return False
        return storage_manager.redis.save_cookies(key, cookies)

    def _filter(self, cookies: List[Dict], key: str) -> List[Dict]:
        """按平台精简cookie：只保留核心cookie + 同名去重"""
        core_keys = self.get_core_cookies(key)

        if not core_keys:
            logger.info(f"[Cookie] {key}: 未配置核心cookie列表，保存全部 {len(cookies)} 个")
            return cookies

        filtered = [c for c in cookies if c.get("name") in core_keys]

        # 因此如果是同一个平台还在相同的cookies，保留一个最短的
        # 并且可以做到cookies的优化，也可以持续进行最新cookies的刷新的和抓取（莫比乌斯）
        
        seen = {}
        for c in filtered:
            name = c.get("name", "")
            domain = c.get("domain", "")
            if name not in seen:
                seen[name] = c
            else:
                if len(domain) < len(seen[name].get("domain", "")):
                    seen[name] = c

        result = list(seen.values())
        before = len(cookies)
        after = len(result)
        if before != after:
            logger.info(f"[Cookie] {key}: 精简 {before} → {after} 个")
        return result


# 全局单例
cookie_manager = CookieManager()
