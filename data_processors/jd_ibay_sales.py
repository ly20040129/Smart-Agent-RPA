# -*- coding: utf-8 -*-
"""
京东艾贝自营仓销售出库 - 数据清洗逻辑

输入：API或浏览器下载的原始Excel文件
处理：根据业务需求清洗、筛选、汇总数据
输出：清洗后的Excel文件
"""
import os
from pathlib import Path
from datetime import datetime
from loguru import logger


def process(input_file: str, context: dict = None, params: dict = None, **kwargs) -> str:
    """
    清洗京东艾贝自营仓销售出库数据

    Args:
        input_file: 输入文件路径（上一步下载或API获取的Excel）
        context: 任务上下文（包含user_params等）
        params: 额外参数（模板路径、输出目录等）
        **kwargs: 兼容其他关键字参数

    Returns:
        清洗后的输出文件路径
    """
    import pandas as pd

    logger.info(f"[jd_ibay_sales] 开始清洗数据: {input_file}")

    # 读取原始数据
    df = pd.read_excel(input_file)
    logger.info(f"[jd_ibay_sales] 原始数据: {len(df)} 行 x {len(df.columns)} 列")
    logger.info(f"[jd_ibay_sales] 列名: {list(df.columns)}")

    # ====== 清洗逻辑（根据实际业务需求修改） ======

    # 1. 去除空行
    df = df.dropna(how='all')

    # 2. 如果有时间字段，统一格式
    if 'refDate' in df.columns:
        try:
            df['refDate'] = pd.to_datetime(df['refDate'], unit='ms', errors='coerce')
            df['业务日期'] = df['refDate'].dt.strftime('%Y-%m-%d')
        except Exception:
            pass

    # 3. 数值字段处理
    numeric_cols = ['amount', 'skuNum', 'fcpyBillingAmount']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 4. 重命名列（英文→中文）
    column_map = {
        'refType': '单据类型',
        'refId': '单据编号',
        'poId': '采购单号',
        'orderNo': '订单号',
        'buyerName': '采销员/销售员',
        'ouName': '合同主体',
        'sku': 'SKU编码',
        'goodsName': '商品名称',
        'skuNum': '数量',
        'amount': '金额',
        'currency': '币种',
        'channelName': '渠道名称',
        'supplierId': '供应商ID',
    }
    df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})

    # 5. 按业务需求筛选和排序
    if '业务日期' in df.columns:
        df = df.sort_values('业务日期')

    logger.info(f"[jd_ibay_sales] 清洗后: {len(df)} 行 x {len(df.columns)} 列")

    # ====== 保存 ======

    # 输出目录：优先用params指定的，其次用context中的，最后用默认
    output_dir = params.get('output_dir') if params else None
    if not output_dir and context:
        user_params = context.get('user_params', {})
        output_dir = user_params.get('output_dir')
    if not output_dir:
        output_dir = os.path.dirname(input_file)

    os.makedirs(output_dir, exist_ok=True)

    # 输出文件名
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"京东艾贝销售出库_清洗后_{today}.xlsx")

    df.to_excel(output_file, index=False)
    logger.info(f"[jd_ibay_sales] 清洗完成，保存到: {output_file}")

    return output_file
