# -*- coding: utf-8 -*-
"""桌面应用自动化步骤"""
import asyncio
from typing import Any, Dict

from . import workflow


async def _desktop(executor):
    if executor.smart_desktop:
        return executor.smart_desktop
    try:
        from src.agent.smart_desktop import SmartDesktop
        executor.smart_desktop = SmartDesktop()
        return executor.smart_desktop
    except ImportError as e:
        return None


async def run(executor, action: str, params: Dict, context: Dict) -> Dict[str, Any]:
    desktop = await _desktop(executor)
    if desktop is None:
        return {"status": "failed", "error": "桌面自动化模块未安装: uiautomation 缺失"}

    if action == "start_app":
        app_path = params.get("app_path", "")
        app_name = params.get("app_name", "")
        wait = params.get("wait_seconds", 5)
        try:
            desktop.start(app_name=app_name or None)
            if app_path:
                await asyncio.to_thread(desktop.desktop.start_app, app_path, "", wait)
            return {"status": "success", "context": {"desktop_app": app_name or app_path}}
        except Exception as e:
            return {"status": "failed", "error": f"启动应用失败: {e}"}

    if action == "smart_click":
        ok = await asyncio.to_thread(desktop.smart_click, params.get("intent", ""), params.get("timeout", 10))
        return {"status": "success" if ok else "failed", "error": "" if ok else f"智能点击失败: {params.get('intent', '')}"}

    if action == "smart_fill":
        ok = await asyncio.to_thread(
            desktop.smart_fill, params.get("intent", ""), params.get("value", ""), params.get("timeout", 10))
        return {"status": "success" if ok else "failed", "error": "" if ok else f"智能填充失败: {params.get('intent', '')}"}

    if action == "smart_select":
        ok = await asyncio.to_thread(
            desktop.smart_select, params.get("intent", ""), params.get("value", ""), params.get("timeout", 10))
        return {"status": "success" if ok else "failed", "error": "" if ok else f"智能选择失败: {params.get('intent', '')}"}

    if action == "smart_wait":
        ok = await asyncio.to_thread(
            desktop.smart_wait, params.get("condition", ""), params.get("timeout", 30))
        return {"status": "success" if ok else "failed", "error": "" if ok else f"等待超时: {params.get('condition', '')}"}

    if action == "smart_export":
        path = await asyncio.to_thread(
            desktop.smart_export, params.get("intent", ""), params.get("save_path", ""), params.get("timeout", 60))
        if path:
            return {"status": "success", "context": {"downloaded_file": path}}
        return {"status": "failed", "error": f"导出失败: {params.get('intent', '')}"}

    if action == "click_button":
        ok = await asyncio.to_thread(desktop.desktop.click_button, params.get("text", ""), False, params.get("timeout", 5))
        return {"status": "success" if ok else "failed"}

    if action == "fill_input":
        ok = await asyncio.to_thread(desktop.desktop.fill_input, params.get("label", ""), params.get("value", ""))
        return {"status": "success" if ok else "failed"}

    if action == "select_menu":
        menu_path = params.get("menu_path", [])
        if isinstance(menu_path, str):
            menu_path = [menu_path]
        ok = await asyncio.to_thread(desktop.desktop.select_menu, menu_path)
        return {"status": "success" if ok else "failed"}

    if action == "export_file":
        path = await asyncio.to_thread(
            desktop.desktop.export_file, params.get("save_path", ""),
            params.get("trigger_button", "导出"), True, "保存", params.get("timeout", 30))
        if path:
            return {"status": "success", "context": {"downloaded_file": path}}
        return {"status": "failed", "error": "导出失败"}

    if action == "press_key":
        ok = await asyncio.to_thread(desktop.desktop.press_key, params.get("key", "Enter"))
        return {"status": "success" if ok else "failed"}

    if action == "wait_window":
        ok = await asyncio.to_thread(desktop.desktop.wait_window, params.get("title", ""), params.get("timeout", 30))
        return {"status": "success" if ok else "failed", "error": "" if ok else f"窗口未出现: {params.get('title', '')}"}

    if action == "run_workflow":
        return await workflow.run(executor, action, params, context)

    return {"status": "failed", "error": f"未知桌面动作: {action}"}
