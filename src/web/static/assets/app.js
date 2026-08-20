/* ============================================================
 * 智能体平台 - 核心 JS 模块 (app.js)
 *   负责: 认证、部门加载、Tab 切换、日志面板、WebSocket、弹窗工具
 * ============================================================ */
var API = '';
var token = localStorage.getItem('token');
var currentUser = JSON.parse(localStorage.getItem('user') || 'null');
var currentTab = 'browser';

/* ---------- 认证 ---------- */
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

/* ---------- 日志面板 ---------- */
function toggleLogPanel() {
    var panel = document.getElementById('log-panel');
    panel.classList.toggle('collapsed');
}
function addLog(msg, type) {
    var body = document.getElementById('log-body');
    var line = document.createElement('div');
    line.className = 'log-line log-' + (type || 'info');
    line.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
    var panel = document.getElementById('log-panel');
    if (panel.classList.contains('collapsed') && (type === 'error' || type === 'success')) {
        panel.classList.remove('collapsed');
    }
}

/* ---------- WebSocket ---------- */
function connectWS() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(proto + '//' + location.host + '/ws');
    ws.onmessage = function(e) {
        try {
            var d = JSON.parse(e.data);
            if (d.type === 'cookie_refresh') {
                // Cookie刷新结果
                if (d.status === 'success') {
                    addLog(d.message, 'success');
                } else if (d.status === 'timeout') {
                    addLog(d.message, 'warn');
                } else if (d.status === 'error') {
                    addLog(d.message, 'error');
                } else if (d.status === 'browser_opened') {
                    addLog(d.message, 'info');
                }
                // 更新按钮状态（包括轮询进度）
                if (typeof onCookieRefreshMessage === 'function') {
                    onCookieRefreshMessage(d);
                }
                // 刷新Cookie列表（成功/超时/错误时才刷新，轮询中不刷新）
                if (d.status === 'success' || d.status === 'timeout' || d.status === 'error') {
                    if (typeof loadCookieKeys === 'function') {
                        loadCookieKeys();
                    }
                }
            } else if (d.type === 'queue' || d.type === 'queue_summary') {
                // 队列状态变化，打一条简洁的日志
                if (d.job) {
                    addLog('队列更新: ' + d.job.task_name + ' -> ' + d.job.status,
                           d.job.status === 'success' ? 'success'
                           : d.job.status === 'failed' ? 'error'
                           : d.job.status === 'running' ? 'info' : 'warn');
                }
            } else {
                addLog(d.message, d.type);
            }
        } catch(err) {
            addLog(e.data, 'info');
        }
    };
}

/* ---------- Tab 切换 ---------- */
function switchTab(tab) {
    currentTab = tab;
    var btns = document.querySelectorAll('.tab-btn');
    for (var i = 0; i < btns.length; i++) btns[i].classList.remove('active');
    if (tab === 'browser') btns[0].classList.add('active');
    else btns[1].classList.add('active');
    loadTasks();
}

/* ---------- 部门 / 初始化 ---------- */
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

async function init() {
    if (!checkAuth()) return;
    try {
        var meRes = await fetch(API + '/api/auth/me', {headers: authHeaders()});
        if (!meRes.ok) throw new Error('token invalid');
        var meData = await meRes.json();
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
