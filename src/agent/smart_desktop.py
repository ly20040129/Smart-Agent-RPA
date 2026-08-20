# -*- coding: utf-8 -*-
"""
智能桌面模块 - LLM驱动的桌面应用操作

核心区别：
  传统RPA:  desktop.click_button("导出")              ← 按文本死找，控件名一改就废
  智能体:   smart_desktop.smart_click("导出本月报表")  ← LLM看控件树，自己理解该点哪个（也废）

LLM的参与方式：
  1. 提取当前窗口的所有可交互控件（按钮、输入框、菜单项）
  2. 把控件列表 + 用户意图 发给LLM
  3. LLM返回应该操作哪个控件（按index或AutomationId）
  4. 执行操作

这样即使应用界面改版、控件名变化，只要语义还在，就能正常工作。

适用场景：
  - 金蝶K/3、金蝶云等桌面ERP
  - 网点管家等业务客户端
  - 任何支持Windows UI Automation的桌面应用
"""
import json
import time
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from src.core.llm_client import LocalLLMClient
from sdk.desktop_sdk import Desktop


class SmartDesktop:
    """
    智能桌面 - LLM是大脑，uiautomation是手脚

    用法对比：
        # 传统方式（写死，脆弱）
        desktop.click_button("导出")
        desktop.fill_input("开始日期", "2026-07-01")

        # 智能方式（LLM理解，健壮）
        smart_desktop.smart_click("导出本月销售数据")
        smart_desktop.smart_fill("选择开始日期为7月1日", "2026-07-01")
    """

    # 提取给LLM看的控件类型（按优先级）
    INTERACTIVE_TYPES = [
        "ButtonControl",
        "MenuItemControl",
        "ListItemControl",
        "TreeItemControl",
        "EditControl",
        "ComboBoxControl",
        "CheckBoxControl",
        "RadioButtonControl",
        "HyperlinkControl",
        "TabItemControl",
    ]

    # 文本展示类型（用于上下文理解）
    TEXT_TYPES = [
        "TextControl",
        "LabelControl",
    ]

    # 单次提取给LLM的最大控件数（避免token超限）
    MAX_ELEMENTS_PER_CALL = 80

    def __init__(
        self,
        desktop: Optional[Desktop] = None,
        llm: Optional[LocalLLMClient] = None,
    ):
        """
        Args:
            desktop: Desktop实例，None则在使用时自动创建
            llm: LLM客户端，None则用默认配置
        """
        self.desktop = desktop or Desktop()
        self.llm = llm or LocalLLMClient()
        self._started = False

    def start(self, app_name: Optional[str] = None, app_path: Optional[str] = None):
        """启动桌面自动化，可选绑定应用窗口"""
        if app_path:
            self.desktop.app_path = app_path
        if app_name:
            self.desktop.app_name = app_name
        self.desktop.start()
        self._started = True
        logger.info(f"[SmartDesktop] 已启动" + (f"，绑定窗口: {app_name}" if app_name else ""))

    def close(self):
        """关闭"""
        if self._started:
            self.desktop.close()
            self._started = False

    # ==================== 上下文管理 ====================
    def __enter__(self):
        if not self._started:
            self.start()
        return self

    def __exit__(self, *args):
        self.close()
        return False

    # ==================== 智能方法（LLM驱动）====================
    def smart_click(self, intent: str, timeout: float = 10) -> bool:
        """
        智能点击：用自然语言描述点哪里

        Args:
            intent: 操作意图，如 "点击导出按钮"、"选择基础设置菜单"
            timeout: 等待超时

        Returns:
            是否点击成功

        Example:
            sd.smart_click("点击登录按钮")
            sd.smart_click("选择文件菜单中的导出")
        """
        logger.info(f"[SmartDesktop] 智能点击: {intent}")
        ctrl = self._llm_select_control(intent, timeout=timeout)
        if not ctrl:
            logger.warning(f"[SmartDesktop] LLM未找到匹配控件: {intent}")
            # 兜底：尝试按文本直接找
            return self._fallback_click_by_text(intent)
        try:
            ctrl.Click()
            logger.info(f"[SmartDesktop] ✅ 点击成功: {intent}")
            return True
        except Exception as e:
            logger.error(f"[SmartDesktop] 点击失败: {e}")
            return False

    def smart_fill(self, intent: str, value: str, timeout: float = 10) -> bool:
        """
        智能填写：用自然语言描述填哪个输入框

        Args:
            intent: 输入框描述，如 "用户名输入框"、"开始日期"
            value: 要填写的值

        Returns:
            是否填写成功

        Example:
            sd.smart_fill("用户名输入框", "admin")
            sd.smart_fill("查询条件的开始日期", "2026-07-01")
        """
        logger.info(f"[SmartDesktop] 智能填充: {intent} = {value}")
        ctrl = self._llm_select_control(
            intent,
            prefer_types=["EditControl", "ComboBoxControl"],
            timeout=timeout,
        )
        if not ctrl:
            logger.warning(f"[SmartDesktop] LLM未找到输入框: {intent}")
            return self.desktop.fill_input(intent, value, timeout=3)

        try:
            ctrl.SetFocus()
            time.sleep(0.1)
            # 清空
            self.desktop._ua.SendKeys("{Ctrl}a")
            time.sleep(0.05)
            self.desktop._ua.SendKeys("{Delete}")
            time.sleep(0.05)
            # 输入
            self.desktop._type_text(value)
            logger.info(f"[SmartDesktop] ✅ 填充成功: {intent} = {value}")
            return True
        except Exception as e:
            logger.error(f"[SmartDesktop] 填充失败: {e}")
            return False

    def smart_select(self, intent: str, value: str, timeout: float = 10) -> bool:
        """
        智能选择下拉框/列表项

        Args:
            intent: 下拉框描述
            value: 要选择的项

        Returns:
            是否成功
        """
        logger.info(f"[SmartDesktop] 智能选择: {intent} -> {value}")
        ctrl = self._llm_select_control(
            intent,
            prefer_types=["ComboBoxControl", "ListItemControl"],
            timeout=timeout,
        )
        if not ctrl:
            return self.desktop.select_combobox(intent, value)

        try:
            ctrl_type_name = ctrl.ControlType
            # 如果是ComboBox，先展开
            if "ComboBox" in str(ctrl_type_name):
                ctrl.Click()
                time.sleep(0.3)
                # 在展开的列表中找匹配项
                items = self.desktop._find_controls(
                    control_type="ListItemControl",
                    depth=15,
                )
                for item in items:
                    if value in (item.Name or ""):
                        item.Click()
                        logger.info(f"[SmartDesktop] ✅ 选择成功: {value}")
                        return True
                logger.warning(f"[SmartDesktop] 列表中未找到: {value}")
                return False
            else:
                # 直接点击ListItem
                ctrl.Click()
                return True
        except Exception as e:
            logger.error(f"[SmartDesktop] 选择失败: {e}")
            return False

    def smart_wait(self, condition: str, timeout: float = 30) -> bool:
        """
        智能等待：等待某个语义条件满足

        Args:
            condition: 等待条件，如 "登录成功显示主界面"、"导出完成对话框出现"
            timeout: 超时时间

        Returns:
            是否满足条件
        """
        logger.info(f"[SmartDesktop] 智能等待: {condition}")
        start = time.time()
        check_interval = 2.0  # 每2秒检查一次

        while time.time() - start < timeout:
            # 先做快速DOM检查（看窗口标题或关键文本）
            if self._quick_check(condition):
                logger.info(f"[SmartDesktop] ✅ 条件满足: {condition}")
                return True

            # 快速检查失败才调LLM（节省token）
            elapsed = time.time() - start
            if elapsed > 5 and int(elapsed) % 6 == 0:  # 6秒查一次LLM
                if self._llm_check_condition(condition):
                    logger.info(f"[SmartDesktop] ✅ 条件满足(LLM): {condition}")
                    return True

            time.sleep(check_interval)

        logger.warning(f"[SmartDesktop] 等待超时: {condition}")
        return False

    def smart_export(
        self,
        intent: str,
        save_path: str,
        timeout: float = 60,
    ) -> Optional[str]:
        """
        智能导出：用自然语言描述要导出什么

        流程：
        1. LLM找到导出按钮并点击
        2. 等待保存对话框出现
        3. 填写保存路径
        4. 点击保存
        5. 等待文件就绪

        Args:
            intent: 导出意图，如 "导出当前报表为Excel"
            save_path: 完整保存路径
            timeout: 整体超时

        Returns:
            保存成功返回路径，失败返回None
        """
        logger.info(f"[SmartDesktop] 智能导出: {intent} -> {save_path}")
        # 先智能点击触发导出
        if not self.smart_click(intent, timeout=10):
            logger.error("[SmartDesktop] 未能触发导出")
            return None
        # 然后用Desktop原生方法处理保存对话框
        return self.desktop.export_file(
            save_path=save_path,
            trigger_button="",  # 已经触发了，不再点
            confirm_in_dialog=True,
            confirm_text="保存",
            timeout=timeout,
        )

    def smart_read_table(
        self,
        intent: str = "当前显示的数据表格",
        max_rows: int = 1000,
    ) -> List[List[str]]:
        """
        智能读取表格：LLM识别页面中的表格控件并提取数据

        Args:
            intent: 表格描述
            max_rows: 最多提取行数

        Returns:
            二维列表（第一行通常是表头）
        """
        logger.info(f"[SmartDesktop] 智能读取表格: {intent}")
        # 直接尝试找DataGrid/Table
        data = self.desktop.get_table_data(max_rows=max_rows)
        if data:
            return data
        # 兜底：LLM判断表格位置，截图后用OCR（暂未集成，留接口）
        logger.warning("[SmartDesktop] 未找到表格控件，可能需要图像识别")
        return []

    # ==================== LLM交互核心 ====================
    def _llm_select_control(
        self,
        intent: str,
        prefer_types: Optional[List[str]] = None,
        timeout: float = 10,
    ) -> Optional[Any]:
        """
        让LLM从控件树中选择应该操作的控件

        Args:
            intent: 用户意图描述
            prefer_types: 优先选择的控件类型
            timeout: 超时时间

        Returns:
            选中的控件对象，或None
        """
        start = time.time()
        while time.time() - start < timeout:
            # 提取控件列表
            elements = self._get_interactive_elements(prefer_types=prefer_types)
            if not elements:
                time.sleep(0.5)
                continue

            # 构造LLM prompt
            elements_text = self._format_elements_for_llm(elements)
            prompt = self._build_selection_prompt(intent, elements_text, prefer_types)

            try:
                reply = self.llm.chat(
                    message=prompt,
                    system_prompt=self._get_system_prompt(),
                )
                # 解析LLM返回的index
                idx = self._parse_llm_index(reply, len(elements))
                if idx is not None and 0 <= idx < len(elements):
                    selected = elements[idx]
                    logger.info(
                        f"[SmartDesktop] LLM选择: index={idx}, "
                        f"type={selected.get('type')}, text={selected.get('text', '')[:30]}"
                    )
                    return selected.get("control")
                else:
                    logger.warning(f"[SmartDesktop] LLM返回无效index: {reply[:100]}")
            except Exception as e:
                logger.error(f"[SmartDesktop] LLM调用失败: {e}")
            time.sleep(1)

        return None

    def _llm_check_condition(self, condition: str) -> bool:
        """让LLM判断当前页面状态是否满足条件"""
        elements = self._get_interactive_elements()
        elements_text = self._format_elements_for_llm(elements[:30])  # 截断节省token
        window_title = ""
        try:
            if self.desktop._window:
                window_title = self.desktop._window.Name or ""
        except Exception:
            pass

        prompt = f"""判断当前桌面应用状态是否满足条件。

当前窗口标题: {window_title}

可见控件（前30个）:
{elements_text}

判断条件: {condition}

只回答 true 或 false，不要解释。"""
        try:
            reply = self.llm.chat(message=prompt)
            return "true" in reply.lower()
        except Exception:
            return False

    # ==================== 控件提取 ====================
    def _get_interactive_elements(
        self,
        prefer_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        提取当前窗口所有可交互控件

        Returns:
            [{"index": 0, "type": "ButtonControl", "text": "登录", "control": ctrl_obj}, ...]
        """
        types_to_search = prefer_types or self.INTERACTIVE_TYPES
        elements = []
        seen_texts = set()  # 去重

        try:
            for ctrl_type in types_to_search:
                ctrls = self.desktop._find_controls(
                    control_type=ctrl_type,
                    depth=12,
                )
                for ctrl in ctrls:
                    try:
                        if ctrl.IsOffscreen:
                            continue
                        text = (ctrl.Name or "").strip()
                        # 去重（同文本同类型的控件只保留第一个）
                        key = (ctrl_type, text)
                        if key in seen_texts:
                            continue
                        seen_texts.add(key)
                        elements.append({
                            "index": len(elements),
                            "type": ctrl_type,
                            "text": text,
                            "control": ctrl,
                        })
                        if len(elements) >= self.MAX_ELEMENTS_PER_CALL:
                            return elements
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"[SmartDesktop] 控件提取失败: {e}")

        return elements

    def _format_elements_for_llm(self, elements: List[Dict]) -> str:
        """格式化控件列表给LLM看"""
        lines = []
        for e in elements:
            text = e.get("text", "")
            if text:
                # 截断过长的文本
                if len(text) > 50:
                    text = text[:50] + "..."
                lines.append(f"[{e['index']}] [{e['type']}] {text}")
            else:
                lines.append(f"[{e['index']}] [{e['type']}] (无文本)")
        return "\n".join(lines)

    def _build_selection_prompt(
        self,
        intent: str,
        elements_text: str,
        prefer_types: Optional[List[str]] = None,
    ) -> str:
        """构造LLM选择控件的prompt"""
        type_hint = ""
        if prefer_types:
            type_hint = f"\n提示：用户希望操作的是 {'/'.join(prefer_types)} 类型控件。"

        return f"""用户想执行的桌面操作: {intent}

当前桌面应用中可见的可交互控件列表（index | 类型 | 文本）:
{elements_text}{type_hint}

请分析用户意图，从上面的控件列表中选择最应该被操作的那个。
只返回该控件的index数字（如 12），不要返回其他任何内容。如果都不合适，返回 -1。"""

    def _get_system_prompt(self) -> str:
        return (
            "你是桌面应用自动化助手。用户会用自然语言描述想点的按钮、"
            "想填的输入框、想选的菜单。你的任务是从控件列表中选出最匹配的，"
            "只返回index数字。注意：控件文本可能是中文，要理解语义而非死板匹配。"
        )

    def _parse_llm_index(self, reply: str, max_count: int) -> Optional[int]:
        """从LLM回复中解析出index"""
        import re
        # 找数字
        match = re.search(r'\b(\d+)\b', reply)
        if match:
            idx = int(match.group(1))
            if 0 <= idx < max_count:
                return idx
        return None

    # ==================== 兜底策略 ====================
    def _quick_check(self, condition: str) -> bool:
        """
        快速检查条件（不调LLM，节省token）
        策略：检查窗口标题、关键文本是否出现
        """
        # 提取condition中的关键词（简单分词）
        keywords = [w for w in condition.replace("，", " ").replace(":", " ").split() if len(w) >= 2]
        if not keywords:
            return False

        # 检查窗口标题
        try:
            if self.desktop._window:
                title = self.desktop._window.Name or ""
                if any(k in title for k in keywords):
                    return True
        except Exception:
            pass

        # 检查关键文本是否出现（用uiautomation快速查找）
        try:
            for keyword in keywords[:3]:  # 最多检查3个关键词
                ctrl = self.desktop._find_text_control(
                    control_types=None,
                    text=keyword,
                    timeout=0.3,
                )
                if ctrl:
                    return True
        except Exception:
            pass

        return False

    def _fallback_click_by_text(self, intent: str) -> bool:
        """LLM选择失败时的兜底：从intent中提取关键词直接找按钮"""
        # 简单提取：去掉"点击"、"按钮"等常见词
        keywords_to_remove = ["点击", "按钮", "选择", "菜单", "的", "中"]
        text = intent
        for w in keywords_to_remove:
            text = text.replace(w, "")
        text = text.strip()
        if not text:
            return False
        logger.info(f"[SmartDesktop] 兜底按文本找按钮: {text}")
        return self.desktop.click_button(text, timeout=3)


# ==================== 异步包装器 ====================
class AsyncSmartDesktop:
    """
    SmartDesktop的异步包装器

    用法：
        async with AsyncSmartDesktop(app_name="金蝶K/3") as sd:
            await sd.smart_click("登录按钮")
            await sd.smart_fill("用户名", "admin")
    """

    def __init__(self, **kwargs):
        self._smart = SmartDesktop(**kwargs)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()
        return False

    async def start(self, **kwargs):
        await asyncio.to_thread(self._smart.start, **kwargs)
        return self

    async def close(self):
        await asyncio.to_thread(self._smart.close)

    def __getattr__(self, name):
        attr = getattr(self._smart, name)
        if callable(attr):
            async def _wrapper(*args, **kwargs):
                return await asyncio.to_thread(attr, *args, **kwargs)
            return _wrapper
        return attr
