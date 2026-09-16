# -*- coding: utf-8 -*-
"""
持久化调度器（借鉴旧项目 bull.ts：启动时注册 → 循环检查 → 到点触发）

不依赖 croniter / apscheduler，自带精简 5-field cron 解析。
调度状态持久化到 Redis（next_run 时间戳），重启不丢失。
"""
import asyncio
import datetime as dt
from typing import Dict, List, Optional
from loguru import logger

from src.agent.task_manager import TaskManager
from src.storage import storage_manager

_SCHEDULE_KEY = "agent:schedules"  # Redis hash: task_id -> next_run ISO


# ==================== 精简 cron 解析 ====================

_FIELD_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]  # min hour dom dow(Mon=0)


def _parse_field(expr: str, lo: int, hi: int) -> set:
    """解析单个 cron 字段为整数集合"""
    if expr == "*":
        return set(range(lo, hi + 1))
    result: set = set()
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if part == "*":
            base = list(range(lo, hi + 1))
        elif "-" in part:
            a, b = part.split("-")
            base = list(range(int(a), int(b) + 1))
        else:
            base = [int(part)]
        result.update(base[::step])
    return {v for v in result if lo <= v <= hi}


def _next_cron(expr: str, now: dt.datetime) -> dt.datetime:
    """计算 cron 表达式在 now 之后的下一次触发时间"""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron 表达式必须是 5 字段: {expr}")
    sets = [_parse_field(parts[i], *_FIELD_RANGES[i]) for i in range(5)]

    candidate = now.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    for _ in range(366 * 1440):  # 最多遍历一年
        if (candidate.minute in sets[0]
                and candidate.hour in sets[1]
                and candidate.day in sets[2]
                and candidate.month in sets[3]
                and candidate.weekday() in sets[4]):
            return candidate
        candidate += dt.timedelta(minutes=1)
    return now + dt.timedelta(days=365)


# ==================== 调度器 ====================

class TaskScheduler:
    """持久化调度器：启动时扫描 YAML → 注册 → 后台循环触发"""

    def __init__(self, task_manager: Optional[TaskManager] = None):
        self.task_manager = task_manager or TaskManager()
        self._task: Optional[asyncio.Task] = None

    # ---- 注册 ----

    def register_all(self) -> int:
        """扫描所有任务 YAML，把带 schedule 的注册到 Redis。返回注册数量。"""
        schedules = self._load_schedules()
        count = 0
        for task_id, task_config in self._iter_tasks():
            cron = (task_config.get("schedule") or "").strip()
            if not cron or not task_config.get("enabled", True):
                schedules.pop(task_id, None)
                continue
            try:
                next_run = _next_cron(cron, dt.datetime.now())
                schedules[task_id] = next_run.isoformat()
                count += 1
                logger.info(f"[Scheduler] 注册 {task_id}: cron='{cron}' 下次={next_run:%Y-%m-%d %H:%M}")
            except Exception as e:
                logger.warning(f"[Scheduler] {task_id} cron 解析失败: {e}")
        self._save_schedules(schedules)
        return count

    def register_one(self, task_id: str) -> bool:
        """单个任务注册/更新调度"""
        task_config = self.task_manager.get_task(task_id)
        if not task_config:
            return False
        cron = (task_config.get("schedule") or "").strip()
        schedules = self._load_schedules()
        if not cron or not task_config.get("enabled", True):
            schedules.pop(task_id, None)
            self._save_schedules(schedules)
            return True
        try:
            schedules[task_id] = _next_cron(cron, dt.datetime.now()).isoformat()
            self._save_schedules(schedules)
            return True
        except Exception as e:
            logger.warning(f"[Scheduler] {task_id} cron 解析失败: {e}")
            return False

    def remove(self, task_id: str) -> None:
        schedules = self._load_schedules()
        schedules.pop(task_id, None)
        self._save_schedules(schedules)

    # ---- 后台循环 ----

    async def start(self, check_interval: int = 60) -> None:
        """启动后台调度循环"""
        self.register_all()
        self._task = asyncio.create_task(self._loop(check_interval))
        logger.info(f"[Scheduler] 后台循环已启动（间隔 {check_interval}s）")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self, interval: int) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Scheduler] tick 异常: {e}")
            await asyncio.sleep(interval)

    async def _tick(self) -> None:
        schedules = self._load_schedules()
        if not schedules:
            return
        now = dt.datetime.now()
        due = [tid for tid, ts in schedules.items()
               if dt.datetime.fromisoformat(ts) <= now]
        if not due:
            return

        for task_id in due:
            logger.info(f"[Scheduler] 触发任务: {task_id}")
            asyncio.create_task(self._run_task(task_id))
            # 计算下次
            cron = (self.task_manager.get_task(task_id) or {}).get("schedule", "")
            if cron:
                schedules[task_id] = _next_cron(cron, now).isoformat()
        self._save_schedules(schedules)

    async def _run_task(self, task_id: str) -> None:
        """实际触发任务执行"""
        try:
            from src.agent.task_executor import TaskExecutor
            executor = TaskExecutor()
            await executor.execute_task(task_id)
        except Exception as e:
            logger.error(f"[Scheduler] 执行 {task_id} 失败: {e}")

    # ---- 辅助 ----

    def _iter_tasks(self):
        """遍历所有任务 YAML，返回 (task_id, config)"""
        tasks_dir = self.task_manager.tasks_dir
        if not tasks_dir.exists():
            return
        for path in tasks_dir.glob("*.yaml"):
            task_id = path.stem
            config = self.task_manager.get_task(task_id)
            if config:
                yield task_id, config

    def list_schedules(self) -> List[Dict]:
        """列出所有调度（API 用）"""
        schedules = self._load_schedules()
        result = []
        for task_id, ts in schedules.items():
            config = self.task_manager.get_task(task_id) or {}
            result.append({
                "task_id": task_id,
                "task_name": config.get("name", task_id),
                "cron": config.get("schedule", ""),
                "next_run": ts,
            })
        return result

    def _load_schedules(self) -> Dict[str, str]:
        if not storage_manager.is_redis_available:
            return {}
        data = storage_manager.redis.get(_SCHEDULE_KEY, {})
        return data if isinstance(data, dict) else {}

    def _save_schedules(self, schedules: Dict[str, str]) -> None:
        if storage_manager.is_redis_available:
            storage_manager.redis.set(_SCHEDULE_KEY, schedules)
