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
        self.jwt_expire_hours = 24

        # JWT secret: 优先从环境变量读，其次从文件读，都没有才生成并持久化
        # 这样重启/多worker之间 secret 保持一致，用户不会被踢下线
        self.jwt_secret = os.environ.get("JWT_SECRET", "")
        if not self.jwt_secret:
            secret_file = self.data_dir / ".jwt_secret"
            if secret_file.exists():
                self.jwt_secret = secret_file.read_text(encoding="utf-8").strip()
            else:
                self.jwt_secret = secrets.token_hex(32)
                secret_file.write_text(self.jwt_secret, encoding="utf-8")

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

    # 允许的角色白名单
    VALID_ROLES = ("admin", "user")
    # 默认密码重置规则：新密码 = 用户名 + "123"
    @staticmethod
    def default_reset_password(username: str) -> str:
        return f"{username}123"

    # ==================== 用户管理 ====================

    def create_user(
        self,
        username: str,
        password: str,
        department: str,
        role: str = "user",
        creator_role: str = None,
        creator_department: str = None,
    ) -> bool:
        """
        创建用户（支持后端双重权限校验）

        Args:
            creator_role:       创建者的角色（None=超管，不受以下两条约束）
            creator_department: 创建者所在部门（当 creator_role != 'admin' 时生效）

        后端约束（就算前端绕过/没隐藏按钮，这里也会硬拒）：
          1. 必填校验：用户名/密码/部门 不能为空；密码≥4位
          2. 角色白名单：role 必须在 VALID_ROLES（admin/user）内，非法值降级为 user
          3. 提权拦截：非 admin 创建者 → 禁止创建/升级 role=admin 的账号，强制降为 user
          4. 部门隔离：非 admin 创建者 → 只能给自己所在部门建人，跨部门返回 False
          5. 唯一性：用户名已存在 → False
        """
        # ---- 1) 必填 + 基础长度校验 ----
        if not username or not password or not department:
            logger.warning(f"创建用户失败: 必填字段为空 (username={username!r}, dept={department!r})")
            return False
        if len(password) < 4:
            logger.warning(f"创建用户失败: 密码太短 (<4位) user={username}")
            return False
        if len(username) > 32 or len(department) > 32:
            logger.warning(f"创建用户失败: 用户名/部门名太长 user={username}")
            return False

        # ---- 2) role 白名单（非法值降级为 user）----
        if role not in self.VALID_ROLES:
            logger.info(f"创建用户 user={username}: 非法 role={role!r}，降级为 user")
            role = "user"

        # ---- 3) 提权拦截：非 admin 创建者不能建 admin 账号 ----
        if creator_role and creator_role != "admin" and role == "admin":
            logger.warning(
                f"提权拦截：创建者({creator_role})试图创建 role=admin 的账号 user={username}，"
                f"已强制降级为 user"
            )
            role = "user"

        # ---- 4) 部门隔离：非 admin 只能给自己部门建人 ----
        if creator_role and creator_role != "admin" and creator_department:
            if department != creator_department:
                logger.warning(
                    f"部门隔离：创建者(dept={creator_department})试图给其他部门建人 "
                    f"(target={department})，已拒绝"
                )
                return False

        # ---- 5) 唯一性 + 落盘 ----
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
        logger.info(f"用户已创建: {username} -> dept={department}, role={role}"
                    + (f" (by {creator_role}/{creator_department})" if creator_role else ""))
        return True

    def reset_password(self, username: str, new_password: str = None) -> Optional[str]:
        """
        重置用户密码。new_password 缺省时按默认规则生成（用户名+123）。
        返回设置的明文密码（方便前端提示用户），失败返回 None。
        """
        if not username or username == "":
            return None
        if new_password is None:
            new_password = self.default_reset_password(username)
        if len(new_password) < 4:
            return None
        users = self._load_json(self.users_file)
        if username not in users:
            return None
        users[username]["password"] = self._hash_password(new_password)
        users[username]["updated_at"] = datetime.now().isoformat()
        self._save_json(self.users_file, users)
        logger.info(f"用户密码已重置: {username}")
        return new_password

    def delete_user(self, username: str, deleter_role: str = None) -> bool:
        """
        删除用户。
        规则：admin 账号永远不可删（防锁死自己）；
              非 admin 删除者想删 admin → 拒绝（防普通用户越权删管理员）。
        """
        users = self._load_json(self.users_file)
        if username not in users:
            return False
        target_role = users[username].get("role", "user")
        # 1) admin 账号永远不可删
        if username == "admin":
            logger.warning(f"试图删除默认admin账号，拒绝")
            return False
        # 2) 非 admin 删除者 想删 role=admin 的账号 → 拒绝
        if deleter_role and deleter_role != "admin" and target_role == "admin":
            logger.warning(f"越权：deleter={deleter_role} 试图删除 admin-role user={username}，拒绝")
            return False
        del users[username]
        self._save_json(self.users_file, users)
        logger.info(f"用户已删除: {username}")
        return True

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
