# -*- coding: utf-8 -*-
"""
HTML模板管理 - 优先从 src/web/static/ 文件系统读取（方便维护和热更），
读取失败时回退到内联的 LOGIN_PAGE_FALLBACK / HTML_PAGE_FALLBACK（保证任何环境都能启动）。

拆分后的文件结构（src/web/static/）：
  login.html                 登录页（引用 assets/login.js + assets/chat.css）
  index.html                 主页面（引用 assets/*.css + assets/*.js）
  assets/app.css             全局样式
  assets/chat.css            聊天浮窗 + 登录页 body 样式
  assets/login.js            登录页逻辑
  assets/app.js              核心逻辑（认证、WebSocket、日志、Tab、部门）
  assets/tasks.js            任务管理：列表、执行、新增/编辑、用户管理、依赖检测
  assets/config.js           我的配置、模板中心
  assets/chat.js             智能助手浮窗
"""
from pathlib import Path


_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _read_text(rel_path: str) -> str:
    """读取 static 目录下的文件；读不到返回空串"""
    try:
        return (_STATIC_DIR / rel_path).read_text(encoding="utf-8")
    except (OSError, IOError):
        return ""


def get_login_page() -> str:
    html = _read_text("login.html")
    if html:
        return html
    return LOGIN_PAGE_FALLBACK


def get_index_page() -> str:
    html = _read_text("index.html")
    if html:
        return html
    return HTML_PAGE_FALLBACK


# 对外保持兼容的变量名（api.py 里 from xxx import LOGIN_PAGE, HTML_PAGE 还能用）
LOGIN_PAGE = get_login_page()
HTML_PAGE = get_index_page()


# =====================================================================
# FALLBACK: 若 static 目录下的文件丢失，使用下面的最小可用版本。
# 仅作为兜底，避免启动即挂。维护时请优先改 static/ 下的源文件。
# =====================================================================

LOGIN_PAGE_FALLBACK = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>智能体平台 - 登录</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif; background:linear-gradient(135deg,#008b8b,#006666); min-height:100vh; display:flex; align-items:center; justify-content:center; }
.login-box { background:#fff; border-radius:16px; padding:40px; width:400px; box-shadow:0 20px 60px rgba(0,0,0,0.3); }
.login-box h1 { color:#008b8b; text-align:center; margin-bottom:5px; font-size:22px; }
.login-box .subtitle { color:#888; text-align:center; margin-bottom:30px; font-size:13px; }
.form-group { margin-bottom:20px; }
.form-group label { display:block; margin-bottom:8px; color:#555; font-weight:500; font-size:14px; }
.form-group input { width:100%; padding:12px 16px; border:2px solid #e0e0e0; border-radius:8px; font-size:14px; transition:border-color 0.3s; }
.form-group input:focus { outline:none; border-color:#008b8b; }
.btn-login { width:100%; padding:12px; background:linear-gradient(135deg,#008b8b,#006666); color:#fff; border:none; border-radius:8px; font-size:15px; cursor:pointer; transition:transform 0.2s; }
.btn-login:hover { transform:translateY(-2px); }
.error-msg { color:#e74c3c; font-size:13px; margin-top:10px; text-align:center; display:none; }
.error-msg.show { display:block; }
</style>
</head>
<body>
<div class="login-box">
    <h1>LY智能体平台</h1>
    <p class="subtitle">LLM驱动的智能自动化</p>
    <div class="form-group">
        <label>用户名</label>
        <input type="text" id="username" placeholder="请输入用户名" autocomplete="off">
    </div>
    <div class="form-group">
        <label>密码</label>
        <input type="password" id="password" placeholder="请输入密码" autocomplete="off">
    </div>
    <button class="btn-login" onclick="doLogin()">登 录</button>
    <div class="error-msg" id="error-msg"></div>
</div>
<script>
async function doLogin() {
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value.trim();
    if (!username || !password) { showError('请输入用户名和密码'); return; }
    try {
        const res = await fetch('/api/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body: JSON.stringify({username, password})});
        const data = await res.json();
        if (data.status === 'success') { localStorage.setItem('token', data.token); localStorage.setItem('user', JSON.stringify(data.user)); window.location.href = '/'; }
        else { showError(data.detail || '登录失败'); }
    } catch(e) { showError('网络错误'); }
}
function showError(msg) { const el = document.getElementById('error-msg'); el.textContent = msg; el.classList.add('show'); }
document.getElementById('password').addEventListener('keyup', e => { if (e.key === 'Enter') doLogin(); });
</script>
</body>
</html>"""


HTML_PAGE_FALLBACK = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><title>智能体平台</title>
<style>body{font-family:sans-serif;background:#f0f2f5;padding:40px;color:#333}h1{color:#008b8b}a{color:#008b8b}</style>
</head><body>
<h1>智能体平台</h1>
<p>⚠️ 未能从 <code>src/web/static/index.html</code> 加载前端页面（使用了兜底页）。</p>
<p>请确认 <code>src/web/static/</code> 目录下的文件完整，或在开发模式下启用 FastAPI reload=True 热加载。</p>
<p><a href="/login">返回登录</a>　<a href="#" onclick="localStorage.clear();location.href='/login'">清除登录态</a></p>
</body></html>"""
