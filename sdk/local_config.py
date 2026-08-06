# 本地配置管理
# 每个人电脑路径不一样，用这个读配置，不要在代码里写死路径
#
# 用法：
#   LocalConfig.get("download_dirs.default")  # 读全局配置
#   LocalConfig.get_for_user("zhangsan", "templates.finance.jd_sales_template")  # 按用户读
import os
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / "local_configs"
_cache_config = None


def _load_global_config():
    global _cache_config
    if _cache_config is not None:
        return _cache_config
    user_file = _CONFIG_DIR / "my_local.yaml"
    if user_file.exists():
        with open(user_file, 'r', encoding='utf-8') as f:
            _cache_config = yaml.safe_load(f) or {}
        return _cache_config
    example_file = _CONFIG_DIR / "example.local.yaml"
    if example_file.exists():
        with open(example_file, 'r', encoding='utf-8') as f:
            _cache_config = yaml.safe_load(f) or {}
    else:
        _cache_config = {}
    return _cache_config


def _get_nested(d, key_path):
    keys = key_path.split(".")
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


class LocalConfig:

    @staticmethod
    def get(key_path, default=None):
        # 读全局配置（my_local.yaml）
        cfg = _load_global_config()
        val = _get_nested(cfg, key_path)
        return val if val else default

    @staticmethod
    def get_path(key_path, default=None):
        # 返回Path对象
        val = LocalConfig.get(key_path, default)
        return Path(val) if val else None

    @staticmethod
    def get_for_user(username, key_path, default=None):
        # 按用户读，优先读用户在网页上填的配置
        # 没填的话回退到全局配置
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        try:
            from src.storage.user_config_manager import get_user_config
            val = get_user_config(username, key_path, default=None)
            if val:
                return val
        except Exception:
            pass
        return LocalConfig.get(key_path, default)

    @staticmethod
    def get_path_for_user(username, key_path, default=None):
        val = LocalConfig.get_for_user(username, key_path, default)
        return Path(val) if val else None

    @staticmethod
    def reload():
        global _cache_config
        _cache_config = None
        return _load_global_config()
