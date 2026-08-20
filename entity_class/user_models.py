# 用户和部门的表定义
# 目前用户数据存在JSON里，这里预留了MySQL表定义
# 后续用户多了可以迁移到MySQL
from entity_class.base import BaseModel, Column


class UserTable(BaseModel):
    table_name = "sys_users"
    id            = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    username      = Column("username", "VARCHAR(100) UNIQUE", "用户名")
    password_hash = Column("password_hash", "VARCHAR(300)", "密码哈希")
    real_name     = Column("real_name", "VARCHAR(100)", "姓名")
    department_id = Column("department_id", "VARCHAR(50)", "部门ID")
    role          = Column("role", "VARCHAR(20)", "角色")
    email         = Column("email", "VARCHAR(200)", "邮箱")
    phone         = Column("phone", "VARCHAR(50)", "手机")
    status        = Column("status", "TINYINT(1) DEFAULT 1", "状态")
    created_at    = Column("created_at", "DATETIME", "创建时间")
    last_login_at = Column("last_login_at", "DATETIME", "最后登录")


class DepartmentTable(BaseModel):
    table_name = "sys_departments"
    id          = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    dept_code   = Column("dept_code", "VARCHAR(50) UNIQUE", "部门编码")
    dept_name   = Column("dept_name", "VARCHAR(100)", "部门名称")
    parent_code = Column("parent_code", "VARCHAR(50)", "上级部门")
    leader      = Column("leader", "VARCHAR(100)", "负责人")
    description = Column("description", "VARCHAR(500)", "描述")
    status      = Column("status", "TINYINT(1) DEFAULT 1", "状态")
