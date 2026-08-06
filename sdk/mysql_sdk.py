# 数据库工具包
# 把Excel存到MySQL、查询数据、自动建表
#
# 用法：
#   from sdk import MySQL
#   from models import JdSalesModel
#   MySQL.save("D:/下载/报表.xlsx", table=JdSalesModel)  # 存数据，表不存在自动建
#   data = MySQL.query(JdSalesModel, limit=100)           # 查数据
import sys
from pathlib import Path
from typing import List, Dict, Any, Type

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
from src.storage import storage_manager


class MySQL:

    @classmethod
    def create_table(cls, model_cls):
        # 根据实体类建表（表已存在就跳过）
        if not storage_manager.is_mysql_available:
            print("[MySQL] MySQL未连接，跳过建表")
            return False
        try:
            columns = _model_to_columns(model_cls)
            return storage_manager.mysql.create_business_table(model_cls.table_name, columns)
        except Exception as e:
            print(f"[MySQL] 建表失败: {e}")
            return False

    @classmethod
    def save(cls, excel_or_data, table, sheet=None, if_exists="append"):
        # 把Excel文件或DataFrame存到MySQL
        # table传实体类，比如 JdSalesModel
        # 表不存在会自动创建
        if not storage_manager.is_mysql_available:
            print("[MySQL] MySQL未连接，数据没保存")
            return 0

        cls.create_table(table)

        df = _to_dataframe(excel_or_data, sheet=sheet)
        if df is None or df.empty:
            print("[MySQL] 数据为空，跳过")
            return 0

        # 列名去空格
        df.columns = [str(c).strip() for c in df.columns]

        # 模糊匹配列名（Excel列名和实体类列名可能不完全一致）
        model_cols = _get_model_columns(table)
        rename_map = {}
        for m_col in model_cols:
            for df_col in df.columns:
                if _fuzzy_match(m_col, df_col):
                    rename_map[df_col] = m_col
                    break
        if rename_map:
            df = df.rename(columns=rename_map)

        # 只保留实体类里有的列
        common = [c for c in df.columns if c in model_cols]
        if not common:
            print(f"[MySQL] 没有匹配的列！实体类: {model_cols}")
            print(f"[MySQL] Excel列: {list(df.columns)[:10]}")
            return 0
        df = df[common]

        table_full = f"smart_agent_{table.table_name}"
        try:
            df.to_sql(name=table_full, con=storage_manager.mysql.engine,
                      if_exists=if_exists, index=False, chunksize=1000)
            print(f"[MySQL] 保存成功: {len(df)}行 -> {table_full}")
            return len(df)
        except Exception as e:
            print(f"[MySQL] 保存失败: {e}")
            return 0

    @classmethod
    def query(cls, table, where=None, limit=100, offset=0, order=None):
        # 查询数据，返回 list[dict]
        if not storage_manager.is_mysql_available:
            return []
        try:
            return storage_manager.mysql.query_business_table(
                table.table_name, limit=limit, offset=offset)
        except Exception as e:
            print(f"[MySQL] 查询失败: {e}")
            return []

    @classmethod
    def insert(cls, table, row):
        # 插一行数据
        if not storage_manager.is_mysql_available:
            return False
        try:
            cls.create_table(table)
            return storage_manager.mysql.insert_business_row(table.table_name, row)
        except Exception as e:
            print(f"[MySQL] 插入失败: {e}")
            return False


# 下面是内部辅助函数，一般不用管

def _model_to_columns(model_cls):
    cols = []
    for attr_name in dir(model_cls):
        attr = getattr(model_cls, attr_name)
        if isinstance(attr, type) and getattr(attr, "_is_column", False):
            cols.append({
                "name": attr.column_name,
                "type": attr.column_type,
                "comment": getattr(attr, "comment", ""),
            })
    if not any(c["name"] == "task_id" for c in cols):
        cols.append({"name": "task_id", "type": "VARCHAR(100)", "comment": "任务ID"})
    return cols


def _get_model_columns(model_cls):
    names = []
    for attr_name in dir(model_cls):
        attr = getattr(model_cls, attr_name)
        if isinstance(attr, type) and getattr(attr, "_is_column", False):
            names.append(attr.column_name)
    return names


def _fuzzy_match(model_col, df_col):
    # 模糊匹配列名：去掉下划线和空格后比较
    a = model_col.lower().replace("_", "").replace(" ", "")
    b = str(df_col).lower().replace("_", "").replace(" ", "")
    if a == b:
        return True
    return (len(a) > 1 and a in b) or (len(b) > 1 and b in a)


def _to_dataframe(src, sheet=None):
    if isinstance(src, pd.DataFrame):
        return src
    if isinstance(src, list):
        return pd.DataFrame(src)
    p = Path(src)
    if not p.exists():
        print(f"[MySQL] 文件不存在: {p}")
        return None
    if p.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(p, sheet_name=sheet or 0)
    if p.suffix.lower() == ".csv":
        return pd.read_csv(p)
    print(f"[MySQL] 不支持的格式: {p.suffix}")
    return None
