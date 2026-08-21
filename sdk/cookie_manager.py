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
from typing import List, Dict
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
            "core_cookies": ["session_key", "verifysession", "merchant_id", "g_ticket"],
        },
        "jd_shop": {
            "login_url": "https://passport.jd.com/new/login.aspx",
            "core_cookies": ["pin", "thor", "pinId", "_pst"],
        },
        "jd_shop_ibay": {
            "login_url": "https://shop.jd.com/jdm/trade/tools/export/ExprotList?_JDMOMID_=1568",
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
        # 在这里添加更多平台...
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

    def capture(self, page, key: str, logged_in: bool = None) -> bool:
        """从Playwright Page抓取"""
        ctx = page.context if hasattr(page, 'context') else page
        return self.capture_from_context(ctx, key, logged_in)

    def capture_from_context(self, context, key: str, logged_in: bool = None) -> bool:
        """从Playwright Context抓取"""
        import asyncio
        try:
            # 用 asyncio.run 执行异步的 cookies()
            cookies = asyncio.run(context.cookies())
            if not cookies:
                return False
            if logged_in is None:
                logged_in = self._is_logged_in(cookies, key)
            if not logged_in:
                logger.info(f"[Cookie] {key}: 未登录，跳过保存")
                return False
            filtered = self._filter(cookies, key)
            return self._save_to_redis(key, filtered)
        except RuntimeError as e:
            # 如果已经在事件循环中，用另一个方式
            try:
                loop = asyncio.get_running_loop()
                # 如果在运行中的循环里，用 run_coroutine_threadsafe 或 create_task
                cookies = asyncio.run_coroutine_threadsafe(context.cookies(), loop).result(timeout=10)
            except Exception:
                raise
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

    def _is_logged_in(self, cookies: List[Dict], key: str) -> bool:
        """核心cookie至少找到2个有值的才算已登录"""
        core_names = self.get_core_cookies(key)
        if not core_names:
            return True
        found = [c["name"] for c in cookies if c.get("name") in core_names and c.get("value")]
        return len(found) >= min(2, len(core_names))

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

    # ---- 内部方法 ----

    def _save_to_redis(self, key: str, cookies: List[Dict], expire_days: int = 30) -> bool:
        if not storage_manager.is_redis_available:
            return False
        return storage_manager.redis.save_cookies(key, cookies)

    def _filter(self, cookies: List[Dict], key: str) -> List[Dict]:
        """只保留核心cookie，同名去重（保留域名最短的）"""
        # core_names = self.get_core_cookies(key)
        # if not core_names:
        return cookies

        # filtered = [c for c in cookies if c.get("name") in core_names]
        # seen = {}
        # for c in filtered:
        #     name = c.get("name", "")
        #     if name not in seen or len(c.get("domain", "")) < len(seen[name].get("domain", "")):
        #         seen[name] = c

        # result = list(seen.values())
        # if len(result) != len(cookies):
        #     logger.info(f"[Cookie] {key}: 精简 {len(cookies)} → {len(result)} 个")
        # return result

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
