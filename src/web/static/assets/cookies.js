/* ============================================================
 * Cookie管理模块 (cookies.js)
 *   展示cookie_key列表 + 所属平台 + 状态 + 刷新按钮
 *   支持多账号：同一平台可注册多个cookie_key
 *   不暴露cookie内容，用户只能：刷新(浏览器登录) / 新增账号
 * ============================================================ */

function openCookieModal() {
    document.getElementById('cookie-modal').style.display = 'block';
    document.getElementById('cookie-modal-overlay').style.display = 'block';
    loadCookieKeys();
}
function closeCookieModal() {
    document.getElementById('cookie-modal').style.display = 'none';
    document.getElementById('cookie-modal-overlay').style.display = 'none';
}

/* ---------- 加载cookie_key列表 ---------- */
async function loadCookieKeys() {
    var el = document.getElementById('cookie-key-list');
    if (!el) return;
    el.innerHTML = '<div style="text-align:center;color:#888;padding:20px;">加载中...</div>';
    try {
        var res = await fetch(API + '/api/cookies/keys', {headers: authHeaders()});
        var data = await res.json();
        var keys = data.keys || [];
        if (!keys.length) {
            el.innerHTML = '<p style="color:#999;text-align:center;padding:20px;">暂无Cookie记录</p>';
            return;
        }

        var html = '';
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            var statusHtml = '';
            var btnClass = 'btn btn-sm';

            if (k.status === 'valid') {
                statusHtml = '<span style="color:#27ae60;">● 有效</span>' +
                    '<span style="color:#999;font-size:12px;margin-left:8px;">剩余' + k.days_left + '天</span>';
            } else if (k.status === 'expired') {
                statusHtml = '<span style="color:#e74c3c;">● 已失效</span>';
                btnClass = 'btn btn-sm btn-warning';
            } else {
                statusHtml = '<span style="color:#999;">● 未登录</span>';
                btnClass = 'btn btn-sm btn-success';
            }

            // 平台标签
            var platformTag = k.platform
                ? '<span style="color:#888;font-size:11px;background:#f0f0f0;padding:2px 6px;border-radius:3px;">' + k.platform + '</span>'
                : '<span style="color:#ccc;font-size:11px;">未知平台</span>';

            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:12px;border-bottom:1px solid #eee;">' +
                '<div>' +
                    '<div style="font-weight:500;font-size:14px;">' + k.key + '</div>' +
                    '<div style="margin-top:4px;display:flex;align-items:center;gap:8px;">' +
                        platformTag + statusHtml +
                    '</div>' +
                '</div>' +
                '<button class="' + btnClass + '" onclick="refreshCookie(\'' + k.key + '\', this)">🔄 刷新</button>' +
            '</div>';
        }
        el.innerHTML = html;
    } catch(e) {
        el.innerHTML = '<div style="color:#e74c3c;text-align:center;padding:20px;">加载失败: ' + e.message + '</div>';
    }
}

/* ---------- 刷新cookie（打开浏览器，后台自动检测登录） ---------- */
async function refreshCookie(key, btn) {
    btn.disabled = true;
    btn.textContent = '⏳ 打开浏览器中...';
    addLog('正在刷新Cookie: ' + key, 'info');
    try {
        var res = await fetch(API + '/api/cookies/' + encodeURIComponent(key) + '/refresh', {
            method: 'POST',
            headers: authHeaders()
        });
        var data = await res.json();
        if (res.ok) {
            addLog('浏览器已打开，请在浏览器中登录（' + key + '），登录成功后自动保存', 'info');
            btn.textContent = '⏳ 等待登录...';
            // WebSocket会在登录成功/超时后推送消息，loadCookieKeys会自动刷新
            // 5分钟后恢复按钮（防止卡住）
            setTimeout(function() {
                btn.disabled = false;
                btn.textContent = '🔄 刷新';
            }, 300000);
        } else {
            addLog('刷新失败: ' + (data.detail || ''), 'error');
            btn.disabled = false;
            btn.textContent = '🔄 刷新';
        }
    } catch(e) {
        addLog('请求失败: ' + e.message, 'error');
        btn.disabled = false;
        btn.textContent = '🔄 刷新';
    }
}

/* ---------- 新增Cookie Key（多账号） ---------- */
async function showAddCookieKeyForm() {
    // 加载平台列表
    var sel = document.getElementById('cookie-key-platform');
    sel.innerHTML = '<option value="">选择平台...</option>';
    try {
        var res = await fetch(API + '/api/cookies/platforms', {headers: authHeaders()});
        var data = await res.json();
        var platforms = data.platforms || [];
        for (var i = 0; i < platforms.length; i++) {
            sel.innerHTML += '<option value="' + platforms[i].name + '">' + platforms[i].name + '</option>';
        }
    } catch(e) {
        addLog('加载平台列表失败: ' + e.message, 'error');
    }
    document.getElementById('cookie-key-form').style.display = 'block';
}

function hideAddCookieKeyForm() {
    document.getElementById('cookie-key-form').style.display = 'none';
    document.getElementById('cookie-key-name').value = '';
    document.getElementById('cookie-key-platform').value = '';
}

async function registerCookieKey() {
    var key = document.getElementById('cookie-key-name').value.trim();
    var platform = document.getElementById('cookie-key-platform').value;
    if (!key || !platform) {
        addLog('请填写名称并选择平台', 'error');
        return;
    }
    try {
        var res = await fetch(API + '/api/cookies/register', {
            method: 'POST',
            headers: Object.assign({}, authHeaders(), {'Content-Type': 'application/json'}),
            body: JSON.stringify({key: key, platform: platform})
        });
        var data = await res.json();
        if (res.ok) {
            addLog('已添加Cookie Key: ' + key + ' (平台: ' + platform + ')', 'success');
            hideAddCookieKeyForm();
            loadCookieKeys();
        } else {
            addLog('添加失败: ' + (data.detail || ''), 'error');
        }
    } catch(e) {
        addLog('请求失败: ' + e.message, 'error');
    }
}
