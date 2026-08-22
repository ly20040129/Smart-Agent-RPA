# -*- coding: utf-8 -*-
"""
任务队列管理器 - 支持任务并行执行与排队

核心能力：
1. 全局并发数限制（默认最多同时跑 5 个任务，避免资源耗尽）
2. 同一任务（task_id 相同）串行化：后面的请求排队等待前面完成
3. 不同任务之间并行运行
4. 可以查询队列状态：等待中 / 运行中 / 已完成
5. 支持取消等待中的任务

使用：
    from src.agent.task_queue import task_queue_manager

    # 提交任务
    job_id = await task_queue_manager.submit(
        task_id="xxx",
        task_name="yyy",
        user_info={...},
        user_params={...},
        run_fn=async_fn,
        on_status_change=callback,
    )

    # 查询状态
    status = task_queue_manager.get_status(job_id)
    queue_snapshot = task_queue_manager.snapshot()
"""
import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

try:
    from src.storage import storage_manager
except Exception:  # 测试或无storage依赖场景兜底
    storage_manager = None


class JobStatus(str, Enum):
    PENDING = "pending"       # 排队中
    RUNNING = "running"       # 运行中
    SUCCESS = "success"       # 执行成功
    FAILED = "failed"         # 执行失败
    CANCELLED = "cancelled"   # 被取消


@dataclass
class Job:
    job_id: str
    task_id: str
    task_name: str
    user_info: Optional[dict]
    user_params: Optional[dict]
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Any] = None
    # 实际执行的异步函数：async def run_fn(task_executor_instance_set_user)
    _run_fn: Optional[Callable[[], Awaitable[Any]]] = None
    # 状态变化回调：callback(job)
    _on_status: Optional[Callable[["Job"], None]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_sec": (
                round((self.finished_at or time.time()) - self.started_at, 1)
                if self.started_at else None
            ),
            "error": self.error,
            "result_summary": str(self.result)[:200] if self.result else None,
            "username": (self.user_info or {}).get("username", ""),
        }


class TaskQueueManager:
    """
    任务队列管理器

    - 全局 Semaphore 限制最大并发数
    - 每个 task_id 有一个自己的锁，保证同一任务的执行串行化
    """

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        # 每个 task_id 一把锁，保证同一任务的多个 job 串行
        self._task_locks: Dict[str, asyncio.Lock] = {}
        # 全部 job（包含已完成的，最近 N 个）
        self._jobs: Dict[str, Job] = {}
        # 按 task_id 分组
        self._jobs_by_task: Dict[str, List[str]] = {}
        self._history_limit = 200  # 最多保留历史记录数
        self._lock = asyncio.Lock()  # 保护内部字典

    def _build_dedup_key(self, task_id: str, user_info: Optional[dict], user_params: Optional[dict]) -> str:
        """构造提交去重键：同一用户 + 同一任务 + 相同参数 = 同一个键"""
        username = (user_info or {}).get("username", "") or "__guest__"
        try:
            params_str = json.dumps(user_params or {}, ensure_ascii=False, sort_keys=True)
        except Exception:
            params_str = str(user_params)
        params_hash = hashlib.md5(params_str.encode("utf-8")).hexdigest()[:10]
        return f"{task_id}:{username}:{params_hash}"

    def _find_same_job_locked(self, dedup_key: str, task_id: str, user_info: Optional[dict], user_params: Optional[dict]) -> Optional[Job]:
        """内存兜底：在当前进程的 job 里找 60 秒内同用户/同参数/同任务的运行/等待中 job，命中则直接复用"""
        now = time.time()
        username = (user_info or {}).get("username", "") or "__guest__"
        for job in self._jobs.values():
            if job.task_id != task_id:
                continue
            if ((job.user_info or {}).get("username", "") or "__guest__") != username:
                continue
            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.SUCCESS, JobStatus.FAILED):
                continue
            # 命中去重只看最近 120s 内的（与 Redis TTL 对齐）
            if now - job.created_at > 120:
                continue
            try:
                a = json.dumps(job.user_params or {}, ensure_ascii=False, sort_keys=True)
                b = json.dumps(user_params or {}, ensure_ascii=False, sort_keys=True)
            except Exception:
                a, b = str(job.user_params), str(user_params)
            if a == b:
                return job
        return None

    async def submit(
        self,
        *,
        task_id: str,
        task_name: str,
        user_info: Optional[dict] = None,
        user_params: Optional[dict] = None,
        run_fn: Callable[[], Awaitable[Any]],
        on_status_change: Optional[Callable[[Job], None]] = None,
    ) -> str:
        """
        提交一个任务到队列，立即返回 job_id。

        去重规则（短时间内同用户同参数）：
        - 若 Redis 命中去重键且对应 job 仍存在：直接复用已有 job_id，不新建，不报错
        - 若未命中：创建新 job，后台执行
        """
        dedup_key = self._build_dedup_key(task_id, user_info, user_params)

        # --- 第 1 步：内存内快速兜底命中（Redis 未开时也能去重） ---
        async with self._lock:
            existed = self._find_same_job_locked(dedup_key, task_id, user_info, user_params)
            if existed is not None:
                logger.info(
                    f"[TaskQueue] 命中内存去重，复用 job={existed.job_id} "
                    f"task={task_id} user={(user_info or {}).get('username', '')}"
                )
                self._notify(existed)
                return existed.job_id

        # --- 第 2 步：Redis 级去重（跨进程/单机重启后仍能命中短时间重复） ---
        reused_job_id: Optional[str] = None
        if storage_manager is not None and storage_manager.is_redis_available:
            existed_job_id = storage_manager.get_submit_dedup_job(dedup_key)
            if existed_job_id:
                async with self._lock:
                    job = self._jobs.get(existed_job_id)
                # 内存里还有就直接复用
                if job is not None:
                    reused_job_id = job.job_id
                else:
                    # 内存里没有（例如进程刚重启），仍视为同一次提交，返回 Redis 里保存的 job_id
                    reused_job_id = existed_job_id
                logger.info(
                    f"[TaskQueue] 命中Redis去重，复用 job={reused_job_id} "
                    f"task={task_id} user={(user_info or {}).get('username', '')}"
                )
                return reused_job_id

        # --- 第 3 步：新建 job ---
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            job_id=job_id,
            task_id=task_id,
            task_name=task_name,
            user_info=user_info,
            user_params=user_params,
            _run_fn=run_fn,
            _on_status=on_status_change,
        )
        async with self._lock:
            self._jobs[job_id] = job
            self._jobs_by_task.setdefault(task_id, []).append(job_id)
            # 取 task 级别的锁（懒创建）
            if task_id not in self._task_locks:
                self._task_locks[task_id] = asyncio.Lock()
            task_lock = self._task_locks[task_id]
            self._prune_history_locked()

        # Redis 去重键 TTL 2 分钟：在此期间重复点击会直接复用同一个 job_id
        if storage_manager is not None:
            try:
                storage_manager.mark_submit_dedup(dedup_key, job_id, ttl_seconds=120)
            except Exception as _e:
                logger.warning(f"[TaskQueue] mark_submit_dedup 失败: {_e}")

        logger.info(f"[TaskQueue] 提交任务 job={job_id} task={task_id} name={task_name}")
        self._notify(job)

        # 后台启动：先等 task 级锁（同任务串行），再等全局信号量
        asyncio.create_task(self._run_job(job, task_lock))
        return job_id

    async def _run_job(self, job: Job, task_lock: asyncio.Lock):
        """执行单个 job 的包装逻辑"""
        try:
            # --- 阶段 1：等待同一 task_id 上的前一个 job 完成 ---
            async with task_lock:
                # --- 阶段 2：拿到全局并发额度 ---
                async with self._sem:
                    # 更新为 running
                    async with self._lock:
                        job.status = JobStatus.RUNNING
                        job.started_at = time.time()
                    logger.info(
                        f"[TaskQueue] 开始执行 job={job.job_id} "
                        f"task={job.task_id} queue_len_pending={self._count_pending()}"
                    )
                    self._notify(job)

                    try:
                        if job._run_fn is None:
                            raise RuntimeError("job.run_fn 为空")
                        # 把 job_id 作为上下文传给 run_fn（通过函数元信息注入或直接做关键字兜底）
                        import inspect
                        sig = inspect.signature(job._run_fn)
                        if "job_id" in sig.parameters:
                            result = await job._run_fn(job_id=job.job_id)
                        else:
                            result = await job._run_fn()
                        job.result = result
                        job.status = JobStatus.SUCCESS
                        logger.info(f"[TaskQueue] ✅ job={job.job_id} 成功")
                    except Exception as e:
                        job.status = JobStatus.FAILED
                        job.error = str(e)
                        logger.exception(f"[TaskQueue] ❌ job={job.job_id} 失败: {e}")
                    finally:
                        job.finished_at = time.time()
                        self._notify(job)
        except Exception as e:
            # 不应该走到这里，兜底
            job.status = JobStatus.FAILED
            job.error = f"队列异常: {e}"
            job.finished_at = time.time()
            logger.exception(f"[TaskQueue] job={job.job_id} 队列级异常: {e}")
            self._notify(job)

    async def cancel_job(self, job_id: str) -> bool:
        """取消一个 PENDING 的 job。运行中的任务无法取消（会返回 False）。"""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status != JobStatus.PENDING:
                return False
            job.status = JobStatus.CANCELLED
            job.finished_at = time.time()
            logger.info(f"[TaskQueue] job={job_id} 已取消")
        self._notify(job)
        return True

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def snapshot(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取队列快照，按创建时间倒序"""
        if task_id:
            ids = list(self._jobs_by_task.get(task_id, []))
        else:
            ids = list(self._jobs.keys())
        jobs = [self._jobs[i] for i in ids if i in self._jobs]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return [j.to_dict() for j in jobs]

    def summary(self) -> Dict[str, Any]:
        """快速统计"""
        counts = {s.value: 0 for s in JobStatus}
        for j in self._jobs.values():
            counts[j.status.value] = counts.get(j.status.value, 0) + 1
        return {
            "max_concurrent": self.max_concurrent,
            "counts": counts,
            "total": len(self._jobs),
        }

    # ---------- 内部 ----------

    def _count_pending(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == JobStatus.PENDING)

    def _notify(self, job: Job):
        if job._on_status:
            try:
                job._on_status(job)
            except Exception as e:
                logger.warning(f"[TaskQueue] status callback 异常: {e}")

    def _prune_history_locked(self):
        """调用方必须已持有 self._lock。清理超出历史上限的已结束 job。"""
        if len(self._jobs) <= self._history_limit:
            return
        # 只清理 finished / cancelled / success / failed 的，并且按时间从老到新
        finished = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        finished.sort(key=lambda j: j.created_at)
        over = len(self._jobs) - self._history_limit
        for j in finished[:over]:
            self._jobs.pop(j.job_id, None)
            lst = self._jobs_by_task.get(j.task_id)
            if lst and j.job_id in lst:
                lst.remove(j.job_id)


# 全局单例（可通过 reset() 重新创建，主要用于测试）
_default_manager: Optional[TaskQueueManager] = None


def get_task_queue_manager(max_concurrent: int = 5) -> TaskQueueManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = TaskQueueManager(max_concurrent=max_concurrent)
    return _default_manager
