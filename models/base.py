# 实体类基类
# 所有数据表定义都继承BaseModel，用Column定义列
#
# 新增一张表的写法：
#   class MyTable(BaseModel):
#       table_name = "my_table"
#       id    = Column("id", "INT AUTO_INCREMENT PRIMARY KEY", "主键")
#       date  = Column("date", "DATE", "日期")
#       amount = Column("amount", "DECIMAL(15,2)", "金额")


def Column(name, type_str, comment=""):
    # 定义一列，返回一个带标记的类
    # type_str常用值：INT / VARCHAR(100) / DECIMAL(15,2) / DATE / DATETIME / TEXT
    return type(f"Col_{name}", (), {
        "column_name": name,
        "column_type": type_str,
        "comment": comment,
        "_is_column": True,
        "__module__": "models.base",
    })


class BaseModel:
    # 子类必须设置table_name
    table_name = "base_table"

    @classmethod
    def create_table(cls):
        # 快捷建表方法
        import sys
        from pathlib import Path
        if str(Path(__file__).resolve().parent.parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from sdk.mysql_sdk import MySQL
        return MySQL.create_table(cls)

    @classmethod
    def query(cls, **kwargs):
        # 快捷查询方法
        import sys
        from pathlib import Path
        if str(Path(__file__).resolve().parent.parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from sdk.mysql_sdk import MySQL
        return MySQL.query(cls, **kwargs)
