# -*- coding: utf-8 -*-
"""
任务管理器 - 支持通过配置文件管理任务，不需要写代码

每个任务就是一份YAML配置，包含：
- 任务名称
- 触发方式（手动/定时）
- 执行步骤（用自然语言描述）
- 数据处理规则

新增任务只需在Web界面填写表单，生成配置即可。
"""
import os
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from loguru import logger

from src.core.config import get_config


class TaskManager:
    """
    任务管理器

    功能：
    1. 读取所有任务配置
    2. 新增任务（保存为YAML配置）
    3. 编辑任务
    4. 启用/禁用任务
    5. 记录执行历史
    """

    def __init__(self):
        self.config = get_config()
        self.tasks_dir = Path("data/tasks")
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

        self.history_dir = Path("data/task_history")
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出所有任务"""
        tasks = []
        for f in self.tasks_dir.glob("*.yaml"):
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    task = yaml.safe_load(fp)
                    task["filename"] = f.stem
                    tasks.append(task)
            except Exception as e:
                logger.error(f"读取任务配置失败 {f}: {e}")

        return tasks

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取单个任务配置"""
        task_path = self.tasks_dir / f"{task_id}.yaml"
        if not task_path.exists():
            return None

        with open(task_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def create_task(self, task_config: Dict[str, Any]) -> str:
        """
        创建新任务

        Args:
            task_config: 任务配置
                {
                    "name": "京东商智竞品数据统计",
                    "description": "通过API接口获取京东商智竞品统计数据",
                    "department": "operations",
                    "enabled": true,
                    "mode": "api",
                    "cookie_key": "jd_shangzhi",
                    "workflow_module": "workflows.jd_shangzhi_jingp_data",
                    "workflow_func": "jd_shangzhi_jingp_data",
                    "params_input": [
                        {"key": "date_str", "label": "查询日期", "required": true, "type": "date"},
                        {"key": "output_dir", "label": "保存位置", "required": true, "type": "path"}
                    ],
                    "schedule": ""
                }

        Returns:
            任务ID
        """
        task_id = task_config.get("name", "task").replace(" ", "_")
        task_path = self.tasks_dir / f"{task_id}.yaml"

        # 添加元数据
        task_config["created_at"] = datetime.now().isoformat()
        task_config["updated_at"] = datetime.now().isoformat()
        task_config["enabled"] = task_config.get("enabled", True)

        with open(task_path, 'w', encoding='utf-8') as f:
            yaml.dump(task_config, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"任务已创建: {task_id}")
        return task_id

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """更新任务配置"""
        task = self.get_task(task_id)
        if not task:
            return False

        task.update(updates)
        task["updated_at"] = datetime.now().isoformat()

        task_path = self.tasks_dir / f"{task_id}.yaml"
        with open(task_path, 'w', encoding='utf-8') as f:
            yaml.dump(task, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"任务已更新: {task_id}")
        return True

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        task_path = self.tasks_dir / f"{task_id}.yaml"
        if task_path.exists():
            task_path.unlink()
            logger.info(f"任务已删除: {task_id}")
            return True
        return False

    def toggle_task(self, task_id: str) -> bool:
        """启用/禁用任务"""
        task = self.get_task(task_id)
        if not task:
            return False

        task["enabled"] = not task.get("enabled", True)
        return self.update_task(task_id, {"enabled": task["enabled"]})

    def save_history(self, task_id: str, result: Dict[str, Any]):
        """保存执行历史"""
        history_file = self.history_dir / f"{task_id}_history.json"

        history = []
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)

        history.append({
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
            "status": result.get("status"),
            "error": result.get("error"),
            "elapsed_time": result.get("elapsed_time")
        })

        # 只保留最近50条
        history = history[-50:]

        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def get_history(self, task_id: str) -> List[Dict]:
        """获取任务执行历史"""
        history_file = self.history_dir / f"{task_id}_history.json"
        if not history_file.exists():
            return []

        with open(history_file, 'r', encoding='utf-8') as f:
            return json.load(f)


# 模块级单例：全项目共用一个（TaskManager 本身无状态，只持有目录路径）。
# api.py 与 task_executor.py 都从这里取，避免各建一个实例造成认知负担。
task_manager = TaskManager()
