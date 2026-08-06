# -*- coding: utf-8 -*-
"""
模板管理器 - 管理用户的Excel模板文件

模板存储结构：
data/templates/
  ├── {username}/
  │   ├── template1.xlsx
  │   ├── template2.xlsx
  │   └── templates_meta.json  # 模板元数据索引
"""
import os
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "data" / "templates"


class TemplateManager:
    """模板管理器"""
    
    def __init__(self):
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    
    def _get_user_dir(self, username: str) -> Path:
        """获取用户模板目录"""
        user_dir = TEMPLATES_DIR / username
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def _get_meta_path(self, username: str) -> Path:
        """获取模板元数据文件路径"""
        return self._get_user_dir(username) / "templates_meta.json"
    
    def _load_meta(self, username: str) -> Dict:
        """加载模板元数据"""
        meta_path = self._get_meta_path(username)
        if meta_path.exists():
            with open(meta_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"templates": []}
    
    def _save_meta(self, username: str, meta: Dict):
        """保存模板元数据"""
        meta_path = self._get_meta_path(username)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    
    def list_templates(self, username: str) -> List[Dict[str, Any]]:
        """列出用户的所有模板"""
        meta = self._load_meta(username)
        return meta.get("templates", [])
    
    def get_template(self, username: str, template_id: str) -> Optional[Dict[str, Any]]:
        """获取指定模板"""
        meta = self._load_meta(username)
        for t in meta.get("templates", []):
            if t["id"] == template_id:
                return t
        return None
    
    def find_by_name(self, username: str, name: str) -> Optional[Dict[str, Any]]:
        """按名称查找模板"""
        meta = self._load_meta(username)
        for t in meta.get("templates", []):
            if t["name"] == name:
                return t
        return None
    
    def upload_template(self, username: str, name: str, file_path: str, 
                        description: str = "", template_type: str = "excel") -> Dict[str, Any]:
        """上传/保存模板"""
        import uuid
        
        user_dir = self._get_user_dir(username)
        ext = Path(file_path).suffix
        template_id = str(uuid.uuid4())[:8]
        
        # 复制文件到模板目录
        dest_filename = f"{template_id}{ext}"
        dest_path = user_dir / dest_filename
        shutil.copy2(file_path, dest_path)
        
        # 保存元数据
        meta = self._load_meta(username)
        template_info = {
            "id": template_id,
            "name": name,
            "description": description,
            "type": template_type,
            "filename": dest_filename,
            "original_name": Path(file_path).name,
            "size": dest_path.stat().st_size,
            "created_at": datetime.now().isoformat()
        }
        meta["templates"].append(template_info)
        self._save_meta(username, meta)
        
        logger.info(f"模板已保存: {username}/{name} ({dest_filename})")
        return template_info
    
    def delete_template(self, username: str, template_id: str) -> bool:
        """删除模板"""
        meta = self._load_meta(username)
        templates = meta.get("templates", [])
        
        target = None
        for t in templates:
            if t["id"] == template_id:
                target = t
                break
        
        if not target:
            return False
        
        # 删除文件
        user_dir = self._get_user_dir(username)
        file_path = user_dir / target["filename"]
        if file_path.exists():
            file_path.unlink()
        
        # 更新元数据
        meta["templates"] = [t for t in templates if t["id"] != template_id]
        self._save_meta(username, meta)
        
        logger.info(f"模板已删除: {username}/{target['name']}")
        return True
    
    def get_template_path(self, username: str, template_id: str) -> Optional[Path]:
        """获取模板文件的实际路径"""
        template = self.get_template(username, template_id)
        if not template:
            return None
        user_dir = self._get_user_dir(username)
        path = user_dir / template["filename"]
        return path if path.exists() else None
    
    def get_template_by_name(self, username: str, name: str) -> Optional[Path]:
        """按名称获取模板路径"""
        template = self.find_by_name(username, name)
        if not template:
            return None
        return self.get_template_path(username, template["id"])
