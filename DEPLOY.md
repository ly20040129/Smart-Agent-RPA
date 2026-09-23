# 服务器部署指南（企业级上线）

## 一、部署前必答的问题

**Q：客户触发任务后，浏览器在哪里打开？**

**A：在服务器上打开，客户电脑上什么都看不到。** RPA 浏览器由服务器上的 Python
进程拉起，客户只能通过 Web 界面看到日志和截图。因此部署前必须：

1. `config.yaml` 设置 `browser.headless: true`（无头模式，Linux 服务器没有图形界面，不设会直接报错）
2. 登录类流程依赖账号密码自动登录（tm_video_up 已是这种模式）；
   需要"扫码/验证码"的登录暂不支持远程无头执行

## 二、服务器环境要求

| 组件 | 要求 |
|------|------|
| OS | Linux（推荐 Ubuntu 22.04+）或 Windows Server |
| Python | 3.10+ |
| Redis | 5.0+（Cookie、任务锁、去重） |
| MySQL | 5.7+ / 8.0（业务数据、任务历史） |
| Chromium | `playwright install chromium && playwright install-deps` |

## 三、部署步骤

```bash
# 1. 上代码
git clone <你的仓库> /opt/smart-agent-rpa && cd /opt/smart-agent-rpa

# 2. 虚拟环境 + 依赖
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium && playwright install-deps

# 3. 配置
cp config/config.example.yaml config/config.yaml
#    编辑：MySQL密码、LLM key、钉钉凭证、browser.headless: true、web.host

# 4. 启动（生产用多 worker 会破坏任务队列单例，固定 1 个进程）
python main.py
```

**进程守护（systemd）：**

```ini
# /etc/systemd/system/smart-agent.service
[Unit]
Description=Smart Agent RPA
After=network.target mysql.service redis.service

[Service]
WorkingDirectory=/opt/smart-agent-rpa
ExecStart=/opt/smart-agent-rpa/.venv/bin/python main.py
Restart=always
RestartSec=5
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now smart-agent
```

## 四、上线前安全检查清单

- [ ] **修改默认密码**：admin/admin123 必须改（Web 用户管理里重置）
- [ ] **JWT_SECRET**：生产建议用环境变量 `export JWT_SECRET=<64位随机串>`，
      不依赖 data/auth/.jwt_secret 文件（当前机制：env 优先 → 文件 → 自动生成）
- [ ] **不要暴露 8000 端口到公网**：用 Nginx 反代 + HTTPS（Let's Encrypt）
- [ ] config.yaml 不要进 git（已做 .gitignore），服务器上权限 600
- [ ] 钉钉 app_secret、数据库密码等全部走 config.yaml 或环境变量，不硬编码

**Nginx 反代（含 WebSocket）：**

```nginx
server {
    listen 443 ssl;
    server_name rpa.yourcompany.com;
    ssl_certificate     /etc/letsencrypt/live/rpa.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rpa.yourcompany.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    # WebSocket（实时日志依赖这个）
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

## 五、服务器模式下的排障手段

- **错误截图**：tm_video_up 上传失败时自动截图到 `data/screenshots/`，
  Web 界面/文件系统均可查看
- **日志**：`data/logs/app_YYYY-MM-DD.log`（loguru，按天分割）
- **任务历史**：`data/task_history/` + Web 界面历史页

## 六、运维约定

- 热更新只对 `workflows/` 和 `data_clean/` 生效（改任务代码不用重启）
- **改了 `sdk/` 或 `src/` 必须重启服务**（systemctl restart smart-agent）
- 数据备份：MySQL 定时 mysqldump + `data/` 目录 rsync
- Cookie 有效期 30 天，到期前钉钉群会收到预警，管理员在 Web 界面点刷新
  （⚠️ 无头模式下扫码登录不可用，依赖账号密码登录的平台才能远程刷新）
