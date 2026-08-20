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
var cookieRefreshTimers = {}; // 记录每个key的定时器

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
            // WebSocket推送cookie_refresh消息时更新按钮文字
            // 5分钟后恢复按钮（防止卡住）
            cookieRefreshTimers[key] = setTimeout(function() {
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

/* WebSocket回调：更新刷新按钮状态 */
function onCookieRefreshMessage(d) {
    // 找到对应的刷新按钮
    var buttons = document.querySelectorAll('#cookie-key-list button');
    for (var i = 0; i < buttons.length; i++) {
        var btn = buttons[i];
        if (btn.onclick && btn.onclick.toString().indexOf(d.key) >= 0) {
            if (d.status === 'success' || d.status === 'timeout' || d.status === 'error') {
                btn.disabled = false;
                btn.textContent = '🔄 刷新';
                if (cookieRefreshTimers[d.key]) {
                    clearTimeout(cookieRefreshTimers[d.key]);
                    delete cookieRefreshTimers[d.key];
                }
            } else if (d.status === 'waiting') {
                btn.textContent = '⏳ 检测中(' + d.message.match(/\d+/) + 's)...';
            }
            break;
        }
    }
}

/* ---------- 多账号注册由管理员在后台操作，前端不暴露 ---------- */
