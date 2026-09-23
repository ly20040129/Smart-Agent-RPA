# -*- coding: utf-8 -*-
"""京东商智竞品排名数据表"""
from sdk.entities import register_entity, Column


@register_entity("jd_sz_compete")
class JD_SZ_Compete:
    """京东商智 竞品分析每日排名（每个SKU每天一行）"""
    table_name = "jd_sz_compete"
    platform = "jd"
    cookie_key = "jd_shangzhi"
    description = "京东商智竞品每日销量排名"

    stat_date  = Column("stat_date", "VARCHAR(10)", "统计日期")
    sku        = Column("sku", "VARCHAR(50)", "SKU")
    rank_4     = Column("rank_4", "VARCHAR(20)", "排名(指标4)")
    rank_6     = Column("rank_6", "VARCHAR(20)", "排名(指标6)")
    created_at = Column("created_at", "DATETIME", "抓取时间")
