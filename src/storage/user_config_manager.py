# -*- coding: utf-8 -*-
"""
👤 用户配置管理器
==================

每个用户的本地配置（路径、上传的文件）存在 data/user_configs/{username}.json

API：
  - get_user_config(username, key)          → 读取某个配置项
  - set_user_config(username, key, value)   → 保存某个配置项
  - get_all_user_config(username)           → 读取该用户所有配置
  - save_uploaded_file(username, key, file) → 保存上传的文件，返回路径
  - get_config_schema()                     → 读取配置项定义（管理员维护的schema）
"""
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "data" / "user_configs"
_SCHEMA_FILE = _PROJECT_ROOT / "local_configs" / "config_schema.yaml"
_UPLOAD_DIR = _PROJECT_ROOT / "data" / "user_uploads"


def _ensure_dirs():
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _user_config_path(username: str) -> Path:
    return _CONFIG_DIR / f"{username}.json"


def _load_user_config(username: str) -> dict:
    """加载用户的全部配置"""
    p = _user_config_path(username)
    if p.exists():
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"values": {}, "uploaded_files": {}}


def _save_user_config(username: str, config: dict):
    _ensure_dirs()
    p = _user_config_path(username)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ============================================================
# 公开 API
# ============================================================
def get_config_schema() -> dict:
    """读取配置项定义（管理员在 config_schema.yaml 维护）"""
    if not _SCHEMA_FILE.exists():
        return {"groups": []}
    with open(_SCHEMA_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {"groups": []}


def get_all_user_config(username: str) -> dict:
    """读取该用户的全部配置（values + uploaded_files）"""
    return _load_user_config(username)


def get_user_config(username: str, key_path: str, default: Any = None) -> Any:
    """
    读取某个配置项（带默认值回退）
    优先级：用户配置 > schema默认值 > default参数
    """
    config = _load_user_config(username)
    values = config.get("values", {})

    # 点号路径取值
    keys = key_path.split(".")
    cur = values
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            cur = None
            break

    if cur is not None and cur != "":
        return cur

    # 回退到schema默认值
    default_from_schema = _get_schema_default(key_path)
    return default_from_schema if default_from_schema else default


def set_user_config(username: str, key_path: str, value: Any):
    """保存某个配置项"""
    config = _load_user_config(username)
    values = config.setdefault("values", {})
    keys = key_path.split(".")
    cur = values
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value
    _save_user_config(username, config)


def batch_set_user_config(username: str, items: Dict[str, Any]):
    """批量保存配置项 {key: value}"""
    config = _load_user_config(username)
    values = config.setdefault("values", {})
    for key_path, value in items.items():
        keys = key_path.split(".")
        cur = values
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = value
    _save_user_config(username, config)


def save_uploaded_file(username: str, key_path: str, file_content: bytes,
                       original_filename: str) -> str:
    """
    保存用户上传的文件，返回保存后的相对路径。
    文件存到 data/user_uploads/{username}/{key最后一段}_{原文件名}
    """
    _ensure_dirs()
    user_upload_dir = _UPLOAD_DIR / username
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    # 用key最后一段做前缀，避免冲突
    prefix = key_path.split(".")[-1]
    # 保留原扩展名
    ext = Path(original_filename).suffix
    safe_name = f"{prefix}{ext}"
    save_path = user_upload_dir / safe_name

    with open(save_path, 'wb') as f:
        f.write(file_content)

    # 返回绝对路径（代码里直接用）
    abs_path = str(save_path.resolve())

    # 一次读写落盘：uploaded_files 记来源，values 让 get_user_config 能直接读到。
    # 注意别拆成两次读改写：下面那步会重新从盘上读，把 uploaded_files 覆盖掉，
    # 导致前端「✓ 已上传」的标记始终不亮。
    config = _load_user_config(username)
    config.setdefault("uploaded_files", {})[key_path] = abs_path
    values = config.setdefault("values", {})
    keys = key_path.split(".")
    cur = values
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = abs_path
    _save_user_config(username, config)

    return abs_path


def _get_schema_default(key_path: str) -> Any:
    """从schema里找某个key的default值"""
    schema = get_config_schema()
    for group in schema.get("groups", []):
        for item in group.get("items", []):
            if item.get("key") == key_path:
                return item.get("default", "")
    return None


def get_user_config_with_schema(username: str) -> List[dict]:
    """
    返回带schema信息的配置列表（给Web前端渲染表单用）
    每个item带当前值
    """
    schema = get_config_schema()
    config = _load_user_config(username)
    values = config.get("values", {})
    uploaded = config.get("uploaded_files", {})

    result = []
    for group in schema.get("groups", []):
        group_items = []
        for item in group.get("items", []):
            key = item["key"]
            # 取当前值
            cur_val = values
            for k in key.split("."):
                if isinstance(cur_val, dict) and k in cur_val:
                    cur_val = cur_val[k]
                else:
                    cur_val = None
                    break
            item_copy = dict(item)
            item_copy["current_value"] = cur_val if cur_val else item.get("default", "")
            item_copy["is_uploaded"] = key in uploaded
            group_items.append(item_copy)
        result.append({
            "name": group.get("name", ""),
            "label": group.get("label", ""),
            "items": group_items,
        })
    return result
