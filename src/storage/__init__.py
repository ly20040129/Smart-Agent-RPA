# -*- coding: utf-8 -*-
"""
存储管理模块

提供统一的存储能力：
- Redis: cookie持久化、会话缓存、任务状态
- MySQL: 业务数据、执行历史、下载记录

使用方式：
    from src.storage import storage_manager

    # 存取cookie
    storage_manager.save_cookies('jd_shop', cookies)
    cookies = storage_manager.load_cookies('jd_shop')

    # 存取业务数据
    storage_manager.save_record('task_history', {...})
    records = storage_manager.query_records('task_history', ...)
"""
from .storage_manager import storage_manager

__all__ = ['storage_manager']
