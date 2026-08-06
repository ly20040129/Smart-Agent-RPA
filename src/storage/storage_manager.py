# -*- coding: utf-8 -*-
"""
存储管理器 - 统一入口

整合Redis和MySQL，提供一站式存储服务。

使用方式：
    from src.storage import storage_manager

    # Cookie持久化（浏览器登录态）
    storage_manager.save_cookies('jd_shop', cookies)
    cookies = storage_manager.load_cookies('jd_shop')

    # 任务历史
    storage_manager.save_task_history(task_id, task_name, 'success', ...)

    # 业务数据
    storage_manager.save_business_data(task_id, task_name, 'sales', '7月销售额', '12345.67')

    # 通用缓存
    storage_manager.cache_set('key', value, expire=3600)
    value = storage_manager.cache_get('key')

设计要点：
- 单例模式，全局共享
- 懒加载，按需初始化
- 没配置Redis/MySQL时自动降级，不影响平台运行
"""
from typing import Any, Optional, List, Dict
from loguru import logger

from src.core.config import get_config
from .redis_manager import RedisManager
from .mysql_manager import MySQLManager


class StorageManager:
    """统一存储管理器"""

    def __init__(self):
        self._redis: Optional[RedisManager] = None
        self._mysql: Optional[MySQLManager] = None
        self._initialized = False

    def _init(self):
        """懒加载初始化（第一次使用时调用）"""
        if self._initialized:
            return
        self._initialized = True

        config = get_config()
        storage_config = config.storage

        # 初始化Redis
        if storage_config.get('redis', {}).get('enabled', False):
            redis_cfg = storage_config['redis']
            self._redis = RedisManager(
                host=redis_cfg.get('host', 'localhost'),
                port=redis_cfg.get('port', 6379),
                db=redis_cfg.get('db', 0),
                password=redis_cfg.get('password', ''),
                prefix=redis_cfg.get('prefix', 'agent:'),
            )
            logger.info("存储模块: Redis已启用")
        else:
            logger.info("存储模块: Redis未启用")

        # 初始化MySQL
        if storage_config.get('mysql', {}).get('enabled', False):
            mysql_cfg = storage_config['mysql']
            self._mysql = MySQLManager(
                host=mysql_cfg.get('host', 'localhost'),
                port=mysql_cfg.get('port', 3306),
                user=mysql_cfg.get('user', 'root'),
                password=mysql_cfg.get('password', ''),
                database=mysql_cfg.get('database', 'smart_agent'),
                charset=mysql_cfg.get('charset', 'utf8mb4'),
            )
            logger.info("存储模块: MySQL已启用")
        else:
            logger.info("存储模块: MySQL未启用")

    @property
    def redis(self) -> Optional[RedisManager]:
        """获取Redis管理器"""
        self._init()
        return self._redis

    @property
    def mysql(self) -> Optional[MySQLManager]:
        """获取MySQL管理器"""
        self._init()
        return self._mysql

    @property
    def is_redis_available(self) -> bool:
        """Redis是否可用"""
        return self.redis is not None and self.redis.client is not None

    @property
    def is_mysql_available(self) -> bool:
        """MySQL是否可用"""
        return self.mysql is not None and self.mysql.engine is not None

    # ==================== Cookie管理（Redis）====================

    def save_cookies(self, domain: str, cookies: List[Dict]) -> bool:
        """保存浏览器cookie"""
        if self.is_redis_available:
            return self._redis.save_cookies(domain, cookies)
        logger.debug(f"Redis不可用，跳过Cookie保存: {domain}")
        return False

    def load_cookies(self, domain: str) -> Optional[List[Dict]]:
        """读取浏览器cookie"""
        if self.is_redis_available:
            return self._redis.load_cookies(domain)
        return None

    def delete_cookies(self, domain: str) -> bool:
        """删除cookie"""
        if self.is_redis_available:
            return self._redis.delete_cookies(domain)
        return False

    def list_cookie_domains(self) -> List[str]:
        """列出所有已保存cookie的域名"""
        if self.is_redis_available:
            return self._redis.list_cookie_domains()
        return []

    # ==================== 缓存（Redis）====================

    def cache_set(self, key: str, value: Any, expire: int = 0) -> bool:
        """设置缓存"""
        if self.is_redis_available:
            return self._redis.set(key, value, expire)
        return False

    def cache_get(self, key: str, default: Any = None) -> Any:
        """获取缓存"""
        if self.is_redis_available:
            return self._redis.get(key, default)
        return default

    def cache_delete(self, key: str) -> bool:
        """删除缓存"""
        if self.is_redis_available:
            return self._redis.delete(key)
        return False

    # ==================== 分布式锁（Redis）====================

    def acquire_lock(self, lock_name: str, timeout: int = 300) -> bool:
        """获取分布式锁"""
        if self.is_redis_available:
            return self._redis.acquire_lock(lock_name, timeout)
        return True  # 无Redis时直接放行

    def release_lock(self, lock_name: str) -> bool:
        """释放分布式锁"""
        if self.is_redis_available:
            return self._redis.release_lock(lock_name)
        return True

    # ==================== 任务状态（Redis）====================

    def set_task_status(self, task_id: str, status: str, extra: dict = None) -> bool:
        """记录任务实时状态"""
        if self.is_redis_available:
            return self._redis.set_task_status(task_id, status, extra)
        return False

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """获取任务实时状态"""
        if self.is_redis_available:
            return self._redis.get_task_status(task_id)
        return None

    # ==================== 任务历史（MySQL）====================

    def save_task_history(self, task_id: str, task_name: str, status: str,
                          start_time: str = None, end_time: str = None,
                          elapsed_time: str = None, steps_total: int = 0,
                          steps_completed: int = 0, error_message: str = None,
                          context: dict = None) -> bool:
        """保存任务执行历史"""
        if self.is_mysql_available:
            return self._mysql.save_task_history(
                task_id, task_name, status, start_time, end_time,
                elapsed_time, steps_total, steps_completed,
                error_message, context
            )
        return False

    def query_task_history(self, task_id: str = None, status: str = None,
                           limit: int = 50) -> List[Dict]:
        """查询任务执行历史"""
        if self.is_mysql_available:
            return self._mysql.query_task_history(task_id, status, limit)
        return []

    # ==================== 下载记录（MySQL）====================

    def save_download_record(self, task_id: str, task_name: str,
                             file_name: str, file_path: str,
                             file_size: int = 0, source_url: str = '') -> bool:
        """保存下载记录"""
        if self.is_mysql_available:
            return self._mysql.save_download_record(
                task_id, task_name, file_name, file_path, file_size, source_url
            )
        return False

    # ==================== 业务数据（MySQL）====================

    def save_business_data(self, task_id: str, task_name: str,
                           data_type: str, data_key: str, data_value: str,
                           raw_data: dict = None, remark: str = '') -> bool:
        """保存业务数据"""
        if self.is_mysql_available:
            return self._mysql.save_business_data(
                task_id, task_name, data_type, data_key, data_value, raw_data, remark
            )
        return False

    def query_business_data(self, data_type: str = None, task_id: str = None,
                            limit: int = 100) -> List[Dict]:
        """查询业务数据"""
        if self.is_mysql_available:
            return self._mysql.query_business_data(data_type, task_id, limit)
        return []

    # ==================== 通用SQL（MySQL）====================

    def execute_sql(self, sql: str, params: dict = None) -> Optional[List[Dict]]:
        """执行任意SQL"""
        if self.is_mysql_available:
            return self._mysql.execute_sql(sql, params)
        return None

    def close(self):
        """关闭所有连接"""
        if self._redis:
            self._redis.close()
        if self._mysql:
            self._mysql.close()
        logger.info("存储模块已关闭")


# 全局单例
storage_manager = StorageManager()
