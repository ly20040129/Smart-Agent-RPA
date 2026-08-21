# -*- coding: utf-8 -*-
"""
京东艾贝自营仓销售出库 - 实体类

数据表：jd_ibay_sales
平台：京东(jd)
Cookie：jd_shop_ibay

对应 workflow: workflows/jd_ibay_self_api.py
对应 data_clean: data_clean/jd_ibay_sales.py
"""
from sdk.entities import register_entity, Column


@register_entity("jd_ibay_sales")
class JD_Ibay_Sales:
    """京东艾贝自营仓销售出库数据实体"""

    table_name = "jd_ibay_sales"
    platform = "jd"                    # 平台标识
    cookie_key = "jd_shop_ibay"        # 默认cookie_key
    description = "京东艾贝自营仓销售出库"  # 描述

    # 列定义（对应京东导出格式的前12列）
    doc_type = Column("doc_type", "VARCHAR(50)", "单据类型")        # 单据类型
    doc_no = Column("doc_no", "VARCHAR(100)", "单据编号")           # 单据编号
    purchase_no = Column("purchase_no", "VARCHAR(100)", "采购单号")  # 采购单号
    order_no = Column("order_no", "VARCHAR(100)", "订单号")         # 订单号
    buyer = Column("buyer", "VARCHAR(50)", "采销员")                # 采销员
    contract_entity = Column("contract_entity", "VARCHAR(100)", "合同主体")  # 合同主体
    sku = Column("sku", "VARCHAR(100)", "SKU编码")                  # SKU编码
    quantity = Column("quantity", "DECIMAL(10,2)", "数量")           # 数量（负=出库，正=退货）
    amount = Column("amount", "DECIMAL(10,2)", "金额")              # 金额
    currency = Column("currency", "VARCHAR(20)", "币种")           # 币种
    biz_date = Column("biz_date", "DATETIME", "业务日期")           # 业务日期
    channel = Column("channel", "VARCHAR(50)", "采购渠道")          # 采购渠道
