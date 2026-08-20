# 财务部门的数据表
# 新增表：复制一个class，改table_name和列就行
from entity_class.base import BaseModel, Column


class WechatBillModel(BaseModel):
    # 公众号微信资金账单
    table_name = "finance_wechat_bill"
    id           = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    bill_date    = Column("bill_date", "DATE", "账单日期")
    trade_no     = Column("trade_no", "VARCHAR(100)", "交易单号")
    order_no     = Column("order_no", "VARCHAR(100)", "商户订单号")
    trade_type   = Column("trade_type", "VARCHAR(50)", "交易类型")
    trade_status = Column("trade_status", "VARCHAR(50)", "交易状态")
    amount       = Column("amount", "DECIMAL(15,2)", "金额")
    service_fee  = Column("service_fee", "DECIMAL(15,2)", "手续费")
    receive_amt  = Column("receive_amt", "DECIMAL(15,2)", "实收金额")
    pay_account  = Column("pay_account", "VARCHAR(200)", "付款方")
    remark       = Column("remark", "VARCHAR(500)", "备注")
    department   = Column("department", "VARCHAR(50) DEFAULT 'finance'", "部门")
    task_id      = Column("task_id", "VARCHAR(200)", "任务ID")


class JdSalesModel(BaseModel):
    # 京东销售出库报表
    table_name = "finance_jd_sales"
    id            = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    sale_date     = Column("sale_date", "DATE", "销售日期")
    jd_order_no   = Column("jd_order_no", "VARCHAR(100)", "京东订单号")
    shop_order_no = Column("shop_order_no", "VARCHAR(100)", "商家订单号")
    sku_code      = Column("sku_code", "VARCHAR(100)", "SKU编码")
    product_name  = Column("product_name", "VARCHAR(300)", "商品名称")
    qty           = Column("qty", "INT", "数量")
    unit_price    = Column("unit_price", "DECIMAL(15,2)", "单价")
    total_amount  = Column("total_amount", "DECIMAL(15,2)", "总金额")
    discount_amt  = Column("discount_amt", "DECIMAL(15,2)", "优惠金额")
    actual_amt    = Column("actual_amt", "DECIMAL(15,2)", "实收金额")
    warehouse     = Column("warehouse", "VARCHAR(200)", "仓库")
    receiver      = Column("receiver", "VARCHAR(100)", "收货人")
    delivery_no   = Column("delivery_no", "VARCHAR(100)", "运单号")
    order_status  = Column("order_status", "VARCHAR(50)", "订单状态")
    account_no    = Column("account_no", "VARCHAR(100)", "京东账号")
    department    = Column("department", "VARCHAR(50) DEFAULT 'finance'", "部门")
    task_id       = Column("task_id", "VARCHAR(200)", "任务ID")


class TmallStockModel(BaseModel):
    # 天猫保税仓库存/出库
    table_name = "finance_tmall_stock"
    id            = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    stat_date     = Column("stat_date", "DATE", "统计日期")
    sku_code      = Column("sku_code", "VARCHAR(100)", "SKU编码")
    product_name  = Column("product_name", "VARCHAR(300)", "商品名称")
    begin_qty     = Column("begin_qty", "INT", "期初数量")
    inbound_qty   = Column("inbound_qty", "INT", "入库数量")
    outbound_qty  = Column("outbound_qty", "INT", "出库数量")
    end_qty       = Column("end_qty", "INT", "期末数量")
    unit_cost     = Column("unit_cost", "DECIMAL(15,2)", "单位成本")
    end_value     = Column("end_value", "DECIMAL(18,2)", "期末库存金额")
    warehouse     = Column("warehouse", "VARCHAR(200)", "仓库")
    department    = Column("department", "VARCHAR(50) DEFAULT 'finance'", "部门")
    task_id       = Column("task_id", "VARCHAR(200)", "任务ID")


class DailyFinanceReport(BaseModel):
    # 财务日报汇总（各平台）
    table_name = "finance_daily_report"
    id           = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    report_date  = Column("report_date", "DATE", "报表日期")
    platform     = Column("platform", "VARCHAR(100)", "平台")
    sales_amount = Column("sales_amount", "DECIMAL(18,2)", "销售额")
    order_count  = Column("order_count", "INT", "订单数")
    refund_amt   = Column("refund_amt", "DECIMAL(15,2)", "退款金额")
    platform_fee = Column("platform_fee", "DECIMAL(15,2)", "平台手续费")
    net_income   = Column("net_income", "DECIMAL(18,2)", "净收入")
    department   = Column("department", "VARCHAR(50) DEFAULT 'finance'", "部门")
    task_id      = Column("task_id", "VARCHAR(200)", "任务ID")
