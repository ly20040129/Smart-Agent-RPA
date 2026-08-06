# -*- coding: utf-8 -*-
"""HTML模板 - 登录页和主页面"""

LOGIN_PAGE = """<!DOCTYPE html>
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
    <h1>康云集团智能体平台</h1>
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
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({username, password})
        });
        const data = await res.json();
        if (data.status === 'success') {
            localStorage.setItem('token', data.token);
            localStorage.setItem('user', JSON.stringify(data.user));
            window.location.href = '/';
        } else {
            showError(data.detail || '登录失败');
        }
    } catch(e) { showError('网络错误'); }
}
function showError(msg) {
    const el = document.getElementById('error-msg');
    el.textContent = msg;
    el.classList.add('show');
}
document.getElementById('password').addEventListener('keyup', e => { if (e.key === 'Enter') doLogin(); });
</script>
</body>
</html>"""


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>智能体平台</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif; background:#f0f2f5; color:#333; }
.header { background:linear-gradient(135deg,#008b8b,#006666); color:#fff; padding:15px 40px; display:flex; justify-content:space-between; align-items:center; }
.header-left h1 { font-size:20px; font-weight:600; }
.header-left p { opacity:0.7; margin-top:3px; font-size:12px; }
.header-right { display:flex; align-items:center; gap:15px; }
.user-info { display:flex; align-items:center; gap:8px; font-size:13px; }
.user-info .dept-badge { background:rgba(255,255,255,0.2); padding:3px 10px; border-radius:12px; font-size:11px; }
.btn-logout { background:rgba(255,255,255,0.2); color:#fff; border:none; padding:6px 14px; border-radius:6px; cursor:pointer; font-size:12px; }
.btn-logout:hover { background:rgba(255,255,255,0.3); }
.container { max-width:1200px; margin:20px auto; padding:0 20px; }
.toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
.toolbar h2 { color:#008b8b; font-size:18px; }
.toolbar-left { display:flex; gap:10px; align-items:center; }
.toolbar-left select { padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:13px; }
.btn { background:#008b8b; color:#fff; border:none; padding:10px 20px; border-radius:6px; cursor:pointer; font-size:14px; transition:background 0.2s; }
.btn:hover { background:#006666; }
.btn-sm { padding:6px 12px; font-size:12px; }
.btn-danger { background:#e74c3c; }
.btn-danger:hover { background:#c0392b; }
.btn-success { background:#27ae60; }
.btn-success:hover { background:#219a52; }
.btn-warning { background:#f39c12; }
.btn-warning:hover { background:#d68910; }
.btn-admin { background:#8e44ad; }
.btn-admin:hover { background:#6c3483; }
.task-card { background:#fff; border-radius:10px; margin-bottom:15px; box-shadow:0 2px 8px rgba(0,0,0,0.06); overflow:hidden; transition:box-shadow 0.2s; }
.task-card:hover { box-shadow:0 4px 16px rgba(0,0,0,0.1); }
.task-header { display:flex; justify-content:space-between; align-items:center; padding:15px 20px; cursor:pointer; user-select:none; }
.task-header:hover { background:#f8f9fa; }
.task-header-left { display:flex; align-items:center; gap:12px; flex:1; }
.task-name { font-size:16px; font-weight:600; color:#333; }
.task-desc-row { display:flex; align-items:center; gap:10px; margin-top:3px; }
.task-desc-row .desc { color:#888; font-size:12px; }
.task-desc-row .schedule { color:#008b8b; font-size:12px; }
.task-desc-row .dept-tag { background:#e0f7f7; color:#008b8b; padding:2px 8px; border-radius:4px; font-size:11px; }
.task-header-right { display:flex; gap:6px; align-items:center; }
.collapse-icon { transition:transform 0.3s; color:#888; font-size:14px; }
.collapse-icon.open { transform:rotate(90deg); }
.task-body { display:none; padding:0 20px 20px; border-top:1px solid #f0f0f0; }
.task-body.show { display:block; }
.task-steps { background:#f8f9fa; border-radius:8px; padding:12px 16px; margin:10px 0; }
.task-step { padding:6px 0; font-size:13px; color:#555; border-bottom:1px dashed #e0e0e0; }
.task-step:last-child { border-bottom:none; }
.task-step .idx { color:#008b8b; font-weight:600; margin-right:6px; }
.task-step .type { display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; margin-right:6px; }
.task-step .type.browser { background:#e3f2fd; color:#1565c0; }
.task-step .type.data { background:#fff3e0; color:#e65100; }
.task-step .type.notify { background:#f3e5f5; color:#7b1fa2; }
.task-step .action { color:#008b8b; font-weight:600; margin-right:6px; }
.task-step .desc { color:#666; }
.badge { padding:3px 10px; border-radius:12px; font-size:11px; font-weight:500; }
.badge-on { background:#d4edda; color:#155724; }
.badge-off { background:#f8d7da; color:#721c24; }
.modal-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:999; }
.modal { display:none; position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); background:#fff; border-radius:12px; padding:25px; width:650px; max-height:85vh; overflow-y:auto; z-index:1000; box-shadow:0 20px 60px rgba(0,0,0,0.3); }
.modal h2 { margin-bottom:20px; color:#008b8b; font-size:18px; }
.form-group { margin-bottom:15px; }
.form-group label { display:block; margin-bottom:6px; font-weight:500; color:#555; font-size:13px; }
.form-group input, .form-group textarea, .form-group select { width:100%; padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:14px; }
.form-group input:focus, .form-group textarea:focus { outline:none; border-color:#008b8b; }
.step-editor { background:#f8f9fa; padding:12px; border-radius:8px; margin-bottom:8px; }
.step-editor select, .step-editor input { padding:6px 10px; border:1px solid #ddd; border-radius:4px; margin-right:5px; }
#log-panel { position:fixed; bottom:0; right:20px; width:420px; max-height:220px; background:#1e1e1e; color:#fff; border-radius:10px 10px 0 0; box-shadow:0 -4px 20px rgba(0,0,0,0.3); z-index:998; transition:all 0.3s; }
#log-panel.collapsed { height:36px; overflow:hidden; }
#log-panel .log-header { display:flex; justify-content:space-between; align-items:center; padding:8px 12px; cursor:pointer; border-bottom:1px solid #333; }
#log-panel.collapsed .log-header { border-bottom:none; }
#log-panel .log-header span { color:#999; font-size:12px; }
#log-panel .log-header button { background:none; border:none; color:#999; cursor:pointer; font-size:14px; padding:0 4px; }
#log-panel .log-body { padding:8px 12px; overflow-y:auto; max-height:170px; font-family:Consolas,monospace; font-size:12px; }
#log-panel.collapsed .log-body { display:none; }
.log-line { margin:2px 0; padding:2px 0; }
.log-success { color:#27ae60; }
.log-error { color:#e74c3c; }
.log-info { color:#3498db; }
.log-warn { color:#f39c12; }
.tab-switch { display:flex; gap:0; }
.tab-btn { padding:8px 20px; border:1px solid #008b8b; background:#fff; color:#008b8b; cursor:pointer; font-size:13px; }
.tab-btn.active { background:#008b8b; color:#fff; }
.tab-btn:first-child { border-radius:6px 0 0 6px; }
.tab-btn:last-child { border-radius:0 6px 6px 0; }
.delivery-section { border-top:1px solid #eee; padding-top:15px; margin-top:15px; }
.delivery-section h3 { font-size:14px; color:#008b8b; margin-bottom:10px; }
.template-list { max-height:300px; overflow-y:auto; border:1px solid #eee; border-radius:6px; }
.template-item { display:flex; justify-content:space-between; align-items:center; padding:10px 12px; border-bottom:1px solid #f5f5f5; }
.template-item:last-child { border-bottom:none; }
.template-info { flex:1; }
.template-name { font-weight:500; font-size:13px; }
.template-meta { color:#999; font-size:11px; margin-top:2px; }
.file-browse-group { display:flex; gap:8px; }
.file-browse-group input { flex:1; }
.mode-tag { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; margin-left:6px; }
.mode-browser { background:#e3f2fd; color:#1565c0; }
.mode-api { background:#fff3e0; color:#e65100; }
</style>
</head>
<body>

<div class="header">
    <div class="header-left">
        <h1>康云集团智能体平台</h1>
        <p>LLM驱动的智能自动化 · 不写代码，用自然语言编排任务</p>
    </div>
    <div class="header-right">
        <div class="user-info">
            <span>👤 <span id="current-user">-</span></span>
            <span class="dept-badge" id="current-dept">-</span>
        </div>
        <button class="btn-logout" onclick="doLogout()">退出</button>
    </div>
</div>

<div class="container">
    <div class="toolbar">
        <div class="toolbar-left">
            <h2>📋 任务列表</h2>
            <select id="dept-filter" onchange="loadTasks()">
                <option value="">全部部门</option>
            </select>
        </div>
        <div class="tab-switch">
            <button class="tab-btn active" onclick="switchTab('browser')">🌐 浏览器自动化</button>
            <button class="tab-btn" onclick="switchTab('api')">🔌 API自动化</button>
        </div>
        <div style="display:flex;gap:10px;">
            <button class="btn" style="background:#16a085;" onclick="openConfigModal()">⚙️ 我的配置</button>
            <button class="btn btn-admin" onclick="openUserModal()">👥 用户管理</button>
            <button class="btn btn-admin" onclick="openDepsModal()">🔧 系统依赖</button>
            <button class="btn" onclick="openCreateModal()">+ 新增任务</button>
        </div>
    </div>
    <div id="task-list"></div>
</div>

<div class="modal-overlay" id="modal-overlay" onclick="closeModal()"></div>
<div class="modal" id="modal">
    <h2 id="modal-title">新增任务</h2>
    <div class="form-group">
        <label>任务名称</label>
        <input type="text" id="task-name" placeholder="如：公众号资金账单">
    </div>
    <div class="form-group">
        <label>所属部门</label>
        <select id="task-dept"></select>
    </div>
    <div class="form-group">
        <label>任务模式</label>
        <select id="task-mode">
            <option value="browser">🌐 浏览器自动化</option>
            <option value="api">🔌 API自动化</option>
        </select>
    </div>
    <div class="form-group">
        <label>任务描述</label>
        <textarea id="task-desc" rows="2" placeholder="简要描述任务目标"></textarea>
    </div>
    <div class="form-group">
        <label>定时执行（Cron格式，留空为手动）</label>
        <input type="text" id="task-schedule" placeholder="如：0 9 * * 1（每周一9点）">
    </div>
    <div class="form-group">
        <label>执行步骤</label>
        <div id="steps-container"></div>
        <button class="btn btn-sm" onclick="addStep()">+ 添加步骤</button>
    </div>
    <div class="delivery-section" id="task-delivery-section">
        <h3>📦 交付配置（可选）</h3>
        <div class="form-group">
            <label>输出文件名模板</label>
            <input type="text" id="task-filename-pattern" placeholder="如：{name}_{date}_{time}.xlsx">
        </div>
        <div class="form-group">
            <label>完成后通知（DingTalk Webhook）</label>
            <input type="text" id="task-dingtalk-webhook" placeholder="留空则使用全局配置">
        </div>
    </div>
    <div style="display:flex;gap:10px;margin-top:20px;">
        <button class="btn btn-success" onclick="saveTask()">保存</button>
        <button class="btn btn-warning" onclick="closeModal()">取消</button>
    </div>
</div>

<div class="modal-overlay" id="user-modal-overlay" onclick="closeUserModal()"></div>
<div class="modal" id="user-modal" style="width:700px;">
    <h2>👥 用户管理</h2>
    <div id="user-list" style="max-height:300px;overflow-y:auto;margin-bottom:15px;"></div>
    <div style="border-top:1px solid #eee;padding-top:15px;">
        <h3 style="color:#008b8b;margin-bottom:10px;font-size:14px;">新增用户</h3>
        <div style="display:flex;gap:10px;margin-bottom:10px;">
            <input type="text" id="new-username" placeholder="用户名" style="flex:1;padding:8px;border:1px solid #ddd;border-radius:6px;">
            <input type="password" id="new-password" placeholder="密码" style="flex:1;padding:8px;border:1px solid #ddd;border-radius:6px;">
            <select id="new-dept" style="padding:8px;border:1px solid #ddd;border-radius:6px;"></select>
            <select id="new-role" style="padding:8px;border:1px solid #ddd;border-radius:6px;">
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
            </select>
            <button class="btn btn-sm" onclick="createUser()">添加</button>
        </div>
    </div>
    <button class="btn btn-warning" onclick="closeUserModal()">关闭</button>
</div>

<div class="modal-overlay" id="deps-modal-overlay" onclick="closeDepsModal()"></div>
<div class="modal" id="deps-modal" style="width:600px;">
    <h2>🔧 系统依赖检测</h2>
    <p style="color:#888;font-size:13px;margin-bottom:15px;">
        桌面自动化（金蝶K/3、网点管家等）需要以下依赖。未安装时点击"安装"按钮即可自动安装。
    </p>
    <div id="deps-list" style="max-height:400px;overflow-y:auto;">
        <div style="text-align:center;color:#888;padding:20px;">加载中...</div>
    </div>
    <div style="display:flex;gap:10px;margin-top:20px;">
        <button class="btn btn-sm" onclick="checkDeps()">🔄 重新检测</button>
        <button class="btn btn-warning" onclick="closeDepsModal()">关闭</button>
    </div>
</div>

<div class="modal-overlay" id="config-modal-overlay" onclick="closeConfigModal()"></div>
<div class="modal" id="config-modal" style="width:700px;">
    <h2>⚙️ 我的配置</h2>
    <p style="color:#888;font-size:12px;margin-bottom:15px;">配置你本地的文件路径和目录。上传的文件仅你自己可见，其他同事互不影响。</p>
    <div id="config-form" style="max-height:350px;overflow-y:auto;"></div>
    <div class="delivery-section">
        <h3>📦 交付配置</h3>
        <div class="form-group">
            <label>下载根目录</label>
            <div class="file-browse-group">
                <input type="text" id="config-download-root" placeholder="如：D:\Downloads\SmartAgent">
                <button class="btn btn-sm" onclick="browseDownloadRoot()">浏览</button>
            </div>
        </div>
        <div class="form-group">
            <label>默认文件名模板</label>
            <input type="text" id="config-filename-pattern" placeholder="如：{name}_{date}_{time}.xlsx" value="{name}_{date}_{time}.xlsx">
            <p style="color:#999;font-size:11px;margin-top:4px;">支持变量：{name} {date} {time}</p>
        </div>
        <div class="form-group">
            <label>DingTalk Webhook URL</label>
            <input type="text" id="config-dingtalk-webhook" placeholder="https://oapi.dingtalk.com/robot/send?access_token=...">
        </div>
        <h3 style="color:#008b8b;font-size:14px;margin:15px 0 10px;">📧 邮件SMTP配置</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
            <div class="form-group">
                <label>SMTP服务器</label>
                <input type="text" id="config-email-smtp" placeholder="如：smtp.qq.com">
            </div>
            <div class="form-group">
                <label>端口</label>
                <input type="text" id="config-email-port" placeholder="465">
            </div>
            <div class="form-group">
                <label>发件邮箱</label>
                <input type="text" id="config-email-sender" placeholder="sender@example.com">
            </div>
            <div class="form-group">
                <label>密码/授权码</label>
                <input type="password" id="config-email-password" placeholder="授权码">
            </div>
        </div>
        <div class="form-group">
            <label>收件人</label>
            <input type="text" id="config-email-receivers" placeholder="多个邮箱用逗号分隔">
        </div>
        <div style="margin-top:10px;">
            <button class="btn btn-sm" style="background:#8e44ad;" onclick="openTemplateModal()">📁 模板中心</button>
        </div>
    </div>
    <div style="display:flex;gap:10px;margin-top:20px;">
        <button class="btn btn-success" onclick="saveMyConfig()">💾 保存配置</button>
        <button class="btn btn-warning" onclick="closeConfigModal()">关闭</button>
    </div>
</div>

<div class="modal-overlay" id="template-modal-overlay" onclick="closeTemplateModal()"></div>
<div class="modal" id="template-modal" style="width:700px;">
    <h2>📁 模板中心</h2>
    <div style="margin-bottom:15px;">
        <h3 style="font-size:14px;color:#008b8b;margin-bottom:10px;">上传新模板</h3>
        <div class="form-group">
            <label>模板名称</label>
            <input type="text" id="tpl-name" placeholder="如：销售日报模板">
        </div>
        <div class="form-group">
            <label>模板描述</label>
            <input type="text" id="tpl-desc" placeholder="简要描述模板用途">
        </div>
        <div style="display:flex;gap:10px;margin-bottom:10px;">
            <div class="form-group" style="flex:1;">
                <label>选择文件</label>
                <input type="file" id="tpl-file" accept=".xlsx,.xls,.docx,.pptx,.pdf,.json">
            </div>
            <div class="form-group" style="width:150px;">
                <label>模板类型</label>
                <select id="tpl-type">
                    <option value="excel">Excel</option>
                    <option value="word">Word</option>
                    <option value="ppt">PPT</option>
                    <option value="pdf">PDF</option>
                    <option value="json">JSON</option>
                    <option value="other">其他</option>
                </select>
            </div>
        </div>
        <button class="btn btn-sm btn-success" onclick="uploadTemplate()">📤 上传模板</button>
    </div>
    <div style="border-top:1px solid #eee;padding-top:15px;margin-top:15px;">
        <h3 style="font-size:14px;color:#008b8b;margin-bottom:10px;">已有模板</h3>
        <div id="template-list" class="template-list">
            <p style="color:#999;text-align:center;padding:20px;">加载中...</p>
        </div>
    </div>
    <div style="display:flex;gap:10px;margin-top:20px;">
        <button class="btn btn-warning" onclick="closeTemplateModal()">关闭</button>
    </div>
</div>

<div id="log-panel" class="collapsed">
    <div class="log-header" onclick="toggleLogPanel()">
        <span>📊 实时日志</span>
        <button onclick="event.stopPropagation();document.getElementById('log-body').innerHTML='';">清空</button>
    </div>
    <div class="log-body" id="log-body"></div>
</div>

<script>
var API = '';
var token = localStorage.getItem('token');
var currentUser = JSON.parse(localStorage.getItem('user') || 'null');
var editTaskId = null;
var currentTab = 'browser';

function checkAuth() {
    if (!token || !currentUser) { window.location.href = '/login'; return false; }
    return true;
}
function doLogout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/login';
}
function authHeaders() {
    return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'};
}

// 日志面板折叠
function toggleLogPanel() {
    var panel = document.getElementById('log-panel');
    panel.classList.toggle('collapsed');
}

// 初始化
async function init() {
    if (!checkAuth()) return;
    // 后端校验 token 有效性，过期/伪造则跳登录
    try {
        var meRes = await fetch(API + '/api/auth/me', {headers: authHeaders()});
        if (!meRes.ok) throw new Error('token invalid');
        var meData = await meRes.json();
        // 用后端返回的 user 覆盖 localStorage（防止本地数据过旧）
        currentUser = meData;
        localStorage.setItem('user', JSON.stringify(meData));
    } catch(e) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = '/login';
        return;
    }
    document.getElementById('current-user').textContent = currentUser.username;
    var deptName = await getDeptName(currentUser.department);
    document.getElementById('current-dept').textContent = deptName;
    await loadDepts();
    await loadTasks();
    connectWS();
    addLog('智能体平台已启动', 'success');
}

async function getDeptName(deptId) {
    if (!deptId) return '未分配';
    try {
        var res = await fetch(API + '/api/departments', {headers: authHeaders()});
        var data = await res.json();
        var depts = data.departments || [];
        for (var i = 0; i < depts.length; i++) {
            if (depts[i].id === deptId) return depts[i].name;
        }
        return deptId;
    } catch(e) { return deptId; }
}

async function loadDepts() {
    var res = await fetch(API + '/api/departments', {headers: authHeaders()});
    var data = await res.json();
    var depts = data.departments || [];
    var filter = document.getElementById('dept-filter');
    filter.innerHTML = '<option value="">全部部门</option>';
    for (var i = 0; i < depts.length; i++) {
        filter.innerHTML += '<option value="' + depts[i].id + '">' + depts[i].name + '</option>';
    }
    if (currentUser.department) filter.value = currentUser.department;
    if (currentUser.role !== 'admin') filter.disabled = true;
    var deptSel = document.getElementById('task-dept');
    deptSel.innerHTML = '<option value="">未分配</option>';
    for (var i = 0; i < depts.length; i++) {
        deptSel.innerHTML += '<option value="' + depts[i].id + '">' + depts[i].name + '</option>';
    }
    if (currentUser.department) deptSel.value = currentUser.department;
    if (currentUser.role !== 'admin') deptSel.disabled = true;
    var newDept = document.getElementById('new-dept');
    newDept.innerHTML = '';
    for (var i = 0; i < depts.length; i++) {
        newDept.innerHTML += '<option value="' + depts[i].id + '">' + depts[i].name + '</option>';
    }
}

async function loadTasks() {
    var deptFilter = document.getElementById('dept-filter').value;
    var res = await fetch(API + '/api/tasks', {headers: authHeaders()});
    var data = await res.json();
    var tasks = data.tasks || [];
    if (deptFilter) {
        var filtered = [];
        for (var i = 0; i < tasks.length; i++) {
            if (!tasks[i].department || tasks[i].department === deptFilter) filtered.push(tasks[i]);
        }
        tasks = filtered;
    }
    if (currentTab === 'browser') {
        var filtered2 = [];
        for (var i = 0; i < tasks.length; i++) {
            if (!tasks[i].mode || tasks[i].mode === 'browser') filtered2.push(tasks[i]);
        }
        tasks = filtered2;
    } else if (currentTab === 'api') {
        var filtered3 = [];
        for (var i = 0; i < tasks.length; i++) {
            if (tasks[i].mode === 'api') filtered3.push(tasks[i]);
        }
        tasks = filtered3;
    }
    var list = document.getElementById('task-list');
    if (!tasks.length) {
        list.innerHTML = '<p style="color:#999;text-align:center;padding:40px;">暂无任务，点击"新增任务"创建</p>';
        return;
    }
    list.innerHTML = '';
    for (var i = 0; i < tasks.length; i++) {
        list.appendChild(renderTaskCard(tasks[i]));
    }
}

function renderTaskCard(t) {
    var enabled = t.enabled !== false;
    var deptName = t.department ? '<span class="dept-tag">🏢 ' + t.department + '</span>' : '';
    var badge = enabled ? '<span class="badge badge-on">● 启用</span>' : '<span class="badge badge-off">● 禁用</span>';
    var isAdmin = currentUser.role === 'admin';
    var fname = t.filename || '';
    
    var card = document.createElement('div');
    card.className = 'task-card';
    
    var header = document.createElement('div');
    header.className = 'task-header';
    
    var leftDiv = document.createElement('div');
    leftDiv.className = 'task-header-left';
    
    var infoDiv = document.createElement('div');
    var modeTag = '';
    if (t.mode === 'api') {
        modeTag = '<span class="mode-tag mode-api">🔌 API</span>';
    } else {
        modeTag = '<span class="mode-tag mode-browser">🌐 浏览器</span>';
    }
    infoDiv.innerHTML = '<div style="display:flex;align-items:center;gap:8px;">' +
        '<span class="task-name">' + (t.name || '未命名') + '</span>' + modeTag + badge + deptName + '</div>' +
        '<div class="task-desc-row"><span class="desc">' + (t.description || '') + '</span>' +
        (t.schedule ? '<span class="schedule">⏰ ' + t.schedule + '</span>' : '') + '</div>';
    leftDiv.appendChild(infoDiv);
    header.appendChild(leftDiv);
    
    var rightDiv = document.createElement('div');
    rightDiv.className = 'task-header-right';
    
    var runBtn = document.createElement('button');
    runBtn.className = 'btn btn-sm btn-success';
    runBtn.textContent = '▶ 执行';
    runBtn.onclick = function() { runTask(fname); };
    rightDiv.appendChild(runBtn);
    
    if (isAdmin) {
        var toggleBtn = document.createElement('button');
        toggleBtn.className = 'btn btn-sm btn-warning';
        toggleBtn.textContent = enabled ? '禁用' : '启用';
        toggleBtn.onclick = function() { toggleTask(fname); };
        rightDiv.appendChild(toggleBtn);
        
        var delBtn = document.createElement('button');
        delBtn.className = 'btn btn-sm btn-danger';
        delBtn.textContent = '删除';
        delBtn.onclick = function() { deleteTask(fname); };
        rightDiv.appendChild(delBtn);
    }
    header.appendChild(rightDiv);
    card.appendChild(header);
    
    return card;
}


var currentParamsTaskId = null;

async function runTask(taskId) {
    // 先获取任务详情，检查是否需要参数输入
    try {
        var res = await fetch(API + '/api/tasks/' + taskId, {headers: authHeaders()});
        var task = await res.json();
        
        if (task.params_input && task.params_input.length > 0) {
            // 需要参数输入，弹出参数弹窗
            currentParamsTaskId = taskId;
            showParamsModal(task);
        } else {
            // 不需要参数，直接执行
            addLog('开始执行任务: ' + task.name, 'info');
            var res2 = await fetch(API + '/api/tasks/' + taskId + '/run', {
                method: 'POST',
                headers: {...authHeaders(), 'Content-Type': 'application/json'},
                body: JSON.stringify({})
            });
            var data = await res2.json();
            if (data.status === 'started') addLog('任务已启动...', 'info');
        }
    } catch(e) { addLog('请求失败: ' + e.message, 'error'); }
}

var fileBrowserCallback = null;

function showParamsModal(task) {
    _savedParamsTask = task;
    _savedParamsValues = {};
    document.getElementById('params-modal-title').textContent = task.name || '输入任务参数';
    var body = document.getElementById('params-modal-body');
    body.innerHTML = '';
    
    var params = task.params_input || [];
    for (var i = 0; i < params.length; i++) {
        var p = params[i];
        var div = document.createElement('div');
        div.className = 'form-group';
        var label = '<label>' + (p.label || p.key) + (p.required ? ' *' : '') + '</label>';
        var input = '';
        if (p.type === 'date') {
            var today = new Date();
            var weekAgo = new Date(today.getTime() - 7*24*60*60*1000);
            var defVal = p.key === 'date_from' ? weekAgo.toISOString().slice(0,10) : today.toISOString().slice(0,10);
            input = '<input type="date" id="param-' + p.key + '" class="form-input" value="' + defVal + '">';
            div.innerHTML = label + input;
        } else if (p.type === 'file') {
            // 文件选择：用 createElement 避免字符串转义问题
            div.innerHTML = label;
            var grp = document.createElement('div');
            grp.className = 'file-browse-group';
            var inp = document.createElement('input');
            inp.type = 'text';
            inp.id = 'param-' + p.key;
            inp.className = 'form-input';
            inp.placeholder = p.help || '点击右侧按钮选择文件';
            inp.readOnly = true;
            var btn = document.createElement('button');
            btn.className = 'btn btn-sm';
            btn.textContent = '浏览';
            btn.onclick = (function(key, accept) {
                return function() { openFileBrowser(key, accept); };
            })(p.key, p.accept || '');
            grp.appendChild(inp);
            grp.appendChild(btn);
            div.appendChild(grp);
        } else if (p.type === 'path') {
            // 目录选择：用 createElement 避免字符串转义问题
            div.innerHTML = label;
            var grp2 = document.createElement('div');
            grp2.className = 'file-browse-group';
            var inp2 = document.createElement('input');
            inp2.type = 'text';
            inp2.id = 'param-' + p.key;
            inp2.className = 'form-input';
            inp2.placeholder = p.help || '点击右侧按钮选择目录';
            inp2.readOnly = true;
            var btn2 = document.createElement('button');
            btn2.className = 'btn btn-sm';
            btn2.textContent = '浏览';
            btn2.onclick = (function(key) {
                return function() { openPathBrowser(key); };
            })(p.key);
            grp2.appendChild(inp2);
            grp2.appendChild(btn2);
            div.appendChild(grp2);
        } else if (p.type === 'select') {
            // 下拉选择
            var opts = (p.options || []).map(function(o) {
                return '<option value="' + o + '">' + o + '</option>';
            }).join('');
            input = '<select id="param-' + p.key + '" class="form-input">' + opts + '</select>';
            div.innerHTML = label + input;
        } else {
            input = '<input type="text" id="param-' + p.key + '" class="form-input" placeholder="' + (p.help || '') + '">';
            div.innerHTML = label + input;
        }
        body.appendChild(div);
    }
    
    document.getElementById('params-modal').style.display = 'flex';
}

// 文件浏览器
async function openFileBrowser(paramKey, accept) {
    // 保存当前所有参数值
    saveCurrentParamsValues();
    fileBrowserCallback = function(selectedPath) {
        var el = document.getElementById('param-' + paramKey);
        if (el) el.value = selectedPath;
        _savedParamsValues[paramKey] = selectedPath;
    };
    await showFileBrowser('');
}

async function openPathBrowser(paramKey) {
    // 保存当前所有参数值
    saveCurrentParamsValues();
    fileBrowserCallback = function(selectedPath) {
        var el = document.getElementById('param-' + paramKey);
        if (el) el.value = selectedPath;
        _savedParamsValues[paramKey] = selectedPath;
    };
    await showFileBrowser('', true);
}

// 保存当前参数弹窗中的所有值
var _savedParamsValues = {};
function saveCurrentParamsValues() {
    var inputs = document.querySelectorAll('#params-modal-body input');
    for (var i = 0; i < inputs.length; i++) {
        var key = inputs[i].id.replace('param-', '');
        if (key) _savedParamsValues[key] = inputs[i].value;
    }
}

async function showFileBrowser(currentPath, dirOnly) {
    var url = API + '/api/files/browse';
    if (currentPath) url += '?path=' + encodeURIComponent(currentPath);
    
    try {
        var res = await fetch(url, {headers: authHeaders()});
        var data = await res.json();
        
        var modal = document.getElementById('params-modal');
        var body = document.getElementById('params-modal-body');
        body.innerHTML = '';
        
        // 标题栏
        var titleDiv = document.createElement('div');
        titleDiv.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;';

        var pathSpan = document.createElement('span');
        pathSpan.style.cssText = 'font-size:13px;color:#666;';
        pathSpan.textContent = data.current;
        titleDiv.appendChild(pathSpan);

        var btnGroup = document.createElement('div');
        btnGroup.style.cssText = 'display:flex;gap:5px;';

        var upBtn = document.createElement('button');
        upBtn.className = 'btn btn-sm';
        upBtn.textContent = '上级';
        upBtn.onclick = function() { showFileBrowser(data.parent, dirOnly); };
        btnGroup.appendChild(upBtn);

        var selBtn = document.createElement('button');
        selBtn.className = 'btn btn-sm btn-success';
        selBtn.textContent = '选择此目录';
        selBtn.onclick = function() { selectCurrentPath(data.current); };
        btnGroup.appendChild(selBtn);

        titleDiv.appendChild(btnGroup);
        body.appendChild(titleDiv);
        
        // 文件列表
        var listDiv = document.createElement('div');
        listDiv.style.cssText = 'max-height:300px;overflow-y:auto;border:1px solid #eee;border-radius:6px;';
        
        for (var i = 0; i < data.items.length; i++) {
            var item = data.items[i];
            var itemDiv = document.createElement('div');
            itemDiv.style.cssText = 'padding:8px 12px;cursor:pointer;border-bottom:1px solid #f5f5f5;font-size:13px;';
            itemDiv.onmouseover = function() { this.style.background = '#f0f8ff'; };
            itemDiv.onmouseout = function() { this.style.background = ''; };
            
            var icon = item.is_dir ? '📁 ' : '📄 ';
            var nameDisplay = icon + item.name;
            
            if (item.is_dir) {
                itemDiv.onclick = (function(path, dOnly) {
                    return function() { showFileBrowser(path, dOnly); };
                })(item.path, dirOnly);
            } else if (!dirOnly) {
                itemDiv.onclick = (function(path) {
                    return function() {
                        if (fileBrowserCallback) fileBrowserCallback(path);
                        // 恢复参数输入弹窗（不关闭，不清空taskId）
                        restoreParamsModal();
                    };
                })(item.path);
            } else {
                itemDiv.style.opacity = '0.5';
                itemDiv.style.cursor = 'default';
            }
            
            itemDiv.textContent = nameDisplay;
            listDiv.appendChild(itemDiv);
        }
        body.appendChild(listDiv);
        
        // 返回按钮
        var backDiv = document.createElement('div');
        backDiv.style.cssText = 'margin-top:10px;text-align:right;';
        backDiv.innerHTML = '<button class="btn btn-warning btn-sm" onclick="closeParamsModal()">取消</button>';
        body.appendChild(backDiv);
        
    } catch(e) {
        addLog('文件浏览失败: ' + e.message, 'error');
    }
}

function selectCurrentPath(path) {
    if (fileBrowserCallback) fileBrowserCallback(path);
    // 恢复参数输入弹窗
    restoreParamsModal();
}

// 恢复参数输入弹窗（保留之前填的数据）
var _savedParamsTask = null;
function restoreParamsModal() {
    if (_savedParamsTask) {
        // 先备份已保存的值（showParamsModal 内部会清空 _savedParamsValues）
        var backup = {};
        for (var k in _savedParamsValues) backup[k] = _savedParamsValues[k];
        showParamsModal(_savedParamsTask);
        // 恢复之前填写的值
        _savedParamsValues = backup;
        for (var key in backup) {
            var el = document.getElementById('param-' + key);
            if (el) el.value = backup[key];
        }
    }
}

function closeParamsModal() {
    document.getElementById('params-modal').style.display = 'none';
    currentParamsTaskId = null;
}

async function runTaskWithParams() {
    if (!currentParamsTaskId) return;
    
    // 收集参数
    var taskId = currentParamsTaskId;
    var inputs = document.querySelectorAll('#params-modal-body input');
    var params = {};
    for (var i = 0; i < inputs.length; i++) {
        var key = inputs[i].id.replace('param-', '');
        params[key] = inputs[i].value;
    }
    
    addLog('开始执行任务(带参数): ' + JSON.stringify(params), 'info');
    closeParamsModal();
    
    try {
        var res = await fetch(API + '/api/tasks/' + taskId + '/run', {
            method: 'POST',
            headers: {...authHeaders(), 'Content-Type': 'application/json'},
            body: JSON.stringify({params: params})
        });
        var data = await res.json();
        if (data.status === 'started') addLog('任务已启动...', 'info');
    } catch(e) { addLog('请求失败: ' + e.message, 'error'); }
}

async function toggleTask(taskId) {
    await fetch(API + '/api/tasks/' + taskId + '/toggle', {method:'POST', headers:authHeaders()});
    loadTasks();
}

async function deleteTask(taskId) {
    if (!confirm('确定删除此任务？')) return;
    await fetch(API + '/api/tasks/' + taskId, {method:'DELETE', headers:authHeaders()});
    loadTasks();
}

function openCreateModal() {
    editTaskId = null;
    document.getElementById('modal-title').textContent = '新增任务';
    document.getElementById('task-name').value = '';
    document.getElementById('task-desc').value = '';
    document.getElementById('task-schedule').value = '';
    document.getElementById('task-mode').value = currentTab;
    document.getElementById('task-filename-pattern').value = '';
    document.getElementById('task-dingtalk-webhook').value = '';
    document.getElementById('steps-container').innerHTML = '';
    addStep();
    showModal();
}

async function editTask(taskId) {
    editTaskId = taskId;
    var res = await fetch(API + '/api/tasks/' + taskId, {headers: authHeaders()});
    var t = await res.json();
    document.getElementById('modal-title').textContent = '编辑任务';
    document.getElementById('task-name').value = t.name || '';
    document.getElementById('task-desc').value = t.description || '';
    document.getElementById('task-schedule').value = t.schedule || '';
    document.getElementById('task-mode').value = t.mode || 'browser';
    document.getElementById('task-filename-pattern').value = t.filename_pattern || '';
    document.getElementById('task-dingtalk-webhook').value = t.dingtalk_webhook || '';
    var deptSel = document.getElementById('task-dept');
    if (t.department) deptSel.value = t.department;
    var container = document.getElementById('steps-container');
    container.innerHTML = '';
    var steps = t.steps || [];
    for (var i = 0; i < steps.length; i++) { addStep(steps[i]); }
    showModal();
}

function addStep(existing) {
    var c = document.getElementById('steps-container');
    var div = document.createElement('div');
    div.className = 'step-editor';
    var s = existing || {};
    
    var typeSel = document.createElement('select');
    typeSel.innerHTML = '<option value="browser"' + (s.type==='browser'?' selected':'') + '>浏览器操作</option>' +
        '<option value="data"' + (s.type==='data'?' selected':'') + '>数据处理</option>' +
        '<option value="notify"' + (s.type==='notify'?' selected':'') + '>通知</option>';
    
    var actionSel = document.createElement('select');
    actionSel.innerHTML = '<option value="navigate"' + (s.action=='navigate'?' selected':'') + '>打开页面</option>' +
        '<option value="login"' + (s.action=='login'?' selected':'') + '>扫码登录</option>' +
        '<option value="click"' + (s.action=='click'?' selected':'') + '>智能点击</option>' +
        '<option value="download"' + (s.action=='download'?' selected':'') + '>智能下载</option>' +
        '<option value="wait"' + (s.action=='wait'?' selected':'') + '>智能等待</option>' +
        '<option value="fill"' + (s.action=='fill'?' selected':'') + '>智能填充</option>' +
        '<option value="process_excel"' + (s.action=='process_excel'?' selected':'') + '>处理Excel</option>';
    
    var descInput = document.createElement('input');
    descInput.type = 'text';
    descInput.placeholder = '步骤描述';
    descInput.value = s.description || '';
    descInput.style.flex = '1';
    descInput.style.minWidth = '150px';
    
    var paramInput = document.createElement('input');
    paramInput.type = 'text';
    paramInput.placeholder = '参数(JSON)';
    paramInput.value = s.params ? JSON.stringify(s.params) : '';
    paramInput.style.width = '200px';
    
    var delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm btn-danger';
    delBtn.textContent = '删除';
    delBtn.onclick = function() { div.remove(); };
    
    var wrapper = document.createElement('div');
    wrapper.style.display = 'flex';
    wrapper.style.gap = '8px';
    wrapper.style.flexWrap = 'wrap';
    wrapper.appendChild(typeSel);
    wrapper.appendChild(actionSel);
    wrapper.appendChild(descInput);
    wrapper.appendChild(paramInput);
    wrapper.appendChild(delBtn);
    div.appendChild(wrapper);
    c.appendChild(div);
}

async function saveTask() {
    var name = document.getElementById('task-name').value.trim();
    if (!name) { alert('请输入任务名称'); return; }
    var dept = document.getElementById('task-dept').value;
    if (!dept && currentUser.role !== 'admin') { alert('请选择所属部门'); return; }
    var steps = [];
    var editors = document.querySelectorAll('.step-editor');
    for (var i = 0; i < editors.length; i++) {
        var sel = editors[i].querySelectorAll('select');
        var inp = editors[i].querySelectorAll('input');
        var params = {};
        if (inp[1].value) { try { params = JSON.parse(inp[1].value); } catch(e) {} }
        steps.push({type:sel[0].value, action:sel[1].value, description:inp[0].value, params:params});
    }
    var body = {
        name: name,
        description: document.getElementById('task-desc').value,
        schedule: document.getElementById('task-schedule').value,
        mode: document.getElementById('task-mode').value,
        department: dept,
        steps: steps,
        filename_pattern: document.getElementById('task-filename-pattern').value,
        dingtalk_webhook: document.getElementById('task-dingtalk-webhook').value
    };
    if (editTaskId) {
        await fetch(API + '/api/tasks/' + editTaskId, {method:'PUT',headers:authHeaders(),body:JSON.stringify(body)});
    } else {
        await fetch(API + '/api/tasks', {method:'POST',headers:authHeaders(),body:JSON.stringify(body)});
    }
    closeModal();
    loadTasks();
}

function showModal() { document.getElementById('modal').style.display = 'block'; document.getElementById('modal-overlay').style.display = 'block'; }
function closeModal() { document.getElementById('modal').style.display = 'none'; document.getElementById('modal-overlay').style.display = 'none'; }

async function openUserModal() {
    var res = await fetch(API + '/api/users', {headers: authHeaders()});
    var data = await res.json();
    var users = data.users || [];
    var list = document.getElementById('user-list');
    var html = '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#f0f0f0;"><th style="padding:8px;text-align:left;">用户名</th><th style="padding:8px;text-align:left;">部门</th><th style="padding:8px;text-align:left;">角色</th><th style="padding:8px;text-align:left;">操作</th></tr></thead><tbody>';
    for (var i = 0; i < users.length; i++) {
        var u = users[i];
        html += '<tr style="border-bottom:1px solid #eee;"><td style="padding:8px;">' + u.username + '</td><td style="padding:8px;">' + u.department + '</td><td style="padding:8px;">' + u.role + '</td><td style="padding:8px;">';
        if (u.username === 'admin') {
            html += '(不可删除)';
        } else {
            html += '<button class="btn btn-sm btn-danger" data-user="' + u.username + '">删除</button>';
        }
        html += '</td></tr>';
    }
    html += '</tbody></table>';
    list.innerHTML = html;
    
    // 绑定删除按钮
    var delBtns = list.querySelectorAll('button[data-user]');
    for (var j = 0; j < delBtns.length; j++) {
        delBtns[j].onclick = function() { deleteUser(this.getAttribute('data-user')); };
    }
    
    document.getElementById('user-modal').style.display = 'block';
    document.getElementById('user-modal-overlay').style.display = 'block';
}

function closeUserModal() { document.getElementById('user-modal').style.display = 'none'; document.getElementById('user-modal-overlay').style.display = 'none'; }

async function createUser() {
    var username = document.getElementById('new-username').value.trim();
    var password = document.getElementById('new-password').value.trim();
    var dept = document.getElementById('new-dept').value;
    var role = document.getElementById('new-role').value;
    if (!username || !password) { alert('请填写用户名和密码'); return; }
    await fetch(API + '/api/users', {method:'POST',headers:authHeaders(),body:JSON.stringify({username:username,password:password,department:dept,role:role})});
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    openUserModal();
}

async function deleteUser(username) {
    if (!confirm('确定删除用户 ' + username + '?')) return;
    await fetch(API + '/api/users/' + username, {method:'DELETE',headers:authHeaders()});
    openUserModal();
}

function addLog(msg, type) {
    var body = document.getElementById('log-body');
    var line = document.createElement('div');
    line.className = 'log-line log-' + (type || 'info');
    line.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
    // 有新日志时自动展开
    var panel = document.getElementById('log-panel');
    if (panel.classList.contains('collapsed') && (type === 'error' || type === 'success')) {
        panel.classList.remove('collapsed');
    }
}

function connectWS() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(proto + '//' + location.host + '/ws');
    ws.onmessage = function(e) {
        var d = JSON.parse(e.data);
        addLog(d.message, d.type);
    };
}

// ==================== 我的配置 ====================
async function openConfigModal() {
    try {
        var res = await fetch(API + '/api/my-config', {headers: authHeaders()});
        var data = await res.json();
        renderConfigForm(data.groups || []);
        document.getElementById('config-modal').style.display = 'block';
        document.getElementById('config-modal-overlay').style.display = 'block';
    } catch(e) { addLog('加载配置失败: ' + e.message, 'error'); }
}

function closeConfigModal() {
    document.getElementById('config-modal').style.display = 'none';
    document.getElementById('config-modal-overlay').style.display = 'none';
}

function renderConfigForm(groups) {
    var form = document.getElementById('config-form');
    form.innerHTML = '';
    for (var gi = 0; gi < groups.length; gi++) {
        var g = groups[gi];
        var groupDiv = document.createElement('div');
        groupDiv.style.marginBottom = '20px';

        var groupTitle = document.createElement('h3');
        groupTitle.style.cssText = 'color:#008b8b;font-size:14px;margin-bottom:10px;border-bottom:1px solid #eee;padding-bottom:5px;';
        groupTitle.textContent = g.label || g.name;
        groupDiv.appendChild(groupTitle);

        for (var ii = 0; ii < g.items.length; ii++) {
            var item = g.items[ii];
            var itemDiv = document.createElement('div');
            itemDiv.style.cssText = 'margin-bottom:12px;padding:10px;background:#f8f9fa;border-radius:6px;';

            var label = document.createElement('label');
            label.style.cssText = 'display:block;font-weight:500;color:#555;font-size:13px;margin-bottom:4px;';
            var requiredMark = item.required ? ' <span style="color:#e74c3c;">*</span>' : '';
            label.innerHTML = item.label + requiredMark;
            itemDiv.appendChild(label);

            if (item.help) {
                var help = document.createElement('p');
                help.style.cssText = 'color:#999;font-size:11px;margin:2px 0 6px;';
                help.textContent = item.help;
                itemDiv.appendChild(help);
            }

            var inputRow = document.createElement('div');
            inputRow.style.cssText = 'display:flex;gap:8px;align-items:center;';

            var input = document.createElement('input');
            input.type = 'text';
            input.id = 'config-' + item.key.replace(/\./g, '-');
            input.placeholder = item.type === 'file' ? '可上传文件或直接填路径' : '请输入路径';
            input.value = item.current_value || '';
            input.style.cssText = 'flex:1;padding:8px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;';
            input.setAttribute('data-key', item.key);
            inputRow.appendChild(input);

            if (item.type === 'file') {
                var uploadBtn = document.createElement('button');
                uploadBtn.className = 'btn btn-sm';
                uploadBtn.textContent = '📤 上传';
                uploadBtn.style.cssText = 'white-space:nowrap;';
                uploadBtn.setAttribute('data-key', item.key);
                var captureKey = item.key;
                uploadBtn.onclick = function(k) { return function() { uploadConfigFile(k); }; }(captureKey);
                inputRow.appendChild(uploadBtn);

                if (item.is_uploaded) {
                    var badge = document.createElement('span');
                    badge.style.cssText = 'color:#27ae60;font-size:11px;white-space:nowrap;';
                    badge.textContent = '✓ 已上传';
                    inputRow.appendChild(badge);
                }
            }

            itemDiv.appendChild(inputRow);
            groupDiv.appendChild(itemDiv);
        }
        form.appendChild(groupDiv);
    }
}

async function uploadConfigFile(key) {
    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.style.display = 'none';
    if (key.indexOf('template') >= 0 || key.indexOf('config_json') >= 0) {
        fileInput.accept = '.xlsx,.xls,.json';
    }
    fileInput.onchange = async function() {
        if (!fileInput.files.length) return;
        var file = fileInput.files[0];
        var formData = new FormData();
        formData.append('key', key);
        formData.append('file', file);
        try {
            addLog('上传文件: ' + file.name + ' ...', 'info');
            var res = await fetch(API + '/api/my-config/upload', {
                method: 'POST',
                headers: {'Authorization': 'Bearer ' + token},
                body: formData,
            });
            var data = await res.json();
            if (data.status === 'success') {
                var inputId = 'config-' + key.replace(/\./g, '-');
                var inputEl = document.getElementById(inputId);
                if (inputEl) inputEl.value = data.path;
                addLog('文件已上传: ' + data.filename, 'success');
            } else {
                addLog('上传失败: ' + (data.detail || ''), 'error');
            }
        } catch(e) { addLog('上传失败: ' + e.message, 'error'); }
    };
    document.body.appendChild(fileInput);
    fileInput.click();
    document.body.removeChild(fileInput);
}

async function saveMyConfig() {
    var inputs = document.querySelectorAll('#config-form input[data-key]');
    var items = {};
    for (var i = 0; i < inputs.length; i++) {
        items[inputs[i].getAttribute('data-key')] = inputs[i].value;
    }
    var delivery = {
        download_root: document.getElementById('config-download-root').value,
        filename_pattern: document.getElementById('config-filename-pattern').value,
        dingtalk_webhook: document.getElementById('config-dingtalk-webhook').value,
        email_settings: {
            smtp_server: document.getElementById('config-email-smtp').value,
            smtp_port: document.getElementById('config-email-port').value,
            sender: document.getElementById('config-email-sender').value,
            password: document.getElementById('config-email-password').value,
            receivers: document.getElementById('config-email-receivers').value
        }
    };
    try {
        var res = await fetch(API + '/api/my-config', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({items: items, delivery: delivery}),
        });
        var data = await res.json();
        if (data.status === 'success') {
            addLog('配置已保存 (' + data.saved + '项)', 'success');
            closeConfigModal();
        } else {
            addLog('保存失败', 'error');
        }
    } catch(e) { addLog('保存失败: ' + e.message, 'error'); }
}

function switchTab(tab) {
    currentTab = tab;
    var btns = document.querySelectorAll('.tab-btn');
    for (var i = 0; i < btns.length; i++) {
        btns[i].classList.remove('active');
    }
    if (tab === 'browser') {
        btns[0].classList.add('active');
    } else {
        btns[1].classList.add('active');
    }
    loadTasks();
}

function browseDownloadRoot() {
    alert('请直接在输入框中填写路径，如：D:\\Downloads\\SmartAgent');
}

function openTemplateModal() {
    document.getElementById('template-modal').style.display = 'block';
    document.getElementById('template-modal-overlay').style.display = 'block';
    loadTemplates();
}

function closeTemplateModal() {
    document.getElementById('template-modal').style.display = 'none';
    document.getElementById('template-modal-overlay').style.display = 'none';
}

async function loadTemplates() {
    var listEl = document.getElementById('template-list');
    listEl.innerHTML = '<p style="color:#999;text-align:center;padding:20px;">加载中...</p>';
    try {
        var res = await fetch(API + '/api/templates', {headers: authHeaders()});
        var data = await res.json();
        var templates = data.templates || [];
        if (!templates.length) {
            listEl.innerHTML = '<p style="color:#999;text-align:center;padding:20px;">暂无模板，上传一个吧</p>';
            return;
        }
        listEl.innerHTML = '';
        for (var i = 0; i < templates.length; i++) {
            var t = templates[i];
            var item = document.createElement('div');
            item.className = 'template-item';
            item.innerHTML = '<div class="template-info">' +
                '<div class="template-name">' + (t.name || '未命名') + '</div>' +
                '<div class="template-meta">' +
                    (t.description || '') +
                    (t.type ? ' · ' + t.type : '') +
                    (t.upload_time ? ' · ' + t.upload_time : '') +
                '</div>' +
            '</div>' +
            '<div>' +
                '<button class="btn btn-sm btn-danger" data-id="' + t.id + '">删除</button>' +
            '</div>';
            var delBtn = item.querySelector('button');
            delBtn.onclick = function(id) { return function() { deleteTemplate(id); }; }(t.id);
            listEl.appendChild(item);
        }
    } catch(e) {
        listEl.innerHTML = '<p style="color:#e74c3c;text-align:center;padding:20px;">加载失败: ' + e.message + '</p>';
    }
}

async function uploadTemplate() {
    var name = document.getElementById('tpl-name').value.trim();
    var desc = document.getElementById('tpl-desc').value.trim();
    var type = document.getElementById('tpl-type').value;
    var fileInput = document.getElementById('tpl-file');
    if (!name) { alert('请输入模板名称'); return; }
    if (!fileInput.files.length) { alert('请选择文件'); return; }
    var file = fileInput.files[0];
    var formData = new FormData();
    formData.append('name', name);
    formData.append('description', desc);
    formData.append('type', type);
    formData.append('file', file);
    try {
        addLog('上传模板: ' + file.name + ' ...', 'info');
        var res = await fetch(API + '/api/templates', {
            method: 'POST',
            headers: {'Authorization': 'Bearer ' + token},
            body: formData
        });
        var data = await res.json();
        if (data.status === 'success') {
            addLog('模板已上传: ' + name, 'success');
            document.getElementById('tpl-name').value = '';
            document.getElementById('tpl-desc').value = '';
            document.getElementById('tpl-file').value = '';
            loadTemplates();
        } else {
            addLog('上传失败: ' + (data.detail || ''), 'error');
        }
    } catch(e) { addLog('上传失败: ' + e.message, 'error'); }
}

async function deleteTemplate(id) {
    if (!confirm('确定删除此模板？')) return;
    try {
        var res = await fetch(API + '/api/templates/' + id, {
            method: 'DELETE',
            headers: authHeaders()
        });
        var data = await res.json();
        if (data.status === 'success') {
            addLog('模板已删除', 'success');
            loadTemplates();
        } else {
            addLog('删除失败', 'error');
        }
    } catch(e) { addLog('删除失败: ' + e.message, 'error'); }
}


init();

</script>


<!-- 任务参数输入弹窗 -->
<div id="params-modal" class="modal" style="display:none;">
    <div class="modal-content">
        <div class="modal-header">
            <span class="modal-title" id="params-modal-title">输入任务参数</span>
            <span class="close" onclick="closeParamsModal()">&times;</span>
        </div>
        <div class="modal-body" id="params-modal-body">
        </div>
        <div class="modal-footer">
            <button class="btn-primary" onclick="runTaskWithParams()" id="params-run-btn">▶ 开始执行</button>
            <button class="btn-secondary" onclick="closeParamsModal()">取消</button>
        </div>
    </div>
</div>

<!-- 智能问答浮窗 -->
<div id="chat-fab" onclick="toggleChat()" title="智能助手">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
    </svg>
</div>

<div id="chat-panel" style="display:none;">
    <div class="chat-header">
        <span>🤖 智能助手</span>
        <span class="chat-close" onclick="toggleChat()">&times;</span>
    </div>
    <div id="chat-messages" class="chat-messages">
        <div class="chat-msg bot">你好！我是智能助手，可以帮你查看任务、执行任务、回答问题。试试问我"列出我的任务"或"执行公众号资金账单"。</div>
    </div>
    <div id="chat-suggestions" class="chat-suggestions"></div>
    <div class="chat-input-area">
        <input type="text" id="chat-input" placeholder="输入消息..." onkeypress="if(event.key==='Enter')sendChat()"/>
        <button onclick="sendChat()" id="chat-send-btn">发送</button>
    </div>
</div>

<style>
#chat-fab {
    position: fixed; bottom: 30px; right: 30px; width: 56px; height: 56px;
    background: #4f46e5; border-radius: 50%; cursor: pointer; z-index: 10000;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 4px 12px rgba(79,70,229,0.4); transition: transform 0.2s;
}
#chat-fab:hover { transform: scale(1.1); }
#chat-panel {
    position: fixed; bottom: 30px; right: 30px; width: 380px; height: 520px;
    background: #fff; border-radius: 12px; z-index: 10001;
    display: flex; flex-direction: column;
    box-shadow: 0 8px 32px rgba(0,0,0,0.15); overflow: hidden;
}
.chat-header {
    background: #4f46e5; color: #fff; padding: 14px 16px; font-size: 15px; font-weight: 600;
    display: flex; justify-content: space-between; align-items: center;
}
.chat-close { cursor: pointer; font-size: 20px; }
.chat-messages {
    flex: 1; overflow-y: auto; padding: 16px; background: #f8f9fa;
    display: flex; flex-direction: column; gap: 10px;
}
.chat-msg {
    max-width: 80%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.5;
    word-wrap: break-word; white-space: pre-wrap;
}
.chat-msg.user { background: #4f46e5; color: #fff; align-self: flex-end; }
.chat-msg.bot { background: #fff; color: #333; align-self: flex-start; border: 1px solid #e5e7eb; }
.chat-msg.system { background: #fef3c7; color: #92400e; align-self: center; font-size: 13px; }
.chat-suggestions { padding: 8px 12px; display: flex; flex-wrap: wrap; gap: 6px; }
.chat-suggestion {
    background: #eef2ff; color: #4f46e5; border: 1px solid #c7d2fe;
    border-radius: 16px; padding: 4px 12px; font-size: 12px; cursor: pointer;
}
.chat-suggestion:hover { background: #c7d2fe; }
.chat-input-area { padding: 12px; border-top: 1px solid #e5e7eb; display: flex; gap: 8px; }
#chat-input {
    flex: 1; border: 1px solid #d1d5db; border-radius: 8px; padding: 8px 12px; font-size: 14px; outline: none;
}
#chat-input:focus { border-color: #4f46e5; }
#chat-send-btn {
    background: #4f46e5; color: #fff; border: none; border-radius: 8px;
    padding: 8px 18px; cursor: pointer; font-size: 14px;
}
#chat-send-btn:hover { background: #4338ca; }
#chat-send-btn:disabled { background: #9ca3af; cursor: not-allowed; }
.chat-typing { color: #9ca3af; font-size: 13px; align-self: flex-start; padding: 4px 14px; }
</style>

<script>
function toggleChat() {
    var panel = document.getElementById('chat-panel');
    var fab = document.getElementById('chat-fab');
    if (panel.style.display === 'none') {
        panel.style.display = 'flex';
        fab.style.display = 'none';
        loadSuggestions();
        document.getElementById('chat-input').focus();
    } else {
        panel.style.display = 'none';
        fab.style.display = 'flex';
    }
}

async function loadSuggestions() {
    try {
        var res = await fetch('/api/chat/suggestions', {headers: authHeaders()});
        var data = await res.json();
        var el = document.getElementById('chat-suggestions');
        el.innerHTML = '';
        (data.suggestions || []).forEach(function(s) {
            var btn = document.createElement('span');
            btn.className = 'chat-suggestion';
            btn.textContent = s;
            btn.onclick = function() {
                document.getElementById('chat-input').value = s;
                sendChat();
            };
            el.appendChild(btn);
        });
    } catch(e) {}
}

function addChatMsg(text, role) {
    var div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.textContent = text;
    document.getElementById('chat-messages').appendChild(div);
    var container = document.getElementById('chat-messages');
    container.scrollTop = container.scrollHeight;
    return div;
}

async function sendChat() {
    var input = document.getElementById('chat-input');
    var text = input.value.trim();
    if (!text) return;

    addChatMsg(text, 'user');
    input.value = '';
    document.getElementById('chat-send-btn').disabled = true;

    var typing = document.createElement('div');
    typing.className = 'chat-typing';
    typing.textContent = '正在思考...';
    typing.id = 'chat-typing-indicator';
    document.getElementById('chat-messages').appendChild(typing);
    document.getElementById('chat-messages').scrollTop = 999999;

    try {
        var res = await fetch('/api/chat', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({message: text})
        });
        var data = await res.json();

        typing.remove();

        if (data.task_started) {
            addChatMsg(data.reply, 'bot');
            var sysDiv = addChatMsg('任务已启动，请查看执行状态', 'system');
            setTimeout(function() { loadTasks(); }, 2000);
        } else {
            addChatMsg(data.reply, 'bot');
        }
    } catch(e) {
        typing.remove();
        addChatMsg('网络错误，请重试', 'system');
    }

    document.getElementById('chat-send-btn').disabled = false;
    input.focus();
}

// ==================== 系统依赖检测 ====================
function openDepsModal() {
    document.getElementById('deps-modal-overlay').style.display = 'block';
    document.getElementById('deps-modal').style.display = 'block';
    checkDeps();
}

function closeDepsModal() {
    document.getElementById('deps-modal-overlay').style.display = 'none';
    document.getElementById('deps-modal').style.display = 'none';
}

async function checkDeps() {
    var list = document.getElementById('deps-list');
    list.innerHTML = '<div style="text-align:center;color:#888;padding:20px;">检测中...</div>';
    try {
        var res = await fetch('/api/system/deps', {headers: authHeaders()});
        var data = await res.json();
        var html = '';
        data.deps.forEach(function(dep) {
            var statusColor = dep.installed ? '#27ae60' : '#e74c3c';
            var statusText = dep.installed ? '✅ 已安装' : '❌ 未安装';
            var actionBtn = dep.installed
                ? '<span style="color:#999;font-size:12px;">无需操作</span>'
                : `<button class="btn btn-sm btn-success" onclick="installDep('${dep.name}', this)">安装</button>`;
            html += '<div class="template-item">' +
                '<div class="template-info">' +
                '<div class="template-name">' + dep.name + ' <span style="color:' + statusColor + ';font-size:12px;margin-left:8px;">' + statusText + '</span></div>' +
                '<div class="template-meta">' + dep.desc + (dep.installed ? '' : ' · 命令: ' + dep.install_cmd) + '</div>' +
                '</div>' +
                '<div>' + actionBtn + '</div>' +
                '</div>';
        });
        if (data.all_installed) {
            html = '<div style="background:#d4edda;color:#155724;padding:10px;border-radius:6px;margin-bottom:10px;font-size:13px;">✅ 所有依赖已安装，桌面自动化功能可用</div>' + html;
        } else {
            html = '<div style="background:#f8d7da;color:#721c24;padding:10px;border-radius:6px;margin-bottom:10px;font-size:13px;">⚠️ 部分依赖未安装，桌面自动化任务可能无法运行。点击"安装"按钮自动安装</div>' + html;
        }
        list.innerHTML = html;
    } catch(e) {
        list.innerHTML = '<div style="color:#e74c3c;padding:20px;">检测失败：' + e.message + '（可能需要管理员权限）</div>';
    }
}

async function installDep(depName, btn) {
    if (!confirm('确认安装 ' + depName + '？安装过程可能需要1-2分钟')) return;
    btn.disabled = true;
    btn.textContent = '安装中...';
    try {
        var res = await fetch('/api/system/deps/install', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({name: depName})
        });
        var data = await res.json();
        if (data.status === 'success') {
            btn.textContent = '✅ 已安装';
            btn.className = 'btn btn-sm';
            btn.style.background = '#27ae60';
            alert(depName + ' 安装成功！');
            checkDeps();  // 重新检测
        } else {
            btn.disabled = false;
            btn.textContent = '安装';
            alert(depName + ' 安装失败：' + (data.error || '未知错误') + '\\n\\n输出：' + (data.output || ''));
        }
    } catch(e) {
        btn.disabled = false;
        btn.textContent = '安装';
        alert('网络错误：' + e.message);
    }
}
</script>

</body>
</body>
</html>"""
