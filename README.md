# Smart Agent RPA 🤖

**YAML 配置 + 纯函数编写自动化任务。**

Smart Agent RPA 是一个基于 Python 的轻量级自动化平台。通过 **YAML 配置 + importlib 直接调用 workflow 函数** 的方式执行任务——浏览器操作、API 调用、数据清洗、MySQL 落库、钉钉交付，一条龙。无注册表、无运行器、无装饰器，保持每个文件从头读到尾就是完整流程。

---

## 设计哲学

**YAML 定义"做什么"，Python 实现"怎么做"，一层薄薄的工具 SDK。**

| 文件类型 | 作用 | 类比 |
| :--- | :--- | :--- |
| `data/tasks/*.yaml` | 任务配置（步骤、参数、描述） | **菜谱** |
| `workflows/*.py` | 浏览器/API 自动化逻辑 | **厨师做菜** |
| `sdk/*.py` | 薄工具层（Browser / pfetch / MySQL / 钉钉） | **厨具** |

标杆写法参考 `workflows/tm_video_up.py`：读数据源 → 逐条处理 → 就地更新状态，失败处理看得见。

---

## 技术栈

| 分类 | 技术 | 用途 |
|------|------|------|
| 语言 | Python 3.10+ | 主要开发语言 |
| Web框架 | FastAPI + Uvicorn | Web界面和API服务 |
| 浏览器自动化 | Playwright | 模拟浏览器操作（纯选择器） |
| 数据处理 | Pandas + openpyxl | Excel/CSV读写和数据清洗 |
| 数据库 | MySQL + SQLAlchemy | 业务数据存储 |
| 缓存 | Redis | Cookie持久化、任务锁 |
| LLM | 智谱 GLM（可选） | 对话、后续 AI 自动化 |
| 认证 | JWT + bcrypt | 用户登录、部门权限隔离 |
| 前端 | 原生HTML/CSS/JS | 无框架依赖 |

---

## 目录结构

```
smart-agent-rpa/
│
├── main.py                 启动入口
├── requirements.txt        依赖清单
├── start.bat               Windows一键启动脚本
│
├── config/                 ── 全局配置 ──
│   ├── config.yaml         主配置（LLM、数据库、浏览器、Web等）
│   └── prompts.yaml        LLM提示词模板
│
├── data/                   ── 运行时数据（自动生成）──
│   ├── tasks/*.yaml        任务配置文件（每个文件 = 一个任务）
│   ├── auth/               用户账号、部门数据
│   ├── task_history/       任务执行历史
│   ├── downloads/          下载的文件
│   └── screenshots/        截图
│
├── workflows/              ★ 写自动化脚本的地方 ──
│   ├── jd_sz_compete.py    京东商智竞品数据（API型标杆：登录→API→MySQL→钉钉）
│   ├── tm_video_up.py      天猫视频上传（浏览器型标杆：多维表→登录→循环操作）
│   └── dingtalk_test.py    钉钉机器人测试
│
├── data_clean/             ── 数据清洗脚本 ──
│
├── sdk/                    ── 薄工具层（workflow 直接 import 的都在这）──
│   ├── browser_sdk.py      浏览器操作（纯 Playwright，一个类）
│   ├── http.py             pfetch：带cookie的网页API请求
│   ├── jd.py               京东平台 API（web_api / fetch_paged）
│   ├── pdd.py              拼多多平台 API
│   ├── wechat_pay.py       微信支付平台 API
│   ├── dingtalk_webhook.py  钉钉群聊通知机器人（notifications.dingtalk）
│   ├── dingtalk_robot.py    钉钉单聊/群发机器人（delivery.dingtalk）
│   ├── delivery.py          文件交付（本地/钉钉/邮件三渠道）
│   ├── cookie_manager.py   多平台Cookie存取 + 域名过滤 + 使用锁
│   ├── mysql_sdk.py        数据库操作（实体类自动建表）
│   ├── entities/           实体类（每个表一个）
│   ├── dingtalk_ai_table.py 钉钉AI表格
│   ├── excel_sdk.py        Excel处理
│   ├── chart_sdk.py        图表生成
│   ├── data_tools.py       输出保存工具
│   ├── slider_captcha.py   滑块验证码
│   └── local_config.py     本地路径配置
│
└── src/                    ── 平台发动机（不写workflow也要在的部分）──
    ├── agent/
    │   ├── task_executor.py    任务执行器（加载→加锁→调函数→交付→通知）
    │   ├── task_manager.py     任务配置管理（读写YAML）
    │   ├── task_queue.py       任务队列
    │   ├── scheduler.py        定时调度
    │   ├── notifier.py         通知门面（调 sdk/dingtalk）
    │   └── template_manager.py 模板管理
    ├── auth/auth_manager.py    用户认证、JWT
    ├── core/                   配置加载、LLM客户端、日志
    ├── storage/                Redis / MySQL / 统一存储入口
    └── web/                    FastAPI路由、前端页面
```

---

## 🚀 快速开始

### 1. 环境准备
确保已安装 **Python 3.10+**、**Redis** 和 **MySQL**。

### 2. 安装依赖
```bash
git clone https://github.com/your-username/smart-agent-rpa.git
cd smart-agent-rpa
pip install -r requirements.txt
playwright install chromium
```

### 3. 配置
复制配置模板并填入你的密钥：
```bash
cp config/config.example.yaml config/config.yaml
```
编辑 `config/config.yaml`：LLM（智谱 GLM-4-Flash 免费）、MySQL、钉钉 app_key/app_secret。
程序启动时会自动创建所需的表结构。

### 4. 启动
```bash
python main.py
```
访问 `http://127.0.0.1:8000`，默认账号：`admin` / `admin123`。

---

## 一个任务是怎么跑起来的

```
用户在Web界面点击"执行"
    ↓
src/web/api.py              收到请求，提交到任务队列
    ↓
src/agent/task_executor.py  读取 data/tasks/xxx.yaml，调 workflow 函数
    ↓
workflows/xxx.py            async def run(user_params) -> dict
    ↓                        （浏览器用 sdk/browser_sdk，API用 sdk/jd.py 等）
delivery / notifier         结果文件交付 + 钉钉通知
```

workflow 函数契约（见 `workflows/__init__.py`）：
- 签名：`async def xxx(user_params: dict) -> dict`
- 返回：必须含 `"status"`（success/failed），失败时含 `"error"`
- 需要交付结果文件时返回 `"output_file": 绝对路径`

---

## 热更新

改 `workflows/*.py` 或 `data_clean/*.py` 后**无需重启服务**，下次执行任务时自动加载最新代码。

**为什么不重载 `sdk/` 和 `src/`：** 这些模块持有全局单例和活动连接（如 Redis、MySQL、WebSocket），reload 会丢失状态。改了基础设施层请重启服务。

**手动重载单个模块：** 可调用 API `POST /api/tasks/{task_id}/reload`。

---

## Cookie 管理

- **存取**：Redis（30天过期），按平台域名过滤，只留核心cookie
- **浏览器任务**：`Browser(cookie_key=...)` start时恢复、close时自动保存
- **Web刷新**：管理界面点"刷新"→ 打开浏览器登录 → 自动轮询检测 → 保存
- **API任务**：`web_api()` 注入cookie，响应判定失效 → 抛 `CookieExpiredError`
- **失效处理写在 workflow 里**：捕获异常 → `notify_expired(key)` 发钉钉 → 就地更新任务状态
- **登录判定**：cookie硬门槛（核心cookie≥2个 + 关键cookie长度≥16）+ 页面成功信号（URL不在登录页 + 命中关键词）
- **使用锁**：同一账号cookie同时只允许一个任务使用（Redis锁 + 僵尸锁检测）
- **多账号**：`jd_shangzhi_店铺A`、`jd_shangzhi_店铺B` 各用各的key，Web界面可注册

新增平台改一处：`sdk/cookie_manager.py` 的 `PLATFORM_CONFIG` 加
`login_url / cookie_domain / core_cookies`（可选 `critical_cookie` / `success_signals`）。

---

## 平台 API 工具（sdk/jd.py 等）

每个平台一个平铺模块，纯函数无类：

```python
from sdk.jd import web_api, fetch_paged

# 单次调用
data = await web_api(
    url="https://vcf.jd.com/api/finance/saleBill/list",
    cookie_key="jd_shop_ibay",
    data='[{"bizType":"4","page":1}]',
)

# 分页拉取
rows = await fetch_paged(
    url="https://vcf.jd.com/api/finance/saleBill/list",
    cookie_key="jd_shop_ibay",
    body_template={"bizType": "4"},
    date_from="2026-08-01",
    date_to="2026-08-31",
)

# cookie失效时
from sdk.http import CookieExpiredError, notify_expired
try:
    data = await web_api(...)
except CookieExpiredError:
    await notify_expired("jd_shop_ibay")   # 发钉钉提醒
    return {"status": "failed", "error": "cookie失效"}
```

新增平台：新建 `sdk/xxx.py`，写 `HEADERS` + `is_expired()` + `web_api()` 三样即可。

---

## Browser SDK（sdk/browser_sdk.py）

纯 Playwright 选择器操作，常用方法：

```python
async with Browser(cookie_key="xxx") as b:
    await b.goto("https://...")
    await b.type_text("input[name='user']", "账号")      # 逐字符输入
    await b.click_by_selector("button.submit")            # 按选择器点击
    await b.click_button_by_text("确 定")                  # 按文本点击
    await b.upload_file("input[type='file']", "D:/v.mp4") # 上传文件
    await b.click_and_download(text="下载账单")            # 点击+捕获下载
    await b.is_visible("#ok", timeout=3000)               # 是否可见
    await b.sleep(2)
    page = await b._get_page()                            # 拿原始page，啥都能干
```

iframe 操作直接用原始 page：

```python
page = await agent._get_page()
frame = page.frame_locator("iframe.xxx")
await frame.locator("input[placeholder='标题']").fill("标题")
```

---

## 新增一个自动化任务

### 第1步：写 workflow（workflows/my_task.py）

参考 `workflows/tm_video_up.py` 的结构：

```python
import workflows  # noqa: F401 — 自动设置项目根路径
from sdk.browser_sdk import Browser

async def run(user_params: dict) -> dict:
    agent = Browser(cookie_key="my_platform")
    await agent.start()
    try:
        await agent.goto("https://xxx.com")
        # ... 业务逻辑 ...
        await agent.close()
        return {"status": "success"}
    except Exception as e:
        await agent.close()
        return {"status": "failed", "error": str(e)}
```

### 第2步：建任务配置（data/tasks/my_task.yaml）

```yaml
name: 我的任务
description: xxx
department: finance
enabled: true
schedule: ''
workflow_module: workflows.my_task
workflow_func: run
params_input:
  - key: date_from
    label: 开始日期
    type: date
    required: true
```

### 第3步：刷新Web界面，任务自动出现，点击执行。

---

## 钉钉机器人

| 类型 | 代码文件 | 配置位置（config.yaml） | 能做什么 |
|------|---------|------------------------|----------|
| 群聊Webhook | `sdk/dingtalk_webhook.py` | `notifications.dingtalk` | 群聊通知/告警 |
| 单聊自建应用 | `sdk/dingtalk_robot.py` | `delivery.dingtalk` | 给具体人发文字/文件 |
| 钉钉多维表 | `sdk/dingtalk_ai_table.py` | `delivery.dingtalk`（复用） | 读写多维表数据 |

测试任务：`data/tasks/test_webhook.yaml`、`test_robot.yaml`、`test_dingtalk_group.yaml`。

---

## 数据存储

| 数据类型 | 存储位置 |
|---------|---------|
| 任务配置 | data/tasks/*.yaml |
| 用户账号 | data/auth/users.json |
| Cookie | Redis（30天过期） |
| 业务数据 | MySQL（实体类自动建表） |
| 下载的文件 | data/downloads/ 或用户指定目录 |
| 任务执行历史 | MySQL（task_history 表） |

---

## 部门权限

- 管理员在Web"用户管理"里给同事创建账号、分配部门
- 财务用户只能看财务部任务，业务用户只能看业务部任务

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。
