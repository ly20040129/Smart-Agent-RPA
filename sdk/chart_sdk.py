# 图表工具
# 从MySQL或Excel读数据，画折线图/柱状图/饼图，保存成PNG
#
# 用法：
#   from sdk import Chart
#   from models import JdSalesModel
#   Chart.line(JdSalesModel, x="sale_date", y="actual_amt", title="每日销售额")
#   Chart.bar(JdSalesModel, x="sale_date", y="qty", title="每日订单数")
#   Chart.pie(JdSalesModel, label_col="order_status", value_col="actual_amt")
from pathlib import Path
from typing import Union, List

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # 没有显示器也能画图
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 中文显示
rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


class Chart:

    @classmethod
    def line(cls, data_source, x, y, save_to=None, title=None, where=None, limit=10000):
        # 折线图
        # data_source可以传实体类、DataFrame或Excel路径
        df = _to_dataframe(data_source, where=where, limit=limit)
        if df is None or df.empty:
            print("[Chart] 没有数据")
            return None
        ys = [y] if isinstance(y, str) else y
        fig, ax = plt.subplots(figsize=(12, 5))
        for col in ys:
            if col not in df.columns:
                print(f"[Chart] 列不存在: {col}")
                continue
            ax.plot(df[x].astype(str), pd.to_numeric(df[col], errors="coerce"),
                    marker="o", linewidth=1.5, label=col)
        ax.set_title(title or f"{x} vs {y}", fontsize=14)
        ax.set_xlabel(x, fontsize=12)
        ax.legend()
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        plt.tight_layout()
        return cls._save(fig, save_to, f"line_{x}_{y}")

    @classmethod
    def bar(cls, data_source, x, y, save_to=None, title=None, stacked=False, where=None, limit=10000):
        # 柱状图
        df = _to_dataframe(data_source, where=where, limit=limit)
        if df is None or df.empty:
            print("[Chart] 没有数据")
            return None
        ys = [y] if isinstance(y, str) else y
        fig, ax = plt.subplots(figsize=(12, 5))
        for col in ys:
            if col not in df.columns:
                print(f"[Chart] 列不存在: {col}")
                continue
            ax.bar(df[x].astype(str), pd.to_numeric(df[col], errors="coerce"),
                   label=col, alpha=0.85)
        ax.set_title(title or f"{x} - {y} 柱状图", fontsize=14)
        ax.set_xlabel(x, fontsize=12)
        ax.legend()
        ax.grid(alpha=0.3, axis="y")
        fig.autofmt_xdate()
        plt.tight_layout()
        return cls._save(fig, save_to, f"bar_{x}_{y}")

    @classmethod
    def pie(cls, data_source, label_col, value_col, save_to=None, title=None, where=None, limit=10000):
        # 饼图：按label_col分组对value_col求和
        df = _to_dataframe(data_source, where=where, limit=limit)
        if df is None or df.empty:
            print("[Chart] 没有数据")
            return None
        grouped = df.groupby(label_col, dropna=False)[value_col].sum().reset_index()
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.pie(grouped[value_col].values,
               labels=[str(x) for x in grouped[label_col].values],
               autopct="%1.1f%%", startangle=90)
        ax.set_title(title or f"{label_col} - {value_col} 占比", fontsize=14)
        ax.axis("equal")
        plt.tight_layout()
        return cls._save(fig, save_to, f"pie_{label_col}_{value_col}")

    @classmethod
    def _save(cls, fig, save_to, default_name):
        # 保存图片，没指定路径就存到local_output/charts/
        import sys as _s
        from pathlib import Path as _P
        proj = _P(_s.argv[0]).resolve().parent
        if save_to is None:
            try:
                from sdk.local_config import LocalConfig
                base = LocalConfig.get_path("chart_dir") or proj / "local_output" / "charts"
            except Exception:
                base = proj / "local_output" / "charts"
            base = _P(base)
            base.mkdir(parents=True, exist_ok=True)
            save_to = str(base / f"{default_name}.png")
        p = _P(save_to)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(p), dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[Chart] 图表已保存: {p}")
        return str(p)


def _to_dataframe(src, where=None, limit=10000):
    # 把数据源统一转成DataFrame
    # 支持实体类、DataFrame、Excel文件路径
    if isinstance(src, pd.DataFrame):
        return src

    if isinstance(src, (str, Path)):
        p = Path(src)
        if p.exists():
            if p.suffix.lower() in (".xlsx", ".xls"):
                return pd.read_excel(p)
            if p.suffix.lower() == ".csv":
                return pd.read_csv(p)

    # 实体类（有table_name属性的）
    table_name = getattr(src, "table_name", None)
    if table_name:
        import sys as _s
        from pathlib import Path as _P
        proj = _P(_s.argv[0]).resolve().parent
        if str(proj) not in _s.path:
            _s.path.insert(0, str(proj))
        from src.storage import storage_manager
        if storage_manager.is_mysql_available:
            rows = storage_manager.mysql.query_business_table(table_name, limit=limit)
            return pd.DataFrame(rows)

    print(f"[Chart] 无法识别的数据源: {type(src)}")
    return None
