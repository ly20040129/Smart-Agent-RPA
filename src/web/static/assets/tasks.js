/* ============================================================
 * 任务管理模块 (tasks.js)
 *   负责: 任务列表、执行(含参数弹窗)、新增/编辑任务、删除/启停
 *         用户管理、系统依赖检测
 * ============================================================ */

var editTaskId = null;

/* ---------- 任务列表 ---------- */
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
    if (t.mode === 'api') modeTag = '<span class="mode-tag mode-api">🔌 API</span>';
    else modeTag = '<span class="mode-tag mode-browser">🌐 浏览器</span>';
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
        var editBtn = document.createElement('button');
        editBtn.className = 'btn btn-sm';
        editBtn.textContent = '编辑';
        editBtn.onclick = function() { editTask(fname); };
        rightDiv.appendChild(editBtn);

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

/* ---------- 参数弹窗 & 文件浏览器 ---------- */
var currentParamsTaskId = null;
var fileBrowserCallback = null;
var _savedParamsValues = {};
var _savedParamsTask = null;

async function runTask(taskId) {
    try {
        var res = await fetch(API + '/api/tasks/' + taskId, {headers: authHeaders()});
        var task = await res.json();

        if (task.params_input && task.params_input.length > 0) {
            currentParamsTaskId = taskId;
            showParamsModal(task);
        } else {
            addLog('开始执行任务: ' + task.name, 'info');
            var res2 = await fetch(API + '/api/tasks/' + taskId + '/run', {
                method: 'POST',
                headers: {...authHeaders(), 'Content-Type': 'application/json'},
                body: JSON.stringify({})
            });
            var data = await res2.json();
            if (data.status === 'queued' || data.status === 'started') {
                addLog('任务已加入队列 (job=' + (data.job_id || '?') + ')', 'info');
            }
        }
    } catch(e) { addLog('请求失败: ' + e.message, 'error'); }
}

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
        var label = '<label>' + (p.label || p.key) + (p.required ? ' <span style="color:#e74c3c;">*</span>' : '') + '</label>';

        if (p.type === 'date') {
            var today = new Date();
            var weekAgo = new Date(today.getTime() - 7*24*60*60*1000);
            var defVal = p.key === 'date_from' ? weekAgo.toISOString().slice(0,10) : today.toISOString().slice(0,10);
            div.innerHTML = label + '<input type="date" id="param-' + p.key + '" class="form-input" value="' + defVal + '">';
        } else if (p.type === 'file' || p.type === 'path') {
            div.innerHTML = label;
            var grp = document.createElement('div');
            grp.className = 'file-browse-group';
            var inp = document.createElement('input');
            inp.type = 'text';
            inp.id = 'param-' + p.key;
            inp.className = 'form-input';
            inp.placeholder = p.help || ('点击右侧按钮选择' + (p.type === 'file' ? '文件' : '目录'));
            inp.readOnly = false;
            var btn = document.createElement('button');
            btn.className = 'btn btn-sm';
            btn.textContent = '浏览…';
            btn.onclick = (function(key, isFile) {
                return function() {
                    saveCurrentParamsValues();
                    fileBrowserCallback = function(selectedPath) {
                        var el = document.getElementById('param-' + key);
                        if (el) el.value = selectedPath;
                        _savedParamsValues[key] = selectedPath;
                    };
                    showFileBrowser('', !isFile);
                };
            })(p.key, p.type === 'file');
            grp.appendChild(inp);
            grp.appendChild(btn);
            div.appendChild(grp);
        } else if (p.type === 'select') {
            var opts = (p.options || []).map(function(o) {
                return '<option value="' + o + '">' + o + '</option>';
            }).join('');
            div.innerHTML = label + '<select id="param-' + p.key + '" class="form-input">' + opts + '</select>';
        } else {
            div.innerHTML = label + '<input type="text" id="param-' + p.key + '" class="form-input" placeholder="' + (p.help || '') + '">';
        }
        body.appendChild(div);
    }

    document.getElementById('params-modal').style.display = 'flex';
}

function saveCurrentParamsValues() {
    var inputs = document.querySelectorAll('#params-modal-body input');
    for (var i = 0; i < inputs.length; i++) {
        var key = inputs[i].id.replace('param-', '');
        if (key) _savedParamsValues[key] = inputs[i].value;
    }
}

// ============================================================
// 文件/目录选择器
// ============================================================

/**
 * 选择目录（用于"保存位置"等场景）
 * @returns {string} 目录名
 */
async function pickDirectory() {
    try {
        if (!('showDirectoryPicker' in window)) {
            alert('当前浏览器不支持此功能，请使用 Chrome 86+ 或 Edge 86+');
            return null;
        }
        const dirHandle = await window.showDirectoryPicker();
        return dirHandle ? dirHandle.name : null;
    } catch (err) {
        if (err.name === 'AbortError') return null;
        console.error('选择目录失败:', err);
        addLog('选择目录失败: ' + err.message, 'error');
        return null;
    }
}

/**
 * 选择文件（用于"上传模板"等场景）
 * @returns {string} 文件名
 */
function pickFile() {
    return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.style.cssText = 'position:fixed;top:-100px;left:-100px;opacity:0;';
        document.body.appendChild(input);
        
        input.onchange = function() {
            const file = this.files && this.files[0];
            document.body.removeChild(this);
            resolve(file ? file.name : null);
        };
        
        input.oncancel = function() {
            document.body.removeChild(this);
            resolve(null);
        };
        
        input.click();
    });
}

// ============================================================
// 统一入口（根据参数自动选择）
// ============================================================

async function showFileBrowser(currentPath, dirOnly) {
    var url = API + '/api/files/browse';
    if (currentPath) url += '?path=' + encodeURIComponent(currentPath);
    try {
        var res = await fetch(url, {headers: authHeaders()});
        var data = await res.json();

        var body = document.getElementById('params-modal-body');
        body.innerHTML = '';

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

        var listDiv = document.createElement('div');
        listDiv.style.cssText = 'max-height:300px;overflow-y:auto;border:1px solid #eee;border-radius:6px;';

        for (var i = 0; i < data.items.length; i++) {
            var item = data.items[i];
            var itemDiv = document.createElement('div');
            itemDiv.style.cssText = 'padding:8px 12px;cursor:pointer;border-bottom:1px solid #f5f5f5;font-size:13px;';
            itemDiv.onmouseover = function() { this.style.background = '#f0f8ff'; };
            itemDiv.onmouseout = function() { this.style.background = ''; };

            var icon = item.is_dir ? '📁 ' : '📄 ';
            itemDiv.textContent = icon + item.name;

            if (item.is_dir) {
                itemDiv.onclick = (function(path, dOnly) {
                    return function() { showFileBrowser(path, dOnly); };
                })(item.path, dirOnly);
            } else if (!dirOnly) {
                itemDiv.onclick = (function(path) {
                    return function() {
                        if (fileBrowserCallback) fileBrowserCallback(path);
                        restoreParamsModal();
                    };
                })(item.path);
            } else {
                itemDiv.style.opacity = '0.5';
                itemDiv.style.cursor = 'default';
            }
            listDiv.appendChild(itemDiv);
        }
        body.appendChild(listDiv);

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
    restoreParamsModal();
}

function restoreParamsModal() {
    if (_savedParamsTask) {
        var backup = {};
        for (var k in _savedParamsValues) backup[k] = _savedParamsValues[k];
        showParamsModal(_savedParamsTask);
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
        if (data.status === 'queued' || data.status === 'started') {
            addLog('任务已加入队列 (job=' + (data.job_id || '?') + ')', 'info');
        }
    } catch(e) { addLog('请求失败: ' + e.message, 'error'); }
}

/* ---------- 任务启停 & 删除 ---------- */
async function toggleTask(taskId) {
    await fetch(API + '/api/tasks/' + taskId + '/toggle', {method:'POST', headers:authHeaders()});
    loadTasks();
}
async function deleteTask(taskId) {
    if (!confirm('确定删除此任务？')) return;
    await fetch(API + '/api/tasks/' + taskId, {method:'DELETE', headers:authHeaders()});
    loadTasks();
}

/* ---------- 新增/编辑 任务 ---------- */
function showModal() { document.getElementById('modal').style.display = 'block'; document.getElementById('modal-overlay').style.display = 'block'; }
function closeModal() { document.getElementById('modal').style.display = 'none'; document.getElementById('modal-overlay').style.display = 'none'; }

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
    typeSel.innerHTML =
        '<option value="browser"' + (s.type==='browser'?' selected':'') + '>浏览器操作</option>' +
        '<option value="data"'    + (s.type==='data'?' selected':'')    + '>数据处理</option>' +
        '<option value="notify"'  + (s.type==='notify'?' selected':'')  + '>通知</option>' +
        '<option value="deliver"' + (s.type==='deliver'?' selected':'') + '>交付</option>' +
        '<option value="desktop"' + (s.type==='desktop'?' selected':'') + '>桌面自动化</option>';

    var actionSel = document.createElement('select');
    actionSel.innerHTML =
        '<option value="navigate"'       + (s.action=='navigate'?' selected':'')       + '>打开页面</option>' +
        '<option value="login"'          + (s.action=='login'?' selected':'')          + '>扫码登录</option>' +
        '<option value="click"'          + (s.action=='click'?' selected':'')          + '>智能点击</option>' +
        '<option value="download"'       + (s.action=='download'?' selected':'')       + '>智能下载</option>' +
        '<option value="wait"'           + (s.action=='wait'?' selected':'')           + '>智能等待</option>' +
        '<option value="fill"'           + (s.action=='fill'?' selected':'')           + '>智能填充</option>' +
        '<option value="run_workflow"'   + (s.action=='run_workflow'?' selected':'')   + '>调用Workflow</option>' +
        '<option value="process_excel"'  + (s.action=='process_excel'?' selected':'')  + '>处理Excel</option>' +
        '<option value="process_data"'   + (s.action=='process_data'?' selected':'')   + '>清洗数据</option>' +
        '<option value="dingtalk_text"'  + (s.action=='dingtalk_text'?' selected':'')  + '>钉钉文本</option>' +
        '<option value="dingtalk_markdown"' + (s.action=='dingtalk_markdown'?' selected':'') + '>钉钉Markdown</option>' +
        '<option value="deliver_file"'   + (s.action=='deliver_file'?' selected':'')   + '>交付文件</option>';

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
        if (inp[1] && inp[1].value) { try { params = JSON.parse(inp[1].value); } catch(e) {} }
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

/* ---------- 用户管理 ---------- */
async function openUserModal() {
    // 非 admin：按钮应该在 init 时就隐藏了，这里再兜底一层直接拒
    if (currentUser && currentUser.role !== 'admin') {
        alert('⚠️ 仅管理员可以进入用户管理');
        return;
    }

    var res = await fetch(API + '/api/users', {headers: authHeaders()});
    if (!res.ok) {
        var txt = await res.text().catch(()=>'');
        alert('获取用户列表失败 (' + res.status + '): ' + (txt || '权限不足'));
        closeUserModal();
        return;
    }
    var data = await res.json();
    var users = data.users || [];
    var list = document.getElementById('user-list');
    var html = '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#f0f0f0;"><th style="padding:8px;text-align:left;">用户名</th><th style="padding:8px;text-align:left;">部门</th><th style="padding:8px;text-align:left;">角色</th><th style="padding:8px;text-align:left;">操作</th></tr></thead><tbody>';
    for (var i = 0; i < users.length; i++) {
        var u = users[i];
        html += '<tr style="border-bottom:1px solid #eee;"><td style="padding:8px;">' + u.username + '</td><td style="padding:8px;">' + u.department + '</td><td style="padding:8px;">' + u.role + '</td><td style="padding:8px;">';
        html += '<button class="btn btn-sm" style="background:#2980b9;color:#fff;margin-right:4px;" onclick="resetUserPwd(\'' + u.username + '\')">🔑 重置密码</button>';
        if (u.username === 'admin') html += '<span style="color:#888;">(不可删除)</span>';
        else html += '<button class="btn btn-sm btn-danger" onclick="deleteUser(\'' + u.username + '\')">删除</button>';
        html += '</td></tr>';
    }
    html += '</tbody></table>';
    list.innerHTML = html;
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
    if (password.length < 4) { alert('密码至少4位'); return; }
    var res = await fetch(API + '/api/users', {method:'POST',headers:authHeaders(),body:JSON.stringify({username:username,password:password,department:dept,role:role})});
    if (!res.ok) {
        var msg = (await res.text().catch(()=>'')) || '创建失败';
        alert('❌ 创建用户失败：' + msg);
        return;
    }
    document.getElementById('new-username').value = '';
    document.getElementById('new-password').value = '';
    openUserModal();
}

async function resetUserPwd(username) {
    if (!confirm('确定重置用户 ' + username + ' 的密码？\n新密码规则：用户名 + "123"')) return;
    var res = await fetch(API + '/api/users/' + encodeURIComponent(username) + '/reset-password', {method:'PUT',headers:authHeaders()});
    if (!res.ok) { var m = await res.text().catch(()=>''); alert('重置失败: '+m); return; }
    var d = await res.json();
    alert('✅ 密码已重置！\n\n新密码: ' + (d.new_password || (username+'123')) + '\n请立即登录后修改。');
}

async function deleteUser(username) {
    if (!confirm('确定删除用户 ' + username + '?')) return;
    var res = await fetch(API + '/api/users/' + encodeURIComponent(username), {method:'DELETE',headers:authHeaders()});
    if (!res.ok) { var m = await res.text().catch(()=>''); alert('删除失败: '+m); return; }
    openUserModal();
}

/* ---------- 系统依赖 ---------- */
async function openDepsModal() {
    document.getElementById('deps-modal').style.display = 'block';
    document.getElementById('deps-modal-overlay').style.display = 'block';
    await checkDeps();
}
function closeDepsModal() { document.getElementById('deps-modal').style.display = 'none'; document.getElementById('deps-modal-overlay').style.display = 'none'; }

async function checkDeps() {
    var el = document.getElementById('deps-list');
    el.innerHTML = '<div style="text-align:center;color:#888;padding:20px;">检测中...</div>';
    try {
        var res = await fetch(API + '/api/system/deps', {headers: authHeaders()});
        var data = await res.json();
        var deps = data.deps || [];
        var html = '';
        for (var i = 0; i < deps.length; i++) {
            var d = deps[i];
            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:12px;border-bottom:1px solid #eee;">' +
                '<div>' +
                    '<div style="font-weight:500;font-size:14px;">' + d.name +
                        (d.installed ? ' <span style="color:#27ae60;">✓ 已安装</span>' : ' <span style="color:#e74c3c;">✗ 未安装</span>') +
                    '</div>' +
                    '<div style="color:#888;font-size:12px;margin-top:3px;">' + d.desc + '</div>' +
                    (d.error ? '<div style="color:#e74c3c;font-size:11px;margin-top:3px;">错误: ' + d.error + '</div>' : '') +
                '</div>' +
                (d.installed ? '' : '<button class="btn btn-sm btn-success" onclick="installDep(\'' + d.name + '\')">安装</button>') +
            '</div>';
        }
        el.innerHTML = html;
    } catch(e) {
        el.innerHTML = '<div style="text-align:center;color:#e74c3c;padding:20px;">检测失败: ' + e.message + '</div>';
    }
}

async function installDep(name) {
    if (!confirm('确定安装依赖: ' + name + ' ?')) return;
    try {
        var res = await fetch(API + '/api/system/deps/install', {
            method:'POST', headers: authHeaders(),
            body: JSON.stringify({name: name})
        });
        var data = await res.json();
        if (data.status === 'success') {
            alert('安装成功');
        } else {
            alert('安装失败: ' + (data.error || data.output || ''));
        }
    } catch(e) { alert('安装请求失败: ' + e.message); }
    checkDeps();
}
