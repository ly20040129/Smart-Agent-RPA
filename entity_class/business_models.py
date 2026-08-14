# 业务部门的数据表（销售、库存、运营等）
from models.base import BaseModel, Column


class SalesDailyModel(BaseModel):
    # 每日销售明细
    table_name = "biz_sales_daily"
    id           = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    sale_date    = Column("sale_date", "DATE", "销售日期")
    platform     = Column("platform", "VARCHAR(100)", "平台")
    shop_name    = Column("shop_name", "VARCHAR(200)", "店铺名")
    sku_code     = Column("sku_code", "VARCHAR(100)", "SKU编码")
    product_name = Column("product_name", "VARCHAR(300)", "商品名")
    qty          = Column("qty", "INT", "数量")
    sales_amount = Column("sales_amount", "DECIMAL(15,2)", "销售金额")
    customer     = Column("customer_name", "VARCHAR(200)", "客户")
    salesperson  = Column("salesperson", "VARCHAR(100)", "业务员")
    department   = Column("department", "VARCHAR(50) DEFAULT 'business'", "部门")
    task_id      = Column("task_id", "VARCHAR(200)", "任务ID")


class InventoryDailyModel(BaseModel):
    # 每日库存
    table_name = "biz_inventory_daily"
    id          = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    stat_date   = Column("stat_date", "DATE", "统计日期")
    sku_code    = Column("sku_code", "VARCHAR(100)", "SKU编码")
    product_name= Column("product_name", "VARCHAR(300)", "商品名")
    category    = Column("category", "VARCHAR(100)", "品类")
    stock_qty   = Column("stock_qty", "INT", "库存数量")
    stock_value = Column("stock_value", "DECIMAL(18,2)", "库存金额")
    avg_cost    = Column("avg_cost", "DECIMAL(15,2)", "平均成本")
    supplier    = Column("supplier", "VARCHAR(200)", "供应商")
    warehouse   = Column("warehouse", "VARCHAR(200)", "仓库")
    department  = Column("department", "VARCHAR(50) DEFAULT 'business'", "部门")
    task_id     = Column("task_id", "VARCHAR(200)", "任务ID")


class OperationDailyModel(BaseModel):
    # 运营日报
    table_name = "biz_operation_daily"
    id            = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    stat_date     = Column("stat_date", "DATE", "统计日期")
    platform      = Column("platform", "VARCHAR(100)", "平台")
    ad_spend      = Column("ad_spend", "DECIMAL(15,2)", "广告花费")
    impressions   = Column("impressions", "BIGINT", "曝光量")
    clicks        = Column("clicks", "INT", "点击量")
    click_rate    = Column("click_rate", "DECIMAL(8,4)", "点击率")
    cpc           = Column("cpc", "DECIMAL(10,2)", "单次点击成本")
    roi           = Column("roi", "DECIMAL(10,2)", "ROI")
    sales_from_ad = Column("sales_from_ad", "DECIMAL(15,2)", "广告销售额")
    operator      = Column("operator", "VARCHAR(100)", "运营")
    department    = Column("department", "VARCHAR(50) DEFAULT 'operations'", "部门")
    task_id       = Column("task_id", "VARCHAR(200)", "任务ID")


class CustomerFeedbackModel(BaseModel):
    # 客户反馈/投诉
    table_name = "biz_customer_feedback"
    id            = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    fb_date       = Column("fb_date", "DATE", "反馈日期")
    customer      = Column("customer", "VARCHAR(200)", "客户名")
    phone         = Column("phone", "VARCHAR(50)", "联系方式")
    platform      = Column("platform", "VARCHAR(100)", "来源平台")
    type_         = Column("type_", "VARCHAR(50)", "类型")
    content       = Column("content", "TEXT", "内容")
    handler       = Column("handler", "VARCHAR(100)", "处理人")
    handle_status = Column("handle_status", "VARCHAR(50)", "处理状态")
    handle_result = Column("handle_result", "TEXT", "处理结果")
    department    = Column("department", "VARCHAR(50) DEFAULT 'business'", "部门")
    task_id       = Column("task_id", "VARCHAR(200)", "任务ID")
