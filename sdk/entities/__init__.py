# -*- coding: utf-8 -*-
"""
实体类基础架构

设计理念：
- 每个任务/数据表对应一个实体类
- 实体类带 table_name 唯一标识
- 用 Column() 定义字段，兼容 mysql_sdk.py 的自动建表
- 装饰器 @register_entity 自动注册，新增实体只加文件不改核心代码

用法：
    from sdk.entities import register_entity, Column

    @register_entity("jd_ibay_sales")
    class JD_Ibay_Sales:
        table_name = "jd_ibay_sales"
        platform = "jd"          # 平台标识
        cookie_key = "jd_shop_ibay"  # 默认cookie_key

        order_id = Column("order_id", "VARCHAR(100)", "单据编号")
        amount = Column("amount", "DECIMAL(10,2)", "金额")

查询：
    from sdk.entities import get_entity, list_entities
    entity = get_entity("jd_ibay_sales")  # 获取实体类
    MySQL.save("data.xlsx", table=entity)  # 存数据，自动建表
"""
import sys
from pathlib import Path
import pkgutil
import importlib
from loguru import logger

# 实体类注册表
_ENTITIES = {}


def Column(name: str, col_type: str = "VARCHAR(255)", comment: str = ""):
    """
    创建一个列类型（类），兼容 mysql_sdk.py 的 isinstance(attr, type) 检查

    Args:
        name: 列名（数据库字段名）
        col_type: 数据库类型，如 VARCHAR(100)、DECIMAL(10,2)、DATETIME
        comment: 列注释
    """
    return type(f"Col_{name}", (), {
        "_is_column": True,
        "column_name": name,
        "column_type": col_type,
        "comment": comment,
    })


def register_entity(table_name: str):
    """
    实体类注册装饰器

    用法：
        @register_entity("jd_ibay_sales")
        class JD_Ibay_Sales:
            table_name = "jd_ibay_sales"
            ...
    """
    def decorator(cls):
        cls.table_name = table_name
        _ENTITIES[table_name] = cls
        return cls
    return decorator


def get_entity(table_name: str):
    """获取已注册的实体类"""
    return _ENTITIES.get(table_name)


def list_entities():
    """列出所有已注册的实体类 {table_name: cls}"""
    return dict(_ENTITIES)


def init_entities():
    """
    启动时自动扫描 sdk/entities/ 下所有模块并注册

    在应用启动时调用：
        from sdk.entities import init_entities
        init_entities()
    """
    import sdk.entities as pkg
    for _, mod_name, _ in pkgutil.iter_modules(pkg.__path__):
        if mod_name.startswith("_"):
            continue
        try:
            importlib.import_module(f"sdk.entities.{mod_name}")
        except Exception as e:
            logger.warning(f"[Entities] 加载 {mod_name} 失败: {e}")
    logger.info(f"[Entities] 已注册 {len(_ENTITIES)} 个实体类: {list(_ENTITIES.keys())}")
