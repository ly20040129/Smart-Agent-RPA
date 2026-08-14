/* ============================================================
 * 智能助手模块 (chat.js)
 * ============================================================ */

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
        var typingEl = document.getElementById('chat-typing-indicator');
        if (typingEl) typingEl.remove();
        addChatMsg(data.reply || '(无响应)', 'bot');

        if (data.task_started) {
            var msgDiv = document.createElement('div');
            msgDiv.className = 'chat-msg system';
            msgDiv.textContent = '✅ 已为你启动任务: ' + (data.task_id || '');
            document.getElementById('chat-messages').appendChild(msgDiv);
        }
    } catch(e) {
        var typingEl2 = document.getElementById('chat-typing-indicator');
        if (typingEl2) typingEl2.remove();
        addChatMsg('请求失败: ' + e.message, 'bot');
    } finally {
        document.getElementById('chat-send-btn').disabled = false;
    }
}
