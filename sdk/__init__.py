# 工具包入口
# 写任务代码时从这里导入：from sdk import Browser, MySQL, Chart ...
from sdk.local_config import LocalConfig
from sdk.browser_sdk import Browser, Cookie
from sdk.cookie_manager import cookie_manager
from sdk.mysql_sdk import MySQL
from sdk.excel_sdk import ExcelClean
from sdk.chart_sdk import Chart

__all__ = [
    "LocalConfig",     # 读本地路径配置
    "Browser",         # 浏览器操作
    "Cookie",          # Redis存取Cookie（旧接口，委托给cookie_manager）
    "cookie_manager",  # Cookie管理器（抓取、精简、存取）
    "MySQL",           # 数据库存取
    "ExcelClean",      # Excel清洗
    "Chart",           # 画图表
]
