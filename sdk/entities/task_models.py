# -*- coding: utf-8 -*-
"""
平台内部数据表实体

任务执行历史、下载记录、通用业务数据
"""
from sdk.entities import register_entity, Column


@register_entity("task_history")
class TaskHistory:
    """任务执行历史"""
    table_name = "task_history"
    platform = ""
    cookie_key = ""
    description = "任务执行历史"

    id           = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    task_id      = Column("task_id", "VARCHAR(200)", "任务ID")
    task_name    = Column("task_name", "VARCHAR(200)", "任务名称")
    department   = Column("department", "VARCHAR(50)", "部门")
    status       = Column("status", "VARCHAR(20)", "状态")
    start_time   = Column("start_time", "DATETIME", "开始时间")
    end_time     = Column("end_time", "DATETIME", "结束时间")
    elapsed_time = Column("elapsed_time", "INT", "耗时(秒)")
    error_msg    = Column("error_msg", "TEXT", "错误信息")
    output_files = Column("output_files", "TEXT", "输出文件")
    created_by   = Column("created_by", "VARCHAR(100)", "触发人")


@register_entity("download_records")
class DownloadRecords:
    """下载文件记录"""
    table_name = "download_records"
    platform = ""
    cookie_key = ""
    description = "下载文件记录"

    id            = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    task_id       = Column("task_id", "VARCHAR(200)", "任务ID")
    filename      = Column("filename", "VARCHAR(500)", "文件名")
    local_path    = Column("local_path", "VARCHAR(500)", "本地路径")
    file_size     = Column("file_size", "BIGINT", "文件大小")
    download_time = Column("download_time", "DATETIME", "下载时间")
    source_site   = Column("source_site", "VARCHAR(200)", "来源网站")
    department    = Column("department", "VARCHAR(50)", "部门")


@register_entity("business_data")
class BusinessData:
    """通用业务数据表（小数据量可以直接存JSON）"""
    table_name = "business_data"
    platform = ""
    cookie_key = ""
    description = "通用业务数据表"

    id            = Column("id", "BIGINT AUTO_INCREMENT PRIMARY KEY", "主键")
    task_id       = Column("task_id", "VARCHAR(200)", "任务ID")
    business_type = Column("business_type", "VARCHAR(100)", "业务类型")
    data_json     = Column("data_json", "TEXT", "数据JSON")
    summary       = Column("summary", "VARCHAR(500)", "摘要")
    created_at    = Column("created_at", "DATETIME", "创建时间")
