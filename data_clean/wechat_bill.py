# -*- coding: utf-8 -*-
"""
公众号资金账单 - 数据清洗模块（重构版）

重构前：185 行（含智能读取、列名规范化、金额清洗、汇总输出等通用逻辑）
重构后：~70 行（只保留微信账单特有的业务规则，通用操作全部走 sdk/data_tools.py）

设计原则：影刀中几个代码块就能完成的需求，迁移过来后不应过度工程化。
"""
import os
from datetime import datetime
from loguru import logger

import pandas as pd

from sdk.data_tools import (
    read_excel_smart, normalize_columns, find_column,
    clean_amount_column, save_output,
)


def process(input_file: str, context: dict = None, params: dict = None, **kwargs) -> str:
    """清洗公众号资金账单数据"""
    logger.info(f"[wechat_bill] 开始清洗: {input_file}")
    if not os.path.exists(input_file):
        raise FileNotFoundError(input_file)

    # 1. 智能读取（自动检测表头行）
    df = read_excel_smart(input_file, header_keywords=["收支类型", "业务类型", "金额"])
    logger.info(f"[wechat_bill] 有效数据: {len(df)} 行 x {len(df.columns)} 列")

    # 2. 列名规范化
    df = normalize_columns(df)

    # 3. 找关键列
    col_income_type = find_column(df, ["收支类型"])
    col_biz_type = find_column(df, ["业务类型"])
    col_amount = find_column(df, ["金额(元)", "金额", "收入金额", "支出金额"])
    col_time = find_column(df, ["交易时间", "记账时间", "时间", "日期"])
    col_order = find_column(df, ["商户订单号", "订单号", "单号"])
    logger.info(f"[wechat_bill] 列映射: 收支类型={col_income_type}, 业务类型={col_biz_type}, 金额={col_amount}")

    # 4. 金额清洗
    if col_amount:
        df = clean_amount_column(df, col_amount)
    else:
        df["_金额数值"] = 0.0

    # 5. 销售额（收支类型=收入）
    sales_mask = pd.Series([False] * len(df))
    if col_income_type:
        sales_mask = df[col_income_type].astype(str).str.contains("收入", na=False)
    sales_amount = float(df.loc[sales_mask, "_金额数值"].sum())

    # 6. 退款额（收支类型=支出，且业务类型含退款/手续费）
    refund_mask = pd.Series([False] * len(df))
    if col_income_type and col_biz_type:
        refund_mask = (
            df[col_income_type].astype(str).str.contains("支出", na=False)
            & df[col_biz_type].astype(str).apply(
                lambda x: any(kw in str(x) for kw in ("退款", "手续费", "扣除")))
        )
    refund_amount = float(df.loc[refund_mask, "_金额数值"].sum())

    logger.info(f"[wechat_bill] 销售额={sales_amount:.2f}, 退款/手续费={refund_amount:.2f}, 净收入={sales_amount-refund_amount:.2f}")

    # 7. 输出目录
    output_dir = None
    if params:
        output_dir = params.get("output_dir")
    if not output_dir and context:
        output_dir = context.get("user_params", {}).get("output_dir")
    if not output_dir:
        output_dir = os.path.dirname(input_file)

    # 8. 保存（汇总 sheet + 明细 sheet）
    summary_df = pd.DataFrame([
        {"指标": "销售额(收入合计)", "金额(元)": round(sales_amount, 2), "说明": "收支类型=收入"},
        {"指标": "退款额(退款/手续费合计)", "金额(元)": round(refund_amount, 2), "说明": "收支类型=支出 且 含退款/手续费"},
        {"指标": "净收入", "金额(元)": round(sales_amount - refund_amount, 2), "说明": "销售额 - 退款额"},
        {"指标": "原始明细总行数", "金额(元)": int(len(df)), "说明": "有效行数"},
    ])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"公众号资金账单_清洗后_{ts}.xlsx")
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="汇总", index=False)
        df.to_excel(writer, sheet_name="明细", index=False)

    logger.info(f"[wechat_bill] 清洗完成 -> {output_file}")
    return output_file