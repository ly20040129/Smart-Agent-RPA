# -*- coding: utf-8 -*-
"""
桌面自动化工具包
封装 Windows 桌面应用操作（金蝶K/3、网点管家、金蝶云等桌面客户端）

设计参考：影刀RPA的xbot.click模式 + 项目现有browser_sdk.py风格

两类方法：
  1. 原生方法（直接操作控件）：click_button / fill_input / select_menu / export_file ...
  2. 图像方法（截图匹配）：click_image / wait_image / find_image ...

依赖：
  - uiautomation: Windows UI Automation API（控件树定位）
  - opencv-python: 图像识别
  - pillow: 截图处理

用法：
  from sdk import Desktop
  with Desktop(app_name="金蝶K/3") as d:
      d.click_button("登录")
      d.fill_input("用户名", "admin")
      d.fill_input("密码", "123456")
      d.click_button("确定")
      d.select_menu(["基础设置", "核算项目", "物料"])
      d.export_file(save_path="D:/reports/material.xlsx")
"""
import os
import sys
import time
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Union

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger


def _import_uiautomation():
    """懒加载uiautomation，未安装时给友好提示"""
    try:
        import uiautomation as ua
        return ua
    except ImportError:
        raise RuntimeError(
            "未安装uiautomation库，请运行：pip install uiautomation>=2.0.0"
        )


def _import_cv2():
    """懒加载opencv，图像识别用"""
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError:
        raise RuntimeError(
            "未安装opencv-python，请运行：pip install opencv-python>=4.8.0"
        )


class Desktop:
    """
    桌面应用自动化操作

    用法：
        with Desktop() as d:                       # 通用桌面操作
            d.start_app("C:/path/to/app.exe")
            d.click_button("确定")

        with Desktop(app_name="金蝶K/3") as d:     # 绑定到特定应用窗口
            d.click_button("登录")
    """

    def __init__(
        self,
        app_name: Optional[str] = None,
        app_path: Optional[str] = None,
        lang: str = "zh",
        slow_mode: bool = False,
    ):
        """
        Args:
            app_name: 应用窗口标题包含的关键字（如"金蝶K/3"），用于绑定窗口
            app_path: 应用启动路径，传入则在start()时自动启动
            lang: 控件语言（zh/en），影响文本匹配
            slow_mode: 慢速模式，每个操作间隔1秒（演示/调试用）
        """
        self.app_name = app_name
        self.app_path = app_path
        self.lang = lang
        self.slow_mode = slow_mode
        self._ua = None           # uiautomation模块
        self._window = None       # 绑定的应用窗口
        self._app_process = None  # 启动的进程
        self._started = False

    # ==================== 上下文管理 ====================
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def start(self):
        """启动桌面自动化：加载uiautomation，可选启动应用，绑定窗口"""
        if self._started:
            return self
        self._ua = _import_uiautomation()
        if self.app_path:
            self.start_app(self.app_path)
        if self.app_name:
            self.bind_window(self.app_name)
        self._started = True
        logger.info(f"[Desktop] 已启动" + (f"，已绑定窗口: {self.app_name}" if self._window else ""))
        return self

    def close(self):
        """关闭桌面自动化（不主动关闭应用，应用由用户或脚本控制）"""
        self._started = False
        self._window = None
        logger.info("[Desktop] 已关闭")

    # ==================== 应用/窗口管理 ====================
    def start_app(self, app_path: str, args: str = "", wait_seconds: float = 5) -> int:
        """启动桌面应用"""
        import subprocess
        if not os.path.exists(app_path):
            raise FileNotFoundError(f"应用不存在: {app_path}")
        cmd = f'"{app_path}" {args}'.strip()
        logger.info(f"[Desktop] 启动应用: {cmd}")
        proc = subprocess.Popen(cmd, shell=True)
        self._app_process = proc
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        return proc.pid

    def bind_window(self, title_keyword: str, timeout: float = 10) -> bool:
        """绑定到指定标题的窗口（后续操作都基于这个窗口）"""
        self._ua = self._ua or _import_uiautomation()
        start = time.time()
        while time.time() - start < timeout:
            win = self._ua.WindowControl(searchDepth=1, Name=title_keyword)
            if win.Exists(0.5):
                self._window = win
                self.app_name = title_keyword
                logger.info(f"[Desktop] 已绑定窗口: {title_keyword}")
                return True
            time.sleep(0.5)
        logger.warning(f"[Desktop] 未找到窗口: {title_keyword}")
        return False

    def list_windows(self) -> List[Dict[str, Any]]:
        """列出当前所有可见顶层窗口（用于查找app_name）"""
        self._ua = self._ua or _import_uiautomation()
        result = []
        root = self._ua.GetRootControl()
        for win in root.GetChildren():
            if win.ControlType == self._ua.ControlType.WindowControl:
                if win.IsOffscreen:
                    continue
                result.append({
                    "title": win.Name,
                    "class_name": win.ClassName,
                    "pid": win.ProcessId,
                })
        return result

    def set_window_foreground(self) -> bool:
        """把绑定的窗口置顶到前台"""
        if not self._window:
            logger.warning("[Desktop] 未绑定窗口")
            return False
        try:
            self._window.SetTopmost(True)
            time.sleep(0.2)
            self._window.SetTopmost(False)
            self._window.SetFocus()
            return True
        except Exception as e:
            logger.error(f"[Desktop] 置顶窗口失败: {e}")
            return False

    # ==================== 内部辅助 ====================
    def _root(self):
        """获取操作根节点：绑定窗口则返回窗口，否则返回桌面根"""
        if not self._started:
            self.start()
        if self._window:
            return self._window
        return self._ua.GetRootControl()

    def _slow(self):
        """慢速模式延迟"""
        if self.slow_mode:
            time.sleep(1.0)

    def _find_controls(
        self,
        control_type: Optional[str] = None,
        name: Optional[str] = None,
        class_name: Optional[str] = None,
        automation_id: Optional[str] = None,
        depth: int = 0xFFFFFFFF,
        root=None,
    ) -> List[Any]:
        """通用控件查找（递归遍历控件树）"""
        self._ua = self._ua or _import_uiautomation()
        root = root if root is not None else self._root()
        results = []
        try:
            def _walk(ctrl, depth_left):
                if not depth_left:
                    return
                for child in ctrl.GetChildren():
                    if name is None or name in (child.Name or ""):
                        if class_name is None or child.ClassName == class_name:
                            if automation_id is None or child.AutomationId == automation_id:
                                if control_type is None or child.ControlType == getattr(self._ua.ControlType, control_type, None):
                                    results.append(child)
                    _walk(child, depth_left - 1)
            _walk(root, 8 if depth == 0xFFFFFFFF else depth)
        except Exception:
            pass
        return results

    # ==================== 点击操作 ====================
    def click_button(self, text: str, exact: bool = False, timeout: float = 5) -> bool:
        """点击按钮（按文本）"""
        logger.info(f"[Desktop] 点击按钮: {text}")
        btn = self._find_text_control(
            control_types=["ButtonControl", "MenuItemControl"],
            text=text,
            exact=exact,
            timeout=timeout,
        )
        if not btn:
            logger.warning(f"[Desktop] 未找到按钮: {text}")
            return False
        try:
            btn.Click()
            self._slow()
            return True
        except Exception as e:
            logger.error(f"[Desktop] 点击按钮失败: {e}")
            return False

    def click_point(self, x: int, y: int, button: str = "left") -> bool:
        """点击屏幕绝对坐标"""
        self._ua = self._ua or _import_uiautomation()
        logger.info(f"[Desktop] 点击坐标: ({x}, {y}) button={button}")
        try:
            self._ua.Click(x, y, waitTime=0.1)
            self._slow()
            return True
        except Exception as e:
            logger.error(f"[Desktop] 点击坐标失败: {e}")
            return False

    def click_image(
        self,
        template_path: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        confidence: float = 0.8,
        timeout: float = 10,
    ) -> bool:
        """通过图像识别点击（截图匹配）"""
        start = time.time()
        while time.time() - start < timeout:
            pos = self.find_image(template_path, region=region, confidence=confidence)
            if pos:
                self.click_point(pos[0], pos[1])
                return True
            time.sleep(0.5)
        logger.warning(f"[Desktop] 图像未出现: {template_path}")
        return False

    def double_click(self, text: str = None, x: int = None, y: int = None) -> bool:
        """双击按钮或坐标"""
        self._ua = self._ua or _import_uiautomation()
        if text:
            ctrl = self._find_text_control(
                control_types=["ButtonControl", "ListItemControl", "TreeItemControl"],
                text=text,
                timeout=3,
            )
            if ctrl:
                ctrl.DoubleClick()
                self._slow()
                return True
            return False
        if x is not None and y is not None:
            self._ua.RightClick(x, y)
            return True
        return False

    def right_click(self, text: str = None, x: int = None, y: int = None) -> bool:
        """右键点击"""
        self._ua = self._ua or _import_uiautomation()
        if text:
            ctrl = self._find_text_control(
                control_types=["ListItemControl", "TreeItemControl", "ButtonControl"],
                text=text,
                timeout=3,
            )
            if ctrl:
                ctrl.RightClick()
                return True
            return False
        if x is not None and y is not None:
            self._ua.RightClick(x, y)
            return True
        return False

    # ==================== 输入操作 ====================
    def fill_input(
        self,
        label: str,
        value: str,
        timeout: float = 5,
        clear_first: bool = True,
    ) -> bool:
        """填写输入框（按标签找输入框）"""
        logger.info(f"[Desktop] 填充: {label} = {value}")
        edit = self._find_edit_by_label(label, timeout=timeout)
        if not edit:
            edits = self._find_controls(control_type="EditControl", depth=8)
            edits = [e for e in edits if e.IsKeyboardFocusable and not e.IsOffscreen]
            if not edits:
                logger.warning(f"[Desktop] 未找到输入框: {label}")
                return False
            edit = edits[0]
            logger.info(f"[Desktop] 标签未找到，使用第一个输入框兜底")
        try:
            edit.SetFocus()
            time.sleep(0.1)
            if clear_first:
                edit.GetValue()
                self._ua.SendKeys("{Ctrl}a")
                time.sleep(0.05)
                self._ua.SendKeys("{Delete}")
                time.sleep(0.05)
            self._type_text(value)
            self._slow()
            return True
        except Exception as e:
            logger.error(f"[Desktop] 填写失败: {e}")
            return False

    def fill_by_automation_id(
        self,
        automation_id: str,
        value: str,
        clear_first: bool = True,
    ) -> bool:
        """通过AutomationId填写输入框（精准定位）"""
        logger.info(f"[Desktop] 按AutomationId填写: {automation_id} = {value}")
        ctrls = self._find_controls(
            control_type="EditControl",
            automation_id=automation_id,
            depth=10,
        )
        if not ctrls:
            logger.warning(f"[Desktop] 未找到AutomationId为{automation_id}的输入框")
            return False
        edit = ctrls[0]
        try:
            edit.SetFocus()
            time.sleep(0.1)
            if clear_first:
                self._ua.SendKeys("{Ctrl}a")
                time.sleep(0.05)
                self._ua.SendKeys("{Delete}")
                time.sleep(0.05)
            self._type_text(value)
            return True
        except Exception as e:
            logger.error(f"[Desktop] 按AutomationId填写失败: {e}")
            return False

    def type_text(self, text: str) -> bool:
        """在当前焦点控件中输入文本"""
        self._ua = self._ua or _import_uiautomation()
        try:
            self._type_text(text)
            return True
        except Exception as e:
            logger.error(f"[Desktop] 输入文本失败: {e}")
            return False

    def press_key(self, key: str) -> bool:
        """按键（如Enter/Esc/Tab/F5）"""
        self._ua = self._ua or _import_uiautomation()
        logger.info(f"[Desktop] 按键: {key}")
        try:
            self._ua.SendKeys(key)
            self._slow()
            return True
        except Exception as e:
            logger.error(f"[Desktop] 按键失败: {e}")
            return False

    def _type_text(self, text: str):
        """内部文本输入，处理特殊字符"""
        self._ua = self._ua or _import_uiautomation()
        if any(ord(c) > 127 for c in text):
            import subprocess
            try:
                subprocess.Popen(
                    ["powershell", "-Command", f"Set-Clipboard -Value '{text}'"],
                    shell=True,
                ).wait(timeout=2)
                time.sleep(0.1)
                self._ua.SendKeys("{Ctrl}v")
            except Exception:
                self._ua.SendKeys(text, waitTime=0.05)
        else:
            self._ua.SendKeys(text, waitTime=0.05)

    # ==================== 菜单/选择操作 ====================
    def select_menu(self, menu_path: List[str], wait_each: float = 0.3) -> bool:
        """多级菜单选择"""
        if not menu_path:
            return False
        logger.info(f"[Desktop] 选择菜单: {' > '.join(menu_path)}")
        self._ua = self._ua or _import_uiautomation()
        try:
            root = self._root()
            menu_bar = self._find_controls(control_type="MenuBarControl", depth=3, root=root)
            if not menu_bar:
                menu_bar = self._find_controls(control_type="MenuControl", depth=3, root=root)
            if not menu_bar:
                logger.warning("[Desktop] 未找到菜单栏")
                return False
            menu_bar = menu_bar[0]
            current = menu_bar
            for i, item_text in enumerate(menu_path):
                found = False
                for child in current.GetChildren():
                    if item_text in (child.Name or ""):
                        if i == 0:
                            child.Click()
                        else:
                            child.MoveMouseToMyCenter()
                            time.sleep(wait_each)
                            child.Click()
                        current = child
                        found = True
                        time.sleep(wait_each)
                        break
                if not found:
                    logger.warning(f"[Desktop] 菜单项未找到: {item_text}")
                    return False
            self._slow()
            return True
        except Exception as e:
            logger.error(f"[Desktop] 选择菜单失败: {e}")
            return False

    def select_combobox(self, label: str, value: str, exact: bool = False) -> bool:
        """下拉框选择"""
        logger.info(f"[Desktop] 选择下拉框: {label} -> {value}")
        combo = self._find_edit_by_label(label, control_type="ComboBoxControl", timeout=5)
        if not combo:
            combos = self._find_controls(control_type="ComboBoxControl", depth=8)
            combo = combos[0] if combos else None
        if not combo:
            logger.warning(f"[Desktop] 未找到下拉框: {label}")
            return False
        try:
            combo.Click()
            time.sleep(0.3)
            self._ua = self._ua or _import_uiautomation()
            for _ in range(10):
                items = self._find_controls(
                    control_type="ListItemControl",
                    name=value if exact else None,
                    depth=15,
                )
                if items:
                    items[0].Click()
                    self._slow()
                    return True
                all_items = self._find_controls(
                    control_type="ListItemControl",
                    depth=15,
                )
                for item in all_items:
                    if value in (item.Name or ""):
                        item.Click()
                        self._slow()
                        return True
                time.sleep(0.2)
            return False
        except Exception as e:
            logger.error(f"[Desktop] 下拉框选择失败: {e}")
            return False

    def check(self, label: str, checked: bool = True) -> bool:
        """勾选/取消勾选复选框"""
        ctrl = self._find_text_control(
            control_types=["CheckBoxControl", "ButtonControl"],
            text=label,
            timeout=3,
        )
        if not ctrl:
            return False
        try:
            current = ctrl.GetToggleState()
            target = 1 if checked else 0
            if current != target:
                ctrl.Click()
            return True
        except Exception:
            return False

    # ==================== 表格操作 ====================
    def get_table_data(
        self,
        table_label: Optional[str] = None,
        max_rows: int = 1000,
    ) -> List[List[str]]:
        """提取表格数据"""
        logger.info(f"[Desktop] 提取表格数据" + (f"（{table_label}）" if table_label else ""))
        for ctrl_type in ["DataGridControl", "TableControl", "ListControl"]:
            grids = self._find_controls(control_type=ctrl_type, depth=10)
            if grids:
                grid = grids[0]
                return self._extract_grid(grid, max_rows)
        logger.warning("[Desktop] 未找到表格控件")
        return []

    def _extract_grid(self, grid_control, max_rows: int) -> List[List[str]]:
        """从DataGrid控件提取数据"""
        rows = []
        try:
            for row_idx, row in enumerate(grid_control.GetChildren()):
                if row_idx >= max_rows:
                    break
                row_data = []
                for cell in row.GetChildren():
                    text = cell.Name or ""
                    try:
                        val = cell.GetValue()
                        if val:
                            text = str(val)
                    except Exception:
                        pass
                    row_data.append(text)
                if row_data:
                    rows.append(row_data)
        except Exception as e:
            logger.error(f"[Desktop] 表格数据提取失败: {e}")
        return rows

    # ==================== 文件/导出操作 ====================
    def export_file(
        self,
        save_path: str,
        trigger_button: str = "导出",
        confirm_in_dialog: bool = True,
        confirm_text: str = "保存",
        timeout: float = 30,
    ) -> Optional[str]:
        """通用导出文件流程"""
        logger.info(f"[Desktop] 导出文件: {save_path}")
        if not self.click_button(trigger_button, timeout=5):
            return None

        if not confirm_in_dialog:
            time.sleep(2)
            return save_path if os.path.exists(save_path) else None

        self._ua = self._ua or _import_uiautomation()
        save_dialog = None
        start = time.time()
        while time.time() - start < timeout / 2:
            for title in ["保存", "另存为", "Save As", "Export"]:
                win = self._ua.WindowControl(searchDepth=1, Name=title)
                if win.Exists(0.3):
                    save_dialog = win
                    break
            if save_dialog:
                break
            time.sleep(0.5)

        if not save_dialog:
            logger.warning("[Desktop] 未出现保存对话框")
            return None

        edits = self._find_controls(
            control_type="EditControl",
            depth=10,
            root=save_dialog,
        )
        if not edits:
            logger.warning("[Desktop] 保存对话框中未找到文件名输入框")
            return None

        target_edit = None
        for edit in edits:
            if not edit.IsOffscreen and edit.IsKeyboardFocusable:
                target_edit = edit
        if not target_edit:
            target_edit = edits[-1]

        try:
            target_edit.SetFocus()
            time.sleep(0.1)
            self._ua.SendKeys("{Ctrl}a")
            time.sleep(0.05)
            self._ua.SendKeys("{Delete}")
            time.sleep(0.05)
            self._type_text(save_path)
            time.sleep(0.3)
            self.click_button(confirm_text, timeout=5)
            start = time.time()
            while time.time() - start < timeout:
                if os.path.exists(save_path):
                    size1 = os.path.getsize(save_path)
                    time.sleep(0.5)
                    size2 = os.path.getsize(save_path)
                    if size1 == size2 and size1 > 0:
                        logger.info(f"[Desktop] 导出完成: {save_path}")
                        return save_path
                time.sleep(0.5)
            logger.warning("[Desktop] 文件未生成")
            return None
        except Exception as e:
            logger.error(f"[Desktop] 导出失败: {e}")
            return None

    def wait_file(self, file_path: str, timeout: float = 60) -> bool:
        """等待文件出现且大小稳定"""
        start = time.time()
        while time.time() - start < timeout:
            if os.path.exists(file_path):
                size1 = os.path.getsize(file_path)
                time.sleep(0.5)
                size2 = os.path.getsize(file_path)
                if size1 == size2 and size1 > 0:
                    return True
            time.sleep(0.5)
        return False

    # ==================== 等待/状态判断 ====================
    def wait_window(self, title: str, timeout: float = 30) -> bool:
        """等待指定标题的窗口出现"""
        self._ua = self._ua or _import_uiautomation()
        start = time.time()
        while time.time() - start < timeout:
            win = self._ua.WindowControl(searchDepth=1, Name=title)
            if win.Exists(0.3):
                return True
            time.sleep(0.5)
        return False

    def wait_text(self, text: str, timeout: float = 15) -> bool:
        """等待指定文本出现"""
        start = time.time()
        while time.time() - start < timeout:
            ctrl = self._find_text_control(
                control_types=None,
                text=text,
                timeout=0.5,
            )
            if ctrl:
                return True
            time.sleep(0.5)
        return False

    def wait_image(self, template_path: str, timeout: float = 15, confidence: float = 0.8) -> bool:
        """等待指定图像出现"""
        start = time.time()
        while time.time() - start < timeout:
            if self.find_image(template_path, confidence=confidence):
                return True
            time.sleep(0.5)
        return False

    def is_window_exists(self, title: str) -> bool:
        """检查窗口是否存在"""
        self._ua = self._ua or _import_uiautomation()
        win = self._ua.WindowControl(searchDepth=1, Name=title)
        return win.Exists(0.3)

    def get_text(self, label: str = None, control_type: str = None) -> Optional[str]:
        """获取控件文本"""
        ctrl = self._find_text_control(
            control_types=[control_type] if control_type else None,
            text=label,
            timeout=2,
        )
        if ctrl:
            return ctrl.Name or ""
        return None

    # ==================== 截图/图像识别 ====================
    def screenshot(self, save_path: str = None, region: Tuple[int, int, int, int] = None) -> Optional[str]:
        """截图"""
        from PIL import ImageGrab
        if not save_path:
            save_dir = _PROJECT_ROOT / "data" / "screenshots"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = str(save_dir / f"desktop_{int(time.time())}.png")
        try:
            if region:
                img = ImageGrab.grab(bbox=region)
            else:
                img = ImageGrab.grab()
            img.save(save_path)
            logger.info(f"[Desktop] 截图保存: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"[Desktop] 截图失败: {e}")
            return None

    def find_image(
        self,
        template_path: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        confidence: float = 0.8,
    ) -> Optional[Tuple[int, int]]:
        """在屏幕中查找模板图像，返回中心坐标"""
        cv2, np = _import_cv2()
        from PIL import ImageGrab
        if not os.path.exists(template_path):
            logger.warning(f"[Desktop] 模板图片不存在: {template_path}")
            return None
        try:
            screen = ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
            screen_np = np.array(screen)
            screen_bgr = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)
            template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template is None:
                logger.warning(f"[Desktop] 模板图片读取失败: {template_path}")
                return None
            result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            if max_val >= confidence:
                h, w = template.shape[:2]
                center_x = max_loc[0] + w // 2
                center_y = max_loc[1] + h // 2
                if region:
                    center_x += region[0]
                    center_y += region[1]
                return (center_x, center_y)
            return None
        except Exception as e:
            logger.error(f"[Desktop] 图像识别失败: {e}")
            return None

    # ==================== 内部辅助：控件查找 ====================
    def _find_text_control(
        self,
        control_types: Optional[List[str]],
        text: str,
        exact: bool = False,
        timeout: float = 3,
    ) -> Optional[Any]:
        """按文本查找控件"""
        self._ua = self._ua or _import_uiautomation()
        start = time.time()
        while time.time() - start < timeout:
            root = self._root()
            types_to_search = control_types or [
                "ButtonControl", "MenuItemControl", "TextControl",
                "ListItemControl", "TreeItemControl", "CheckBoxControl",
                "RadioButtonControl", "HyperlinkControl", "LabelControl",
            ]
            for ctrl_type in types_to_search:
                type_cls = getattr(self._ua, ctrl_type, None)
                if not type_cls:
                    continue
                if exact:
                    ctrl = type_cls(root, Name=text, searchDepth=15)
                    if ctrl.Exists(0.1):
                        return ctrl
                else:
                    ctrls = self._find_controls(
                        control_type=ctrl_type,
                        depth=15,
                        root=root,
                    )
                    for c in ctrls:
                        if text in (c.Name or ""):
                            return c
            time.sleep(0.3)
        return None

    def _find_edit_by_label(
        self,
        label: str,
        control_type: str = "EditControl",
        timeout: float = 5,
    ) -> Optional[Any]:
        """通过标签查找邻近的输入框/下拉框"""
        self._ua = self._ua or _import_uiautomation()
        start = time.time()
        while time.time() - start < timeout:
            label_ctrl = None
            for label_type in ["TextControl", "LabelControl", "ButtonControl"]:
                ctrls = self._find_controls(control_type=label_type, depth=15)
                for c in ctrls:
                    if label in (c.Name or ""):
                        label_ctrl = c
                        break
                if label_ctrl:
                    break
            if not label_ctrl:
                time.sleep(0.3)
                continue

            try:
                parent = label_ctrl.GetParent()
                if parent:
                    children = parent.GetChildren()
                    found_label = False
                    for child in children:
                        if child == label_ctrl:
                            found_label = True
                            continue
                        if found_label:
                            child_type = child.ControlType
                            target_type = getattr(self._ua.ControlType, control_type, None)
                            if target_type and child_type == target_type:
                                return child
                            if control_type == "EditControl" and child_type == getattr(self._ua.ControlType, "ComboBoxControl", None):
                                return child
            except Exception:
                pass

            target_type_cls = getattr(self._ua, control_type, None)
            if target_type_cls:
                ctrl = target_type_cls(self._root(), searchDepth=15)
                if ctrl.Exists(0.1):
                    return ctrl
            time.sleep(0.3)
        return None


# ==================== 异步包装器（适配项目async风格）====================
class AsyncDesktop:
    """
    Desktop的异步包装器

    项目workflow脚本是async的，用AsyncDesktop可以在async函数中调用
    内部用asyncio.to_thread包装同步uiautomation调用

    用法：
        async with AsyncDesktop(app_name="金蝶K/3") as d:
            await d.click_button("登录")
            await d.fill_input("用户名", "admin")
    """

    def __init__(self, **kwargs):
        self._desktop = Desktop(**kwargs)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()
        return False

    async def start(self):
        await asyncio.to_thread(self._desktop.start)
        return self

    async def close(self):
        await asyncio.to_thread(self._desktop.close)

    def __getattr__(self, name):
        """代理所有方法为异步调用"""
        attr = getattr(self._desktop, name)
        if callable(attr):
            async def _wrapper(*args, **kwargs):
                return await asyncio.to_thread(attr, *args, **kwargs)
            return _wrapper
        return attr
