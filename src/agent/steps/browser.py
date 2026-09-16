# -*- coding: utf-8 -*-
"""
浏览器步骤 —— 全部用 browser-use 驱动，动作转为自然语言交给 AI。

重构重点：
  - action: browser_use  已存在，保持不变
  - 新增 action: smart_login  智能登录（自动检测登录态、处理验证码）
  - 新增 action: smart_export 智能导出（导航→筛选→导出，全自然语言）
  - 新增 action: fill_form    批量填表（多字段自然语言描述）

设计原则：金蝶云、网店管家这类老旧系统，不再手写 Playwright selector，
而是 YAML 里一句自然语言让 AI 自己操作浏览器。
"""
import os
from typing import Any, Dict

from loguru import logger

from . import workflow


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    # 懒加载 browser agent
    if not executor.browser_agent:
        from src.tools.browser_use_agent import BrowserUseAgent
        executor.browser_agent = BrowserUseAgent()

    agent = executor.browser_agent
    url = params.get("url", "")

    # ==================== 基础动作 ====================

    if action == "navigate":
        result = await agent.run(task=f"打开页面 {url}", initial_url=url)
        return {"status": "success", "context": {"current_url": url, "browser_use_result": result}}

    if action == "click":
        intent = params.get("intent", "")
        result = await agent.run(task=f"点击页面上的'{intent}'按钮或链接")
        return {"status": "success", "context": {"click_result": result}}

    if action == "fill":
        intent = params.get("intent", "")
        value = params.get("value", "")
        result = await agent.run(task=f"在页面上的'{intent}'输入框中填入：{value}")
        return {"status": "success", "context": {"fill_result": result}}

    if action == "wait":
        condition = params.get("condition", "")
        result = await agent.run(task=f"等待页面满足条件：{condition}。满足后返回。")
        return {"status": "success", "context": {"wait_result": result}}

    if action == "download":
        intent = params.get("intent", "")
        result = await agent.run(task=f"下载页面上的'{intent}'文件。下载完成后返回文件路径。")
        # 尝试从结果中提取下载文件路径
        file_path = _extract_file_path(result)
        return {"status": "success", "context": {
            "downloaded_file": file_path or result,
            "browser_use_result": result,
        }}

    # ==================== 高级动作（自然语言驱动） ====================

    if action == "browser_use":
        """通用自然语言驱动：YAML 里写 task 描述，AI 全自动操作"""
        task = params.get("task", "")
        if not task:
            return {"status": "failed", "error": "browser_use 动作需要 task 参数"}
        result = await agent.run(task=task, initial_url=url or None)
        file_path = _extract_file_path(result)
        return {"status": "success", "context": {
            "browser_use_result": result,
            "downloaded_file": file_path or "",
        }}

    if action == "smart_login":
        """
        智能登录：自动检测登录态，已登录则跳过，未登录则执行登录。

        YAML 示例:
          - type: browser
            action: smart_login
            params:
              url: "https://kd.yourcompany.com/login"
              account: "${username}"
              password: "${password}"
              login_task: "输入账号密码后点击登录按钮"
              success_hint: "页面显示「销售管理」菜单"
        """
        account = params.get("account", "")
        password = params.get("password", "")
        login_task = params.get("login_task", "")
        success_hint = params.get("success_hint", "页面显示用户信息或主菜单")

        # 先检查是否已登录
        check_task = f"打开 {url}，检查是否已登录。登录成功标志：{success_hint}。如果已登录，直接返回'已登录'。"
        check_result = await agent.run(task=check_task, initial_url=url)

        if "已登录" in str(check_result):
            logger.info("[browser] 已登录，跳过登录步骤")
            return {"status": "success", "context": {"login_status": "already_logged_in"}}

        # 未登录，执行登录
        task = login_task or f"登录页面。输入账号 {account}，密码 {password}，点击登录。登录成功标志：{success_hint}。如需验证码，等待用户手动处理。"
        result = await agent.run(task=task, initial_url=url)
        return {"status": "success", "context": {"login_result": result, "login_status": "logged_in"}}

    if action == "smart_export":
        """
        智能导出：导航到目标页面 → 筛选条件 → 导出文件。

        YAML 示例:
          - type: browser
            action: smart_export
            params:
              url: "https://kd.yourcompany.com/"
              navigate_task: "进入「销售管理」→「销售出库单」"
              filter_task: "设置日期范围 ${date_from} 到 ${date_to}"
              export_task: "点击「导出」按钮，选择 Excel 格式"
              wait_download: true
        """
        navigate_task = params.get("navigate_task", "")
        filter_task = params.get("filter_task", "")
        export_task = params.get("export_task", "")
        wait_download = params.get("wait_download", True)

        full_task_parts = []
        if url:
            full_task_parts.append(f"1. 打开页面 {url}")
        if navigate_task:
            full_task_parts.append(f"2. {navigate_task}")
        if filter_task:
            full_task_parts.append(f"3. {filter_task}")
        if export_task:
            full_task_parts.append(f"4. {export_task}")
        if wait_download:
            full_task_parts.append("5. 等待文件下载完成，返回下载文件路径")

        task = "\n".join(full_task_parts)
        result = await agent.run(task=task, initial_url=url or None)
        file_path = _extract_file_path(result)
        return {"status": "success", "context": {
            "browser_use_result": result,
            "downloaded_file": file_path or "",
        }}

    if action == "fill_form":
        """
        批量填表：自然语言描述多个字段的填写。

        YAML 示例:
          - type: browser
            action: fill_form
            params:
              url: "https://xxx.com/form"
              fields: |
                在「客户名称」输入框填入 ${customer}
                在「日期」选择器选择 ${date}
                在「备注」文本框填入 "自动生成"
                点击「提交」按钮
        """
        fields = params.get("fields", "")
        if not fields:
            return {"status": "failed", "error": "fill_form 动作需要 fields 参数"}
        task = f"打开 {url}，按以下要求填写表单：\n{fields}"
        result = await agent.run(task=task, initial_url=url or None)
        return {"status": "success", "context": {"fill_form_result": result}}

    # ==================== 委托 workflow ====================

    if action == "run_workflow":
        return await workflow.run(executor, action, params, context)

    return {"status": "failed", "error": f"未知浏览器动作: {action}"}


def _extract_file_path(result) -> str:
    """从 browser-use 返回结果中提取下载文件路径"""
    if not result:
        return ""
    if isinstance(result, str):
        # 尝试匹配常见路径模式
        import re
        m = re.search(r'([A-Za-z]:\\[^\s,;]+\.(?:xlsx|xls|csv|pdf|zip))', result)
        if m:
            path = m.group(1)
            if os.path.exists(path):
                return path
        m = re.search(r'(/[^\s,;]+\.(?:xlsx|xls|csv|pdf|zip))', result)
        if m:
            path = m.group(1)
            if os.path.exists(path):
                return path
    return ""