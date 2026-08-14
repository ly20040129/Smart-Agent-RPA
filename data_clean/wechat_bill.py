# -*- coding: utf-8 -*-
"""
公众号资金账单 - 数据清洗逻辑

输入：微信支付下载的资金账单Excel（业务明细）
处理：
  - 识别表头行（微信账单前面常有几行说明文字）
  - 列名中文化
  - 筛选：收支类型=收入 → 销售额；收支类型=支出 且 业务类型∈{退款,扣除交易手续费} → 退款额
  - 汇总并输出清洗后Excel
输出：清洗后Excel文件路径
"""
import os
from pathlib import Path
from datetime import datetime
from loguru import logger


def _find_header_row(df_raw):
    """微信账单Excel开头有说明行，尝试找到真正的表头行"""
    import pandas as pd
    # 找包含"收支类型"或"业务类型"或"金额"的行
    for i in range(min(20, len(df_raw))):
        row_vals = [str(v).strip() for v in df_raw.iloc[i].tolist() if str(v).strip()]
        joined = "|".join(row_vals)
        if "收支类型" in joined or "业务类型" in joined or ("金额" in joined and "时间" in joined):
            return i
    return 0


def _read_excel_smart(file_path):
    """智能读取微信账单，支持 .xlsx / .xls / .csv 格式"""
    import pandas as pd
    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.csv':
        for enc in ['utf-8-sig', 'utf-8', 'gbk', 'gb18030']:
            try:
                raw = pd.read_csv(file_path, header=None, dtype=str, encoding=enc)
                header_idx = _find_header_row(raw)
                df = pd.read_csv(file_path, header=header_idx, dtype=str, encoding=enc)
                logger.info(f"[wechat_bill] CSV读取成功(encoding={enc})，检测表头行: 第{header_idx}行")
                df = df.dropna(axis=0, how='all').dropna(axis=1, how='all')
                return df
            except Exception:
                continue
        raise RuntimeError(f"CSV文件读取失败，请检查编码: {file_path}")
    else:
        raw = pd.read_excel(file_path, header=None, dtype=str)
        header_idx = _find_header_row(raw)
        logger.info(f"[wechat_bill] 检测表头行: 第{header_idx}行")
        df = pd.read_excel(file_path, header=header_idx, dtype=str)
        df = df.dropna(axis=0, how='all').dropna(axis=1, how='all')
        return df


def process(input_file: str, context: dict = None, params: dict = None, **kwargs):
    """
    清洗公众号资金账单数据

    Args:
        input_file: 输入的Excel文件路径
        context: 任务上下文（含user_params等）
        params: 额外参数

    Returns:
        清洗后的输出文件路径
    """
    import pandas as pd

    logger.info(f"[wechat_bill] 开始清洗: {input_file}")
    if not os.path.exists(input_file):
        raise FileNotFoundError(input_file)

    # 1. 读取
    df = _read_excel_smart(input_file)
    logger.info(f"[wechat_bill] 有效数据: {len(df)} 行 x {len(df.columns)} 列")
    logger.info(f"[wechat_bill] 列名: {list(df.columns)}")

    # 2. 列名规范化（去空格、去换行）
    df.columns = [str(c).replace("\n", "").replace(" ", "").strip() for c in df.columns]

    # 3. 找关键列名（中文列名变体可能很多）
    def _find_col(keywords):
        for kw in keywords:
            for col in df.columns:
                if kw in col:
                    return col
        return None

    col_income_type = _find_col(["收支类型"])
    col_biz_type = _find_col(["业务类型"])
    col_amount = _find_col(["金额(元)", "金额", "收入金额", "支出金额"])
    col_time = _find_col(["交易时间", "记账时间", "时间", "日期"])
    col_order = _find_col(["商户订单号", "订单号", "单号"])

    logger.info(f"[wechat_bill] 关键列映射: 收支类型={col_income_type}, 业务类型={col_biz_type}, 金额={col_amount}, 时间={col_time}")

    # 4. 金额转数值
    if col_amount:
        df[col_amount] = (
            df[col_amount]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("¥", "", regex=False)
            .str.replace("￥", "", regex=False)
            .str.strip()
        )
        df["_金额数值"] = pd.to_numeric(df[col_amount], errors="coerce").fillna(0.0)
    else:
        df["_金额数值"] = 0.0

    # 5. 识别销售额（收支类型=收入）
    sales_mask = pd.Series([False] * len(df))
    if col_income_type:
        sales_mask = df[col_income_type].astype(str).str.contains("收入", na=False)
    sales_amount = float(df.loc[sales_mask, "_金额数值"].sum())
    logger.info(f"[wechat_bill] 销售额记录: {int(sales_mask.sum())} 行，合计 = {sales_amount:.2f}")

    # 6. 识别退款额（收支类型=支出，且业务类型是退款/手续费）
    refund_mask = pd.Series([False] * len(df))
    if col_income_type and col_biz_type:
        refund_mask = (
            df[col_income_type].astype(str).str.contains("支出", na=False)
            & df[col_biz_type].astype(str).apply(
                lambda x: ("退款" in str(x)) or ("手续费" in str(x)) or ("扣除" in str(x))
            )
        )
    elif col_biz_type:
        refund_mask = df[col_biz_type].astype(str).apply(
            lambda x: ("退款" in str(x)) or ("手续费" in str(x))
        )
    refund_amount = float(df.loc[refund_mask, "_金额数值"].sum())
    logger.info(f"[wechat_bill] 退款/手续费记录: {int(refund_mask.sum())} 行，合计 = {refund_amount:.2f}")

    # 7. 重命名列（英文→中文，输出给用户）
    rename_map = {}
    if col_time and "日期" not in col_time:
        rename_map[col_time] = "交易时间"
    if col_order:
        rename_map[col_order] = "订单号"
    if col_income_type:
        rename_map[col_income_type] = "收支类型"
    if col_biz_type:
        rename_map[col_biz_type] = "业务类型"
    if col_amount:
        rename_map[col_amount] = "金额(元)"
    if rename_map:
        df = df.rename(columns=rename_map)

    # 删除内部辅助列
    if "_金额数值" in df.columns:
        df = df.drop(columns=["_金额数值"])

    # 8. 输出：在首行附带汇总信息
    #    做法：生成一个汇总sheet + 明细sheet
    output_dir = None
    if params:
        output_dir = params.get("output_dir")
    if not output_dir and context:
        output_dir = context.get("user_params", {}).get("output_dir")
    if not output_dir:
        output_dir = os.path.dirname(input_file)
    os.makedirs(output_dir, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"公众号资金账单_清洗后_{today}.xlsx")

    summary_df = pd.DataFrame(
        [
            {"指标": "销售额(收入合计)", "金额(元)": round(sales_amount, 2), "说明": "收支类型=收入的所有记录"},
            {"指标": "退款额(支出中退款/手续费合计)", "金额(元)": round(refund_amount, 2), "说明": "收支类型=支出 且 业务类型包含退款/手续费"},
            {"指标": "净收入", "金额(元)": round(sales_amount - refund_amount, 2), "说明": "销售额 - 退款额"},
            {"指标": "原始明细总行数", "金额(元)": int(len(df)), "说明": "去空前的有效行数"},
        ]
    )

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="汇总", index=False)
        df.to_excel(writer, sheet_name="明细", index=False)

    logger.info(f"[wechat_bill] 清洗完成 -> {output_file}")
    logger.info(f"[wechat_bill] 汇总: 销售额={sales_amount:.2f}, 退款/手续费={refund_amount:.2f}, 净收入={sales_amount-refund_amount:.2f}")

    return output_file
