# -*- coding: utf-8 -*-
"""
FastAPI Web服务 - 智能体平台Web界面 v3.0

功能：
1. 部门权限 - 登录、部门隔离、用户管理
2. 任务管理 - 新增/编辑/删除/启停任务，按部门过滤
3. 任务执行 - 手动触发、查看实时状态
4. 执行历史 - 查看历史记录
5. 动态建表 - 为不同任务/部门创建业务数据表
6. 实时日志 - WebSocket推送
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
import os
import tempfile
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger

from src.core.config import get_config
from src.agent.task_manager import TaskManager
from src.agent.task_executor import TaskExecutor
from src.agent.task_queue import get_task_queue_manager, JobStatus
from src.auth import auth_manager
from src.storage import storage_manager

app = FastAPI(title="智能体平台", version="3.0.0")
config = get_config()

# ==================== 中间件 ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 数据模型 ====================
class TaskCreateRequest(BaseModel):
    name: str
    description: str = ""
    schedule: str = ""
    department: str = ""
    steps: List[Dict[str, Any]] = []

class TaskUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    schedule: Optional[str] = None
    department: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    department: str
    role: str = "user"

class CreateTableRequest(BaseModel):
    table_name: str
    columns: List[Dict[str, str]]

# ==================== 认证依赖 ====================
async def get_current_user(request: Request) -> Optional[dict]:
    """从请求中获取当前用户（未登录返回None）"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        user = auth_manager.verify_token(token)
        return user
    return None

async def require_auth(request: Request) -> dict:
    """要求已登录，否则返回401"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(401, "未登录或登录已过期")
    return user

async def require_admin(request: Request) -> dict:
    """要求管理员权限"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(401, "未登录或登录已过期")
    if user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


# ==================== WebSocket管理 ====================
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in self.active:
            try:
                await ws.send_json(message)
            except:
                pass


manager = ConnectionManager()
task_manager = TaskManager()
task_queue = get_task_queue_manager(max_concurrent=5)  # 最多同时跑 5 个任务

# ==================== 模板管理 ====================
from src.agent.template_manager import TemplateManager
template_mgr = TemplateManager()


# ==================== 挂载静态文件（CSS/JS/HTML 资源）====================
from fastapi.staticfiles import StaticFiles
_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ==================== 页面路由（动态读取 html 文件，方便修改不用重启）====================
@app.get("/", response_class=HTMLResponse)
async def index():
    return html_templates.get_index_page()

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return html_templates.get_login_page()


# ==================== 认证API ====================
@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """登录"""
    user = auth_manager.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    token = auth_manager.generate_token(user)
    return {"status": "success", "token": token, "user": user}

@app.get("/api/auth/me")
async def get_me(user: dict = Depends(require_auth)):
    """获取当前用户信息"""
    return user

@app.post("/api/auth/logout")
async def logout():
    """登出（前端删除token即可）"""
    return {"status": "success"}


# ==================== 用户管理API（管理员）====================
@app.get("/api/users")
async def list_users(user: dict = Depends(require_admin)):
    """列出所有用户"""
    return {"users": auth_manager.list_users()}

@app.post("/api/users")
async def create_user(req: CreateUserRequest, user: dict = Depends(require_admin)):
    """创建用户"""
    success = auth_manager.create_user(req.username, req.password, req.department, req.role)
    if not success:
        raise HTTPException(400, "用户已存在")
    return {"status": "success"}

@app.delete("/api/users/{username}")
async def delete_user(username: str, user: dict = Depends(require_admin)):
    """删除用户"""
    success = auth_manager.delete_user(username)
    if not success:
        raise HTTPException(400, "无法删除")
    return {"status": "success"}


# ==================== 部门管理API（管理员）====================
@app.get("/api/departments")
async def list_departments(user: dict = Depends(require_auth)):
    """列出所有部门"""
    return {"departments": auth_manager.list_departments()}

@app.post("/api/departments/{dept_id}")
async def create_department(dept_id: str, req: dict, user: dict = Depends(require_admin)):
    """创建部门"""
    success = auth_manager.create_department(dept_id, req.get("name",""), req.get("description",""))
    if not success:
        raise HTTPException(400, "部门已存在")
    return {"status": "success"}

@app.delete("/api/departments/{dept_id}")
async def delete_department(dept_id: str, user: dict = Depends(require_admin)):
    """删除部门"""
    success = auth_manager.delete_department(dept_id)
    if not success:
        raise HTTPException(400, "无法删除")
    return {"status": "success"}


# ==================== 任务管理API ====================
@app.get("/api/tasks")
async def list_tasks(user: dict = Depends(require_auth)):
    """获取任务列表（按部门过滤）"""
    all_tasks = task_manager.list_tasks()
    # 管理员看全部，普通用户只看本部门的
    if user.get("role") == "admin":
        return {"tasks": all_tasks}
    user_dept = user.get("department", "")
    filtered = [t for t in all_tasks if t.get("department", "") == user_dept or not t.get("department")]
    return {"tasks": filtered}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, user: dict = Depends(require_auth)):
    """获取单个任务详情"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    # 权限检查
    if user.get("role") != "admin" and task.get("department") and task["department"] != user.get("department"):
        raise HTTPException(403, "无权访问此任务")
    return task

@app.post("/api/tasks")
async def create_task(req: TaskCreateRequest, user: dict = Depends(require_auth)):
    """创建新任务"""
    task_config = {
        "name": req.name,
        "description": req.description,
        "schedule": req.schedule,
        "department": req.department or user.get("department", ""),
        "enabled": True,
        "steps": req.steps
    }
    task_id = task_manager.create_task(task_config)
    
    # 如果指定了部门，自动创建业务数据表
    if req.department and storage_manager.is_mysql_available:
        storage_manager.mysql.create_business_table(f"{req.department}_{task_id}", [
            {"name": "id", "type": "INT AUTO_INCREMENT PRIMARY KEY"},
            {"name": "task_id", "type": "VARCHAR(100)", "comment": "任务ID"},
            {"name": "task_name", "type": "VARCHAR(200)", "comment": "任务名称"},
            {"name": "data_key", "type": "VARCHAR(200)", "comment": "数据键"},
            {"name": "data_value", "type": "TEXT", "comment": "数据值"},
            {"name": "remark", "type": "VARCHAR(500)", "comment": "备注"},
        ])
    
    return {"status": "success", "task_id": task_id}

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, req: TaskUpdateRequest, user: dict = Depends(require_auth)):
    """更新任务"""
    updates = {k: v for k, v in req.dict().items() if v is not None}
    success = task_manager.update_task(task_id, updates)
    if not success:
        raise HTTPException(404, "任务不存在")
    return {"status": "success"}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, user: dict = Depends(require_auth)):
    """删除任务"""
    success = task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(404, "任务不存在")
    return {"status": "success"}

@app.post("/api/tasks/{task_id}/toggle")
async def toggle_task(task_id: str, user: dict = Depends(require_auth)):
    """启用/禁用任务"""
    success = task_manager.toggle_task(task_id)
    if not success:
        raise HTTPException(404, "任务不存在")
    task = task_manager.get_task(task_id)
    return {"status": "success", "enabled": task.get("enabled")}

class RunTaskRequest(BaseModel):
    params: Optional[Dict[str, Any]] = None

@app.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str, req: RunTaskRequest = None, user: dict = Depends(require_auth)):
    """手动执行任务（支持传入用户参数）- 提交到任务队列，支持并行执行"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    user_params = req.params if req else None
    task_name = task.get("name", task_id)

    # 构造 run_fn：封装原先 _run_task_background 的逻辑，供队列执行
    async def run_fn():
        # 这里用局部变量捕获外面的 task_id, user_params, user
        await manager.broadcast({
            "type": "status",
            "message": f"任务 [{task_name}] 开始执行...",
            "task_id": task_id,
        })
        executor = TaskExecutor()
        if user:
            executor.set_user(user)
        result = await executor.execute_task(task_id, user_params=user_params)
        if result.get("status") == "success":
            await manager.broadcast({
                "type": "success",
                "message": f"任务 [{task_name}] 执行成功，耗时 {result.get('elapsed_time')}秒",
                "task_id": task_id,
                "result": {k: v for k, v in result.items() if k != "context"},
            })
        else:
            await manager.broadcast({
                "type": "error",
                "message": f"任务 [{task_name}] 执行失败: {result.get('error')}",
                "task_id": task_id,
                "error": result.get("error"),
            })
        return result

    # 状态变化时通过 WebSocket 推送队列状态
    def on_status_change(job):
        payload = {
            "type": "queue",
            "job": job.to_dict(),
            "queue_summary": task_queue.summary(),
        }
        asyncio.create_task(manager.broadcast(payload))

    job_id = await task_queue.submit(
        task_id=task_id,
        task_name=task_name,
        user_info=user,
        user_params=user_params,
        run_fn=run_fn,
        on_status_change=on_status_change,
    )

    # 顺便立即推一下队列整体状态
    await manager.broadcast({
        "type": "queue_summary",
        "summary": task_queue.summary(),
        "jobs": task_queue.snapshot(task_id)[:20],
    })

    return {"status": "queued", "task_id": task_id, "job_id": job_id}

@app.get("/api/tasks/{task_id}/history")
async def get_history(task_id: str, user: dict = Depends(require_auth)):
    """获取任务执行历史"""
    history = task_manager.get_history(task_id)
    return {"history": history}


# ==================== 任务队列 API ====================
@app.get("/api/queue/summary")
async def get_queue_summary(user: dict = Depends(require_auth)):
    """获取队列概览（运行中/等待中/成功/失败计数）"""
    return {"summary": task_queue.summary()}


@app.get("/api/queue/jobs")
async def get_queue_jobs(
    task_id: Optional[str] = None,
    limit: int = 100,
    user: dict = Depends(require_auth),
):
    """获取队列任务列表。管理员看全部，普通用户只看自己部门可见的任务"""
    all_jobs = task_queue.snapshot(task_id=task_id)
    if user.get("role") != "admin":
        user_dept = user.get("department", "")
        # 根据 task_id 过滤权限
        visible = []
        for j in all_jobs:
            t = task_manager.get_task(j["task_id"])
            if not t:
                continue
            if not t.get("department") or t.get("department") == user_dept:
                visible.append(j)
        all_jobs = visible
    return {"jobs": all_jobs[:limit]}


@app.get("/api/queue/jobs/{job_id}")
async def get_queue_job(job_id: str, user: dict = Depends(require_auth)):
    """查询单个 job 的状态"""
    job = task_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    # 权限检查
    if user.get("role") != "admin":
        t = task_manager.get_task(job.task_id)
        if t and t.get("department") and t["department"] != user.get("department"):
            raise HTTPException(403, "无权访问")
    return {"job": job.to_dict()}


@app.post("/api/queue/jobs/{job_id}/cancel")
async def cancel_queue_job(job_id: str, user: dict = Depends(require_auth)):
    """取消排队中的任务（运行中的无法取消）"""
    job = task_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    ok = await task_queue.cancel_job(job_id)
    if not ok:
        raise HTTPException(400, "只有等待中的任务才能取消（或已不存在）")
    return {"status": "success", "job_id": job_id}


# ==================== 动态建表API ====================
@app.get("/api/tables")
async def list_tables(user: dict = Depends(require_auth)):
    """列出所有业务数据表"""
    tables = storage_manager.mysql.list_business_tables() if storage_manager.is_mysql_available else []
    return {"tables": tables}

@app.post("/api/tables")
async def create_table(req: CreateTableRequest, user: dict = Depends(require_admin)):
    """创建业务数据表"""
    success = storage_manager.mysql.create_business_table(req.table_name, req.columns)
    if not success:
        raise HTTPException(500, "建表失败")
    return {"status": "success"}

@app.delete("/api/tables/{table_name}")
async def delete_table(table_name: str, user: dict = Depends(require_admin)):
    """删除业务数据表"""
    success = storage_manager.mysql.drop_business_table(table_name)
    if not success:
        raise HTTPException(500, "删表失败")
    return {"status": "success"}

@app.get("/api/tables/{table_name}/data")
async def query_table_data(table_name: str, limit: int = 100, offset: int = 0, user: dict = Depends(require_auth)):
    """查询业务数据表"""
    data = storage_manager.mysql.query_business_table(table_name, limit=limit, offset=offset)
    return {"data": data}

@app.post("/api/tables/{table_name}/data")
async def insert_table_data(table_name: str, data: dict, user: dict = Depends(require_auth)):
    """向业务表插入数据"""
    success = storage_manager.mysql.insert_business_row(table_name, data)
    if not success:
        raise HTTPException(500, "插入失败")
    return {"status": "success"}




# ==================== 用户配置API ====================
from src.storage import user_config_manager as ucm
from fastapi import UploadFile, File, Form

@app.get("/api/my-config")
async def get_my_config(user: dict = Depends(require_auth)):
    """获取当前用户的配置（带schema信息，给前端渲染表单）"""
    groups = ucm.get_user_config_with_schema(user["username"])
    return {"groups": groups, "username": user["username"]}

@app.post("/api/my-config")
async def save_my_config(data: dict, user: dict = Depends(require_auth)):
    """保存当前用户的配置（批量）"""
    items = data.get("items", {})
    ucm.batch_set_user_config(user["username"], items)
    return {"status": "success", "saved": len(items)}

@app.post("/api/my-config/upload")
async def upload_config_file(
    key: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(require_auth),
):
    """上传一个文件作为配置值（如Excel模板），返回保存后的路径"""
    content = await file.read()
    saved_path = ucm.save_uploaded_file(
        user["username"], key, content, file.filename
    )
    return {"status": "success", "path": saved_path, "filename": file.filename}

# ==================== WebSocket ====================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)



# ==================== 模板管理API ====================
@app.get("/api/templates")
async def list_templates(user=Depends(require_auth)):
    """列出当前用户的模板"""
    templates = template_mgr.list_templates(user["username"])
    return {"templates": templates}

@app.post("/api/templates/upload")
async def upload_template(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    template_type: str = Form("excel"),
    user=Depends(require_auth)
):
    """上传模板"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        result = template_mgr.upload_template(
            username=user["username"],
            name=name,
            file_path=tmp_path,
            description=description,
            template_type=template_type
        )
        return {"status": "success", "template": result}
    finally:
        os.unlink(tmp_path)

@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: str, user=Depends(require_auth)):
    """删除模板"""
    success = template_mgr.delete_template(user["username"], template_id)
    if success:
        return {"status": "success"}
    raise HTTPException(404, "模板不存在")

@app.get("/api/templates/{template_id}/download")
async def download_template(template_id: str, user=Depends(require_auth)):
    """下载模板文件"""
    path = template_mgr.get_template_path(user["username"], template_id)
    if not path:
        raise HTTPException(404, "模板不存在")
    return FileResponse(str(path), filename=path.name)


# ==================== 文件浏览器 ====================
@app.get("/api/files/browse")
async def browse_files(
    path: str = "",
    user=Depends(require_auth)
):
    """浏览本地文件系统，返回指定目录下的文件和文件夹列表"""
    if not path:
        path = os.path.expanduser("~")

    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise HTTPException(400, "路径无效")

    items = []
    try:
        for entry in os.listdir(path):
            full_path = os.path.join(path, entry)
            is_dir = os.path.isdir(full_path)
            items.append({
                "name": entry,
                "path": full_path,
                "is_dir": is_dir,
                "size": os.path.getsize(full_path) if not is_dir else 0,
                "modified": datetime.fromtimestamp(os.path.getmtime(full_path)).isoformat()
            })
    except PermissionError:
        raise HTTPException(403, "无权限访问该目录")

    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

    parent = os.path.dirname(path) if path != os.path.dirname(path) else path
    return {
        "current": path,
        "parent": parent,
        "items": items
    }

# ==================== 任务执行（旧函数已废弃，现走 task_queue 队列；保留占位引用防止意外调用）====================
# 原先：async def _run_task_background(...)
# 新逻辑直接在 run_task / smart_chat 里通过 task_queue.submit() 提交





# ==================== 启动 ====================
def start_server():
    import uvicorn
    uvicorn.run("src.web.api:app", host=config.web.host, port=config.web.port, reload=config.web.reload)


# ==================== HTML页面（从模板导入）====================
from src.web import html_templates

if __name__ == "__main__":
    start_server()


# ===== Cookie管理 =====
@app.get("/api/cookies/keys")
async def list_cookie_keys(user=Depends(require_auth)):
    """
    列出所有cookie_key及其状态
    来源：平台配置 + 自定义注册 + Redis中已有的
    只返回：key名、所属平台、状态、剩余天数
    不返回cookie内容
    """
    from sdk.cookie_manager import cookie_manager
    keys = cookie_manager.list_cookie_keys()
    return {"keys": keys}


@app.get("/api/cookies/platforms")
async def list_cookie_platforms(user=Depends(require_auth)):
    """列出所有可用平台（用于注册新cookie_key时选择）"""
    from sdk.cookie_manager import cookie_manager
    platforms = []
    for name, cfg in cookie_manager.PLATFORM_CONFIG.items():
        platforms.append({
            "name": name,
            "login_url": cfg.get("login_url", ""),
        })
    return {"platforms": platforms}


@app.post("/api/cookies/register")
async def register_cookie_key(req: dict, user=Depends(require_auth)):
    """
    注册一个新的cookie_key（多账号场景）
    body: {"key": "jd_shangzhi_店铺B", "platform": "jd_shangzhi"}
    """
    from sdk.cookie_manager import cookie_manager
    key = req.get("key", "").strip()
    platform = req.get("platform", "").strip()
    if not key or not platform:
        raise HTTPException(400, "key和platform不能为空")
    ok = cookie_manager.register_cookie_key(key, platform)
    if not ok:
        raise HTTPException(400, f"注册失败，平台 {platform} 不存在")
    return {"status": "success", "key": key, "platform": platform}


@app.delete("/api/cookies/keys/{key}")
async def delete_cookie_key(key: str, user=Depends(require_auth)):
    """删除一个cookie_key及其cookie（自定义注册的才允许删除，平台内置的不允许）"""
    from sdk.cookie_manager import cookie_manager
    # 尝试取消注册（只对自定义key有效）
    cookie_manager.unregister_cookie_key(key)
    # 删除cookie
    cookie_manager.delete(key)
    return {"status": "success"}


@app.post("/api/cookies/{key}/refresh")
async def refresh_cookie(key: str, user=Depends(require_auth)):
    """
    刷新指定cookie_key的Cookie
    只影响这一个key，不会动其他key的cookie

    流程：删除旧cookie → 打开浏览器到登录页 → 后台轮询检测登录 → 自动保存
    用户只需在浏览器中登录，无需操作后台终端
    登录结果通过WebSocket推送到前端
    """
    from sdk.browser_sdk import Browser
    from sdk.cookie_manager import cookie_manager

    # 检查cookie_key是否已配置平台
    platform = cookie_manager.resolve_platform(key)
    if not platform:
        raise HTTPException(400, f"未知的cookie_key: {key}，请先注册并关联平台")

    login_url = cookie_manager.get_login_url(key)
    if not login_url:
        raise HTTPException(400, f"平台 {platform} 未配置login_url")

    # 只删除这一个key的旧cookie（不影响其他key）
    cookie_manager.delete(key)

    async def do_refresh():
        try:
            async with Browser(cookie_key=key, headless=False) as b:
                await b.open(login_url)

                # WebSocket通知：浏览器已打开
                await manager.broadcast({
                    "type": "cookie_refresh",
                    "key": key,
                    "status": "browser_opened",
                    "message": f"浏览器已打开，请在浏览器中登录（{key}）",
                })

                # 每次轮询时通过WebSocket推送进度
                async def on_progress(info):
                    found = info.get('found', [])
                    threshold = info.get('threshold', 2)
                    await manager.broadcast({
                        "type": "cookie_refresh",
                        "key": key,
                        "status": info.get("status", "waiting"),
                        "message": f"检测中（{info.get('elapsed', 0)}s）: 核心cookie {len(found)}/{threshold}，缺少: {info.get('missing', [])}",
                    })

                # 登录成功时推送
                async def on_success():
                    await manager.broadcast({
                        "type": "cookie_refresh",
                        "key": key,
                        "status": "success",
                        "message": f"Cookie刷新成功（{key}）",
                    })

                # 超时时推送
                async def on_timeout():
                    await manager.broadcast({
                        "type": "cookie_refresh",
                        "key": key,
                        "status": "timeout",
                        "message": f"登录超时，请重试（{key}）",
                    })

                # 自动轮询检测登录（不阻塞事件循环，每3秒检查一次）
                await b.wait_login_auto(
                    timeout=300,
                    interval=3,
                    on_success=on_success,
                    on_timeout=on_timeout,
                    on_progress=on_progress,
                )

        except Exception as e:
            logger.error(f"刷新Cookie失败: {e}")
            await manager.broadcast({
                "type": "cookie_refresh",
                "key": key,
                "status": "error",
                "message": f"刷新失败: {e}",
            })

    asyncio.create_task(do_refresh())
    return {"message": f"正在打开浏览器，请在浏览器中登录（{key}）"}


# ==================== 智能问答API ====================
from pydantic import BaseModel as _BM

class ChatRequest(_BM):
    message: str


def _match_task_id(text: str, visible_tasks: list) -> Optional[str]:
    """
    模糊匹配任务：从用户输入或LLM回复中找到最匹配的任务
    
    匹配顺序：精确filename → 精确name → 模糊匹配name
    """
    text = text.strip()
    
    # 1. 精确匹配 filename
    for t in visible_tasks:
        if t.get("filename") == text:
            return text
    
    # 2. 精确匹配 name
    for t in visible_tasks:
        if t.get("name") == text:
            return t.get("filename", "")
    
    # 3. 模糊匹配（包含关系）
    for t in visible_tasks:
        name = t.get("name", "")
        if text in name or name in text:
            return t.get("filename", "")
    
    # 4. 相似度匹配
    from difflib import SequenceMatcher
    best_match = None
    best_score = 0.5  # 最低阈值
    for t in visible_tasks:
        name = t.get("name", "")
        score = SequenceMatcher(None, text, name).ratio()
        if score > best_score:
            best_score = score
            best_match = t.get("filename", "")
    
    return best_match


@app.post("/api/chat")
async def smart_chat(req: ChatRequest, user: dict = Depends(require_auth)):
    """智能问答入口 - 用户和LLM对话，可以查任务、跑任务、问问题"""
    from src.core.llm_client import LocalLLMClient
    import json as _json
    import re as _re

    llm = LocalLLMClient()

    # 获取当前用户可见的任务列表
    user_dept = user.get("department", "")
    all_tasks = task_manager.list_tasks()
    visible_tasks = []
    for t in all_tasks:
        if user.get("role") == "admin" or t.get("department") == user_dept:
            visible_tasks.append({
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "enabled": t.get("enabled", True),
                "mode": t.get("mode", ""),
                "filename": t.get("filename", "")
            })

    # 任务列表文本（同时显示名称和文件名，让LLM能精确返回）
    task_list_text = "\n".join(
        f"- 名称:{t['name']} | 文件名:{t['filename']} | 模式:{t['mode']} | {t['description']}"
        for t in visible_tasks if t["enabled"]
    ) if visible_tasks else "（暂无任务）"

    # 获取最近执行历史
    recent_history = []
    try:
        for t in visible_tasks:
            fname = t.get("filename", "")
            if fname:
                hist = task_manager.get_history(fname)
                if hist:
                    for h in hist[:2]:
                        recent_history.append({"task": t["name"], "status": h.get("status", ""),
                                               "time": h.get("executed_at", ""), "error": h.get("error", "")})
    except Exception:
        pass

    history_text = "\n".join(
        f"- {h['task']}: {h['status']} ({h['time']})"
        for h in recent_history[:5]
    ) if recent_history else "（暂无历史）"

    system_prompt = f"""你是LY智能自动化平台的助手。当前用户是 {user.get('username', '用户')}，部门：{user_dept}。

## 可执行的任务列表
{task_list_text}

## 最近执行历史
{history_text}

## 你的职责
1. 用户想执行任务时，找到对应任务，返回JSON指令。返回格式：
```json
{{"action": "run_task", "task_id": "任务的文件名"}}
```
注意：task_id 必须是上面列表中的"文件名"字段值，不要用任务名称。

2. 用户问任务列表、历史情况时，直接回答。

3. 用户问平台使用问题时，简要回答。

保持回复简洁，用中文。"""

    try:
        reply = llm.chat(req.message, system_prompt=system_prompt, use_history=True)

        # 提取JSON指令
        task_to_run = None
        json_match = _re.search(r'```json\s*(\{.*?\})\s*```', reply, _re.DOTALL)
        if json_match:
            try:
                cmd = _json.loads(json_match.group(1))
                if cmd.get("action") == "run_task" and cmd.get("task_id"):
                    task_to_run = cmd["task_id"]
            except Exception:
                pass
        if not task_to_run:
            json_match2 = _re.search(r'"task_id"\s*:\s*"([^"]+)"', reply)
            if json_match2:
                task_to_run = json_match2.group(1)

        # 模糊匹配：LLM返回的可能不是精确的filename
        if task_to_run:
            task_to_run = _match_task_id(task_to_run, visible_tasks)

        # 执行任务
        if task_to_run:
            task = task_manager.get_task(task_to_run)
            if task and (user.get("role") == "admin" or task.get("department") == user_dept):
                task_name = task.get("name", task_to_run)

                async def run_fn():
                    await manager.broadcast({"type": "status", "message": f"任务 [{task_name}] 开始执行...", "task_id": task_to_run})
                    executor = TaskExecutor()
                    executor.set_user(user)
                    result = await executor.execute_task(task_to_run, user_params=None)
                    if result.get("status") == "success":
                        await manager.broadcast({"type": "success", "message": f"任务 [{task_name}] 成功，耗时 {result.get('elapsed_time')}秒", "task_id": task_to_run})
                    else:
                        await manager.broadcast({"type": "error", "message": f"任务 [{task_name}] 失败: {result.get('error')}", "task_id": task_to_run})
                    return result

                def on_status_change(job):
                    asyncio.create_task(manager.broadcast({"type": "queue", "job": job.to_dict(), "queue_summary": task_queue.summary()}))

                await task_queue.submit(task_id=task_to_run, task_name=task_name, user_info=user,
                                        user_params=None, run_fn=run_fn, on_status_change=on_status_change)
                return {"reply": reply, "task_started": True, "task_id": task_to_run}
            else:
                return {"reply": reply + "\n\n⚠️ 任务不存在或你没有权限执行此任务。", "task_started": False}

        return {"reply": reply, "task_started": False}

    except Exception as e:
        return {"reply": f"抱歉，处理出错了：{e}", "task_started": False}


@app.get("/api/chat/suggestions")
async def chat_suggestions(user: dict = Depends(require_auth)):
    """获取建议问题（根据当前任务自动生成）"""
    user_dept = user.get("department", "")
    all_tasks = task_manager.list_tasks()
    visible = [t for t in all_tasks if user.get("role") == "admin" or t.get("department") == user_dept]

    suggestions = []
    if visible:
        suggestions.append("列出我的所有任务")
        suggestions.append(f"执行{visible[0].get('name', '')}")
        suggestions.append("最近的任务执行情况怎么样")
    else:
        suggestions.append("怎么创建一个新任务")
        suggestions.append("这个平台能做什么")

    suggestions.append("怎么配置任务参数")
    return {"suggestions": suggestions}



# ==================== 系统依赖检测（管理员）====================
@app.get("/api/system/deps")
async def check_deps(user: dict = Depends(require_admin)):
    """
    检测桌面自动化所需依赖是否已安装
    返回每个依赖的状态和安装命令
    """
    import os
    import sys
    # 修复 uiautomation 依赖 comtypes 时的缓存目录权限问题
    # 将 comtypes_cache 重定向到项目本地，避免 AppData 权限不足
    try:
        _api_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(os.path.dirname(_api_dir))
        project_comtypes_cache = os.path.join(_project_root, "data", "comtypes_cache")
        os.makedirs(project_comtypes_cache, exist_ok=True)
        # comtypes 不读取环境变量，直接通过修改 comtypes.gen.__path__ 和 gen_dir
        import importlib
        import types
        try:
            import comtypes
        except ImportError:
            comtypes = None
        if comtypes is not None:
            try:
                import comtypes.client
            except ImportError:
                pass
            # 确保 comtypes.gen 包存在
            try:
                import comtypes.gen
            except ImportError:
                comtypes.gen = types.ModuleType("comtypes.gen")
                sys.modules["comtypes.gen"] = comtypes.gen
                comtypes.gen.__path__ = []
            # 设置自定义缓存目录
            if not hasattr(comtypes.gen, "__path__"):
                comtypes.gen.__path__ = []
            if project_comtypes_cache not in comtypes.gen.__path__:
                comtypes.gen.__path__.insert(0, project_comtypes_cache)
            try:
                import comtypes.client
                comtypes.client.gen_dir = project_comtypes_cache
            except Exception:
                pass
    except Exception:
        pass

    deps = [
        {"name": "uiautomation", "import_name": "uiautomation",
         "desc": "Windows桌面控件自动化", "install_cmd": "pip install uiautomation"},
        {"name": "opencv-python", "import_name": "cv2",
         "desc": "图像识别（控件截图匹配）", "install_cmd": "pip install opencv-python"},
        {"name": "pillow", "import_name": "PIL",
         "desc": "截图处理", "install_cmd": "pip install pillow"},
    ]
    result = []
    for dep in deps:
        installed = False
        import_error = None
        try:
            __import__(dep["import_name"])
            installed = True
        except Exception as e:
            import_error = str(e)[:100]
            installed = False
        dep_entry = {**dep, "installed": installed}
        if import_error:
            dep_entry["error"] = import_error
        result.append(dep_entry)
    return {"deps": result, "all_installed": all(d["installed"] for d in result)}


@app.post("/api/system/deps/install")
async def install_dep(req: dict, user: dict = Depends(require_admin)):
    """
    通过Web界面安装依赖（管理员权限）
    后台执行 pip install，返回安装结果
    """
    import subprocess
    dep_name = req.get("name", "")
    if not dep_name:
        raise HTTPException(400, "未指定依赖名")

    # 安全检查：只允许安装白名单内的包
    allowed = {"uiautomation", "opencv-python", "pillow"}
    if dep_name not in allowed:
        raise HTTPException(400, f"不允许安装非白名单包: {dep_name}")

    logger.info(f"管理员 {user.get('username')} 正在安装依赖: {dep_name}")
    try:
        # 异步执行pip install，避免阻塞Web服务
        result = await asyncio.to_thread(
            subprocess.run,
            ["pip", "install", dep_name],
            capture_output=True,
            text=True,
            timeout=300,  # 5分钟超时
        )
        success = result.returncode == 0
        output = result.stdout[-500:] if result.stdout else ""
        error = result.stderr[-500:] if result.stderr else ""

        return {
            "status": "success" if success else "failed",
            "output": output,
            "error": error,
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "安装超时（5分钟）"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ==================== LLM模型管理API ====================
@app.get("/api/llm/providers")
async def list_llm_providers(user: dict = Depends(require_auth)):
    """列出所有可用的LLM提供商和当前选中的"""
    from src.core.config import get_config as _get_cfg
    cfg = _get_cfg()
    providers = [
        {"id": "zhipuai", "name": "智谱AI (GLM-4-Flash)", "configured": bool(cfg.llm.zhipuai_api_key)},
        {"id": "deepseek", "name": "DeepSeek-V4 (ModelScope)", "configured": bool(cfg.llm.deepseek_api_key)},
        {"id": "ollama", "name": "Ollama (本地)", "configured": bool(cfg.llm.base_url)},
    ]
    return {
        "providers": providers,
        "current": cfg.llm.provider,
        "current_model": cfg._get_model_name(),
    }


@app.post("/api/llm/switch")
async def switch_llm_provider(req: dict, user: dict = Depends(require_admin)):
    """切换LLM提供商（仅管理员）"""
    provider = req.get("provider", "")
    if provider not in ("zhipuai", "deepseek", "ollama"):
        raise HTTPException(400, f"不支持的提供商: {provider}")

    # 更新配置并保存
    config.update_config("llm.provider", provider)
    config.save_config()

    # 重置全局配置单例，下次使用时重新加载
    import src.core.config as cfg_module
    cfg_module._config_instance = None

    logger.info(f"管理员 {user.get('username')} 切换LLM提供商为: {provider}")
    return {"status": "success", "provider": provider}
