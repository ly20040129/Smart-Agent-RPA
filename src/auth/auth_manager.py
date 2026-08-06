# -*- coding: utf-8 -*-
"""
部门权限管理器

功能：
1. 用户管理 - 新增/删除/修改账号
2. 部门管理 - 部门隔离，用户只能看本部门任务
3. JWT认证 - 登录态验证
4. 任务部门绑定 - 每个任务绑定到一个部门
"""
import json
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
from loguru import logger

try:
    import jwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False


class AuthManager:
    """部门权限管理器"""

    def __init__(self):
        self.data_dir = Path("data/auth")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_file = self.data_dir / "users.json"
        self.departments_file = self.data_dir / "departments.json"
        self.jwt_secret = secrets.token_hex(32)
        self.jwt_expire_hours = 24

        self._init_default_data()

    def _init_default_data(self):
        """初始化默认数据"""
        if not self.users_file.exists():
            # 默认管理员账号
            default_users = {
                "admin": {
                    "username": "admin",
                    "password": self._hash_password("admin123"),
                    "department": "admin",
                    "role": "admin",
                    "created_at": datetime.now().isoformat()
                }
            }
            self._save_json(self.users_file, default_users)

        if not self.departments_file.exists():
            default_depts = {
                "admin": {"name": "系统管理", "description": "管理员部门", "color": "#008080"},
                "finance": {"name": "财务部", "description": "财务相关任务", "color": "#e74c3c"},
                "business": {"name": "业务部", "description": "业务相关任务", "color": "#3498db"},
                "operations": {"name": "运营部", "description": "运营相关任务", "color": "#f39c12"}
            }
            self._save_json(self.departments_file, default_depts)

    def _hash_password(self, password: str) -> str:
        """密码哈希"""
        return hashlib.sha256(password.encode()).hexdigest()

    def _save_json(self, path: Path, data: dict):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    # ==================== 用户管理 ====================

    def create_user(self, username: str, password: str, department: str, role: str = "user") -> bool:
        """创建用户"""
        users = self._load_json(self.users_file)
        if username in users:
            logger.warning(f"用户已存在: {username}")
            return False
        users[username] = {
            "username": username,
            "password": self._hash_password(password),
            "department": department,
            "role": role,
            "created_at": datetime.now().isoformat()
        }
        self._save_json(self.users_file, users)
        logger.info(f"用户已创建: {username} -> {department}")
        return True

    def delete_user(self, username: str) -> bool:
        """删除用户"""
        if username == "admin":
            return False
        users = self._load_json(self.users_file)
        if username in users:
            del users[username]
            self._save_json(self.users_file, users)
            logger.info(f"用户已删除: {username}")
            return True
        return False

    def update_user(self, username: str, **kwargs) -> bool:
        """更新用户信息"""
        users = self._load_json(self.users_file)
        if username not in users:
            return False
        for key, value in kwargs.items():
            if key == "password":
                users[username][key] = self._hash_password(value)
            else:
                users[username][key] = value
        self._save_json(self.users_file, users)
        return True

    def list_users(self) -> List[dict]:
        """列出所有用户"""
        users = self._load_json(self.users_file)
        result = []
        for u, info in users.items():
            info_copy = {k: v for k, v in info.items() if k != 'password'}
            result.append(info_copy)
        return result

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        """验证登录"""
        users = self._load_json(self.users_file)
        if username not in users:
            return None
        if users[username]['password'] != self._hash_password(password):
            return None

        user = {k: v for k, v in users[username].items() if k != 'password'}
        logger.info(f"用户登录成功: {username}")
        return user

    def generate_token(self, user: dict) -> str:
        """生成JWT Token"""
        if not HAS_JWT:
            # 无JWT库时，用简单base64编码
            import base64
            payload = json.dumps({
                "username": user["username"],
                "department": user["department"],
                "role": user["role"],
                "exp": (datetime.now() + timedelta(hours=self.jwt_expire_hours)).timestamp()
            })
            return base64.b64encode(payload.encode()).decode()

        payload = {
            "username": user["username"],
            "department": user["department"],
            "role": user["role"],
            "exp": datetime.now() + timedelta(hours=self.jwt_expire_hours)
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> Optional[dict]:
        """验证Token"""
        if not token:
            return None
        try:
            if not HAS_JWT:
                import base64
                payload = base64.b64decode(token.encode()).decode()
                data = json.loads(payload)
                if data.get("exp", 0) < datetime.now().timestamp():
                    return None
                return data
            else:
                return jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except Exception:
            return None

    # ==================== 部门管理 ====================

    def create_department(self, dept_id: str, name: str, description: str = "", color: str = "#008080") -> bool:
        """创建部门"""
        depts = self._load_json(self.departments_file)
        if dept_id in depts:
            return False
        depts[dept_id] = {"name": name, "description": description, "color": color}
        self._save_json(self.departments_file, depts)
        return True

    def delete_department(self, dept_id: str) -> bool:
        """删除部门"""
        if dept_id == "admin":
            return False
        depts = self._load_json(self.departments_file)
        if dept_id in depts:
            del depts[dept_id]
            self._save_json(self.departments_file, depts)
            return True
        return False

    def list_departments(self) -> List[dict]:
        """列出所有部门"""
        depts = self._load_json(self.departments_file)
        return [{"id": k, **v} for k, v in depts.items()]

    def get_department(self, dept_id: str) -> Optional[dict]:
        """获取部门信息"""
        depts = self._load_json(self.departments_file)
        return depts.get(dept_id)


# 全局单例
auth_manager = AuthManager()
