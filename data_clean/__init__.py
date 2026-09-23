# -*- coding: utf-8 -*-
"""
数据清洗模块

每个文件对应一个任务的数据清洗逻辑，独立维护互不干扰。
新增任务只需新增一个文件，不需要修改已有代码。

清洗函数接口约定：
  输入：input_file（原始文件路径）+ context（上下文字典，含 user_params 等）
  输出：清洗后的文件路径（str）
"""

import sys
from pathlib import Path

# 自动把项目根目录加入 sys.path，确保 `from sdk.xxx import ...` 等导入正常工作
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
