# -*- coding: utf-8 -*-
"""
通用装饰器库（借鉴 dj_new_server 依赖注入思想）

把 Cookie 管理、日志记录、参数校验、失败重试等"每个需求都要写一遍的样板代码"
抽成装饰器，让业务函数只关注核心逻辑。

用法:
    @with_cookie("jd_shangzhi")
    @with_logging("京东商智统计")
    @validate_params("excel_path", "output_dir")
    @auto_retry(3)
    async def process(date_str=None, excel_path=None, output_dir=None, **kwargs):
        # 这里只写业务逻辑，kwargs['cookie'] 已自动注入
        ...
"""
import functools
import os
import sys
import time
import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ==================== Cookie 装饰器 ====================

def with_cookie(cookie_key: str):
    """
    自动处理 Cookie 获取、使用锁、释放。

    被装饰函数的 kwargs 中会注入 cookie 字典，
    业务代码直接 kwargs['cookie'] 拿。

    例:
        @with_cookie("jd_shangzhi")
        async def process(**kwargs):
            cookie = kwargs['cookie']  # dict 格式
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            from sdk.cookie_manager import cookie_manager

            owner = kwargs.pop("_cookie_owner", func.__name__)
            if not cookie_manager.acquire_use(cookie_key, owner):
                raise RuntimeError(f"Cookie账号 {cookie_key} 正被其他任务使用，请稍后重试")

            try:
                cookies = cookie_manager.load(cookie_key)
                if not cookies or not cookie_manager.is_logged_in(cookie_key):
                    raise RuntimeError(
                        f"Cookie不存在或已过期（{cookie_key}）。\n"
                        f"请去Web界面 → Cookie管理 → 点击「刷新」按钮重新登录。"
                    )
                kwargs["cookie"] = cookies
                kwargs["cookie_dict"] = cookie_manager.load_as_dict(cookie_key)
                kwargs["cookie_string"] = cookie_manager.load_as_string(cookie_key)
                return func(*args, **kwargs)
            finally:
                cookie_manager.release_use(cookie_key, owner)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            from sdk.cookie_manager import cookie_manager

            owner = kwargs.pop("_cookie_owner", func.__name__)
            if not cookie_manager.acquire_use(cookie_key, owner):
                raise RuntimeError(f"Cookie账号 {cookie_key} 正被其他任务使用，请稍后重试")

            try:
                cookies = cookie_manager.load(cookie_key)
                if not cookies or not cookie_manager.is_logged_in(cookie_key):
                    raise RuntimeError(
                        f"Cookie不存在或已过期（{cookie_key}）。\n"
                        f"请去Web界面 → Cookie管理 → 点击「刷新」按钮重新登录。"
                    )
                kwargs["cookie"] = cookies
                kwargs["cookie_dict"] = cookie_manager.load_as_dict(cookie_key)
                kwargs["cookie_string"] = cookie_manager.load_as_string(cookie_key)
                return await func(*args, **kwargs)
            finally:
                cookie_manager.release_use(cookie_key, owner)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ==================== 日志装饰器 ====================

def with_logging(task_name: str = ""):
    """
    自动记录任务开始/结束/耗时/异常。

    例:
        @with_logging("京东商智统计")
        async def process(**kwargs):
            ...
    """
    def decorator(func: Callable):
        name = task_name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger.info(f"[{name}] ========== 开始执行 ==========")
            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                logger.info(f"[{name}] ✅ 执行成功，耗时 {elapsed:.1f}秒")
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.error(f"[{name}] ❌ 执行失败（{elapsed:.1f}秒）: {e}")
                raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger.info(f"[{name}] ========== 开始执行 ==========")
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.time() - start
                logger.info(f"[{name}] ✅ 执行成功，耗时 {elapsed:.1f}秒")
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.error(f"[{name}] ❌ 执行失败（{elapsed:.1f}秒）: {e}")
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ==================== 参数校验装饰器 ====================

def validate_params(*required_params: str):
    """
    自动校验必填参数，缺失时抛出清晰的 RuntimeError。

    例:
        @validate_params("excel_path", "output_dir")
        async def process(excel_path=None, output_dir=None, **kwargs):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            for p in required_params:
                if not kwargs.get(p):
                    raise RuntimeError(f"缺少必填参数: {p}")
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            for p in required_params:
                if not kwargs.get(p):
                    raise RuntimeError(f"缺少必填参数: {p}")
            return await func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ==================== 自动重试装饰器 ====================

def auto_retry(max_retries: int = 3, base_delay: float = 2.0):
    """
    失败自动重试（指数退避）。

    例:
        @auto_retry(3)
        async def call_api(**kwargs):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        wait = base_delay * (2 ** (attempt - 1))
                        logger.warning(f"[重试] 第{attempt}次失败，{wait:.1f}秒后重试: {e}")
                        time.sleep(wait)
            raise last_error

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        wait = base_delay * (2 ** (attempt - 1))
                        logger.warning(f"[重试] 第{attempt}次失败，{wait:.1f}秒后重试: {e}")
                        await asyncio.sleep(wait)
            raise last_error

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ==================== 路径自动创建装饰器 ====================

def ensure_output_dir(output_key: str = "output_dir"):
    """
    自动确保输出目录存在。

    例:
        @ensure_output_dir("output_dir")
        async def process(output_dir=None, **kwargs):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            out = kwargs.get(output_key, "")
            if out:
                os.makedirs(out, exist_ok=True)
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            out = kwargs.get(output_key, "")
            if out:
                os.makedirs(out, exist_ok=True)
            return await func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator