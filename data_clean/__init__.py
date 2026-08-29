# -*- coding: utf-8 -*-
"""
数据清洗模块

每个文件对应一个任务的数据清洗逻辑，独立维护互不干扰。
新增任务只需新增一个文件，不需要修改已有代码。

清洗函数接口约定：
  输入：input_file（上一步生成的文件路径）+ 可选的 context（上下文数据）+ 可选的 params（额外参数）
  输出：output_file（清洗后的文件路径）或 (data, output_file) 元组

示例YAML调用：
  - type: data
    action: process_data
    params:
      module: data_clean.jd_ibay_sales
      function: process
"""
