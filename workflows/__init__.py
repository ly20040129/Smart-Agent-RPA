# -*- coding: utf-8 -*-
"""
业务代码目录 —— 自动设置项目根路径，无需在每个 workflow 文件中重复样板代码。

写新任务：复制一个现有文件改名字改逻辑即可。

============ workflow 函数契约（所有 workflow 必须遵守）============
签名：  async def xxx(user_params: dict) -> dict
        参数由编排层（task_executor）合并后位置传入，不要用 **kwargs。

返回：  必须含 "status"，取值 "success" 或 "failed"
        失败时含 "error": 错误说明
        需要编排层把结果文件交付给用户时，含 "output_file": 文件绝对路径
        （workflow 自己已完成发送的，如钉钉测试，不要返回 output_file，
          否则会被编排层重复交付）

其余业务字段（行数、命中数等）随意添加，编排层会原样存进任务历史。
==================================================================
"""
import sys
from pathlib import Path

# 自动把项目根目录加入 sys.path，确保 `from sdk.xxx import ...` 等导入正常工作
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))