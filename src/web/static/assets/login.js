/* 登录页 JS */
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
