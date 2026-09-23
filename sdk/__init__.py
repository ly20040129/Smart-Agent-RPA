# -*- coding: utf-8 -*-
"""
基础设施层 SDK 包

各子模块独立导入，本包不做聚合导出，避免 import 链副作用。
直接从子模块导入即可：
    from sdk.cookie_manager import cookie_manager
    from sdk.mysql_sdk import MySQL
    from sdk.data_tools import save_output
    from sdk.browser_sdk import Browser
"""
