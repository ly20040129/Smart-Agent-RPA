# -*- coding: utf-8 -*-
"""
Redis管理器

功能：
1. Cookie持久化 - 保存/恢复浏览器登录态
2. 会话缓存 - 任务状态、临时数据
3. 分布式锁 - 防止任务重复执行

设计要点：
- 懒加载：第一次调用时才连接，没配置Redis时自动跳过
- 连接池：复用连接，避免频繁创建/销毁
- JSON序列化：cookie等复杂数据自动序列化
"""
import json
import time
from typing import Any, Optional, List, Dict
from loguru import logger

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    logger.warning("未安装redis库，Redis功能不可用。安装: pip install redis")


class RedisManager:
    """Redis管理器"""

    def __init__(self, host: str = 'localhost', port: int = 6379,
                 db: int = 0, password: str = '', prefix: str = 'agent:'):
        """
        初始化Redis管理器

        Args:
            host: Redis服务器地址
            port: 端口
            db: 数据库编号
            password: 密码（无则留空）
            prefix: key前缀，避免和其他项目冲突
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password if password else None
        self.prefix = prefix
        self._client = None  # 懒加载

    @property
    def client(self):
        """懒加载Redis连接（连接池）"""
        if not HAS_REDIS:
            return None
        if self._client is None:
            try:
                self._client = redis.ConnectionPool(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    decode_responses=True,  # 自动解码为字符串
                    max_connections=20,
                    protocol=2,  # 强制用RESP2，兼容老版本Redis
                )
                # 测试连接
                test_conn = redis.Redis(connection_pool=self._client)
                test_conn.ping()
                logger.info(f"Redis连接成功: {self.host}:{self.port} db={self.db}")
            except Exception as e:
                logger.warning(f"Redis连接失败: {e}，Redis功能不可用")
                self._client = None
                return None
        return redis.Redis(connection_pool=self._client) if self._client else None

    def _key(self, key: str) -> str:
        """添加前缀"""
        return f"{self.prefix}{key}"

    # ==================== Cookie管理 ====================

    def save_cookies(self, domain: str, cookies: List[Dict]) -> bool:
        """
        保存浏览器cookie到Redis

        Args:
            domain: 网站标识，如 'jd_shop', 'wechat_pay'
            cookies: Playwright的cookie列表

        Returns:
            是否保存成功
        """
        client = self.client
        if client is None:
            return False

        try:
            data = json.dumps(cookies, ensure_ascii=False)
            key = self._key(f"cookies:{domain}")
            client.set(key, data)
            # 设置过期时间30天
            client.expire(key, 30 * 24 * 3600)
            logger.info(f"Cookie已保存到Redis: {domain} ({len(cookies)}条, 30天有效)")
            return True
        except Exception as e:
            logger.error(f"保存Cookie失败: {e}")
            return False

    def load_cookies(self, domain: str) -> Optional[List[Dict]]:
        """
        从Redis读取浏览器cookie

        Args:
            domain: 网站标识

        Returns:
            cookie列表，无则返回None
        """
        client = self.client
        if client is None:
            return None

        try:
            key = self._key(f"cookies:{domain}")
            data = client.get(key)
            if data:
                cookies = json.loads(data)
                logger.info(f"从Redis读取Cookie: {domain} ({len(cookies)}条)")
                # 每次读取时自动续期30天
                client.expire(key, 30 * 24 * 3600)
                return cookies
            logger.debug(f"Redis中无Cookie: {domain}")
            return None
        except Exception as e:
            logger.error(f"读取Cookie失败: {e}")
            return None

    def get_cookie_ttl(self, domain: str) -> int:
        """返回Cookie剩余有效时间（秒），-1表示不存在"""
        client = self.client
        if client is None:
            return -1
        try:
            key = self._key(f"cookies:{domain}")
            ttl = client.ttl(key)
            return ttl
        except Exception as e:
            logger.error(f"获取Cookie TTL失败: {e}")
            return -1

    def list_cookies(self) -> list:
        """列出所有已存储的Cookie及其状态"""
        client = self.client
        if client is None:
            return []
        try:
            keys = client.keys(self._key("cookies:*"))
            result = []
            for k in keys:
                # 去掉前缀
                domain = k.replace(self._key("cookies:"), "")
                ttl = client.ttl(k)
                # 读取cookie数量
                data = client.get(k)
                count = len(__import__('json').loads(data)) if data else 0
                if ttl > 0:
                    days_left = round(ttl / 86400, 1)
                    status = "正常"
                elif ttl == -1:
                    days_left = -1
                    status = "永不过期"
                else:
                    days_left = 0
                    status = "已过期"
                result.append({
                    "domain": domain,
                    "count": count,
                    "ttl": ttl,
                    "days_left": days_left,
                    "status": status
                })
            return result
        except Exception as e:
            logger.error(f"列出Cookie失败: {e}")
            return []

    def delete_cookies(self, domain: str) -> bool:
        """删除指定域名的cookie"""
        client = self.client
        if client is None:
            return False
        try:
            key = self._key(f"cookies:{domain}")
            client.delete(key)
            logger.info(f"Cookie已删除: {domain}")
            return True
        except Exception as e:
            logger.error(f"删除Cookie失败: {e}")
            return False

    def list_cookie_domains(self) -> List[str]:
        """列出所有已保存cookie的域名标识"""
        client = self.client
        if client is None:
            return []
        try:
            pattern = self._key("cookies:*")
            keys = client.keys(pattern)
            # 提取域名标识
            prefix_len = len(self._key("cookies:"))
            return [k[prefix_len:] for k in keys]
        except Exception:
            return []

    # ==================== 通用缓存 ====================

    def set(self, key: str, value: Any, expire: int = 0) -> bool:
        """
        设置缓存

        Args:
            key: 缓存键
            value: 值（自动JSON序列化）
            expire: 过期时间（秒），0=不过期
        """
        client = self.client
        if client is None:
            return False
        try:
            data = json.dumps(value, ensure_ascii=False)
            k = self._key(key)
            if expire > 0:
                client.setex(k, expire, data)
            else:
                client.set(k, data)
            return True
        except Exception as e:
            logger.error(f"Redis SET失败: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """获取缓存"""
        client = self.client
        if client is None:
            return default
        try:
            data = client.get(self._key(key))
            if data:
                return json.loads(data)
            return default
        except Exception:
            return default

    def delete(self, key: str) -> bool:
        """删除缓存"""
        client = self.client
        if client is None:
            return False
        try:
            client.delete(self._key(key))
            return True
        except Exception:
            return False

    # ==================== 分布式锁 ====================

    def acquire_lock(self, lock_name: str, timeout: int = 300) -> bool:
        """
        获取分布式锁（防止任务重复执行）

        Args:
            lock_name: 锁名称
            timeout: 锁超时时间（秒）

        Returns:
            是否获取成功
        """
        client = self.client
        if client is None:
            return True  # 没有Redis时直接放行
        try:
            key = self._key(f"lock:{lock_name}")
            # SET NX EX：不存在才设置，带过期
            result = client.set(key, str(time.time()), nx=True, ex=timeout)
            if result:
                logger.info(f"获取锁成功: {lock_name}")
                return True
            logger.warning(f"获取锁失败（已被占用）: {lock_name}")
            return False
        except Exception as e:
            logger.error(f"获取锁异常: {e}")
            return True  # 异常时放行，不阻塞业务

    def release_lock(self, lock_name: str) -> bool:
        """释放分布式锁"""
        client = self.client
        if client is None:
            return True
        try:
            client.delete(self._key(f"lock:{lock_name}"))
            logger.info(f"释放锁: {lock_name}")
            return True
        except Exception:
            return False

    # ==================== 任务状态 ====================

    def set_task_status(self, task_id: str, status: str, extra: dict = None) -> bool:
        """
        记录任务实时状态

        Args:
            task_id: 任务ID
            status: 状态（running/success/failed/waiting）
            extra: 附加信息
        """
        data = {
            'status': status,
            'timestamp': time.time(),
            'extra': extra or {}
        }
        # 状态保留1小时
        return self.set(f"task_status:{task_id}", data, expire=3600)

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """获取任务实时状态"""
        return self.get(f"task_status:{task_id}")

    def close(self):
        """关闭连接池"""
        if self._client:
            self._client.disconnect()
            self._client = None
            logger.info("Redis连接已关闭")
