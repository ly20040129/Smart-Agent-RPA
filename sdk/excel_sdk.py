# Excel数据清洗工具
# 下载的Excel经常有问题：列名乱、有空行、金额带符号、日期格式不对
# 这个工具帮你自动处理
#
# 用法：
#   from sdk import ExcelClean
#   df = ExcelClean.load_and_clean("D:/下载/账单.xlsx")  # 读取并自动清洗
#   df = ExcelClean.filter(df, "金额 > 1000")             # 筛选
#   ExcelClean.save(df, "D:/结果/处理后.xlsx")            # 保存
# 后续可以持续封装新方法

from pathlib import Path
from typing import List
import pandas as pd


class ExcelClean:

    @classmethod
    def load_and_clean(cls, file_path, sheet=None, skip_rows=0, header_row=None):
        # 读Excel并做基础清洗：去空行、去重复、格式化日期和金额
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")

        if p.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(p, sheet_name=sheet or 0, header=header_row, skiprows=skip_rows)
        elif p.suffix.lower() == ".csv":
            df = pd.read_csv(p, header=header_row, skiprows=skip_rows)
        else:
            raise ValueError(f"不支持的格式: {p.suffix}")

        # 列名去空格
        df.columns = [str(c).strip() for c in df.columns]
        # 去全空行/列
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        # 去重复
        df = df.drop_duplicates()

        # 自动格式化每列
        for col in df.columns:
            df[col] = cls._clean_column(df[col])

        print(f"[ExcelClean] 清洗完成: {len(df)}行 x {len(df.columns)}列  {p.name}")
        return df

    @classmethod
    def match_template(cls, df, template_path):
        # 用模板Excel对齐列名和顺序
        if template_path is None:
            return df
        p = Path(template_path)
        if not p.exists():
            print(f"[ExcelClean] 模板不存在: {p}，跳过")
            return df
        tmpl_df = pd.read_excel(p, sheet_name=0)
        tmpl_cols = [str(c).strip() for c in tmpl_df.columns]

        new_df = pd.DataFrame()
        used = set()
        for tcol in tmpl_cols:
            found = None
            for dcol in df.columns:
                if dcol in used:
                    continue
                a = tcol.lower().replace("_", "").replace(" ", "")
                b = str(dcol).lower().replace("_", "").replace(" ", "")
                if a == b or (len(a) > 2 and (a in b or b in a)):
                    found = dcol
                    break
            if found:
                new_df[tcol] = df[found].values
                used.add(found)
            else:
                new_df[tcol] = None

        for dcol in df.columns:
            if dcol not in used:
                new_df[dcol] = df[dcol].values

        print(f"[ExcelClean] 模板匹配: {len(tmpl_cols)}模板列 -> 匹配{len(used)}列")
        return new_df

    @classmethod
    def filter(cls, df, query_str):
        # 按条件筛选，比如 filter(df, "订单状态 == '已支付'")
        try:
            return df.query(query_str)
        except Exception as e:
            print(f"[ExcelClean] 筛选失败 '{query_str}': {e}")
            return df

    @classmethod
    def group_sum(cls, df, by, sum_cols):
        # 按列分组求和，比如 group_sum(df, by="日期", sum_cols=["销售额"])
        for c in sum_cols:
            if c not in df.columns:
                print(f"[ExcelClean] 列不存在: {c}")
                return df
        return df.groupby(by, dropna=False)[sum_cols].sum().reset_index()

    @classmethod
    def save(cls, df, output_path, sheet_name="Sheet1"):
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(p, sheet_name=sheet_name, index=False)
        print(f"[ExcelClean] 已保存: {p}")
        return str(p)

    @classmethod
    def _clean_column(cls, series):
        # 自动识别金额列（带¥符号的转成数字）和日期列
        if series.dtype == object:
            try:
                if series.astype(str).str.contains(r"[¥$,，]").any():
                    cleaned = (series.astype(str)
                               .str.replace("¥", "", regex=False)
                               .str.replace("￥", "", regex=False)
                               .str.replace(",", "", regex=False)
                               .str.replace("，", "", regex=False)
                               .str.strip())
                    return pd.to_numeric(cleaned, errors="ignore")
            except Exception:
                pass
            try:
                return pd.to_datetime(series, errors="ignore")
            except Exception:
                pass
        return series
