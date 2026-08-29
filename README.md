# 智能体自动化平台

用自然语言描述操作步骤，自动完成网页操作、数据下载、数据清洗、入库和图表生成。
主要场景：公众号账单下载、京东报表下载、天猫库存导出等重复性工作。

---

## 技术栈

| 分类 | 技术 | 用途 |
|------|------|------|
| 语言 | Python 3.10+ | 主要开发语言 |
| Web框架 | FastAPI + Uvicorn | Web界面和API服务 |
| 浏览器自动化 | Playwright | 模拟浏览器操作 |
| 桌面自动化 | uiautomation + OpenCV | 桌面应用控件操作、图像识别（金蝶K/3、网点管家等） |
| LLM | 智谱GLM-4-Flash | 理解页面元素、智能点击下载 |
| 数据处理 | Pandas + openpyxl | Excel/CSV读写和数据清洗 |
| 数据库 | MySQL + SQLAlchemy | 业务数据存储 |
| 缓存 | Redis | Cookie持久化、任务锁 |
| 图表 | Matplotlib | 折线图、柱状图、饼图 |
| 认证 | JWT + bcrypt | 用户登录、部门权限隔离 |
| 前端 | 原生HTML/CSS/JS | 无框架依赖 |
| 配置 | YAML | 任务配置、全局配置 |

---

## 目录结构

```
smart_agent_platform/
│
├── start_web.py            ★ 启动入口（带热更新）
├── main.py                 备用启动入口
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
│   ├── task_history/       任务执行历史(半个日志)
│   ├── downloads/          下载的文件
│   └── screenshots/        截图
│
├── workflows/              ★ 写自动化脚本的地方 ──
│   ├── wechat_pay_bill.py  公众号资金账单（浏览器自动化）
│   ├── jd_ibay_self.py     京东艾贝自营仓（浏览器自动化）
│   └── jd_ibay_self_api.py 京东艾贝自营仓（API自动化）
│
├── data_clean/             ── 数据清洗脚本 ──
│   ├── wechat_bill.py      公众号账单清洗
│   └── jd_ibay_sales.py    京东销售数据清洗
│
├── sdk/                    ── 封装好的工具SDK ──
│   ├── browser_sdk.py      浏览器操作（智能+原生方法）
│   ├── desktop_sdk.py      桌面应用操作（控件+图像识别，金蝶K/3等）
│   ├── cookie_manager.py   ★ 多平台Cookie管理（按域名过滤+存取）
│   ├── mysql_sdk.py        数据库操作（实体类自动建表）
│   ├── excel_sdk.py        Excel处理
│   ├── chart_sdk.py        图表生成
│   ├── local_config.py     本地路径配置
│   ├── entities/           ★ 实体类（每个任务一个，带表名唯一标识）
│   │   ├── __init__.py     基类+Column()+@register_entity+自动扫描
│   │   ├── business_models.py  业务表
│   │   ├── finance_models.py   财务表
│   │   ├── task_models.py      任务历史表
│   │   ├── user_models.py      用户表
│   │   └── jd_ibay_sales.py    京东艾贝出库实体
│   └── platforms/          ★ 平台工具类（Cookie探活+去重预警+API失效刷新）
│       ├── __init__.py     基类+@register_platform+自动扫描
│       ├── jd.py           京东（.jd.com）
│       ├── pdd.py          拼多多（.pdd.com）
│       └── wechat_pay.py   微信支付（.weixin.qq.com）
│
├── local_configs/          ── 用户本地配置 ──
│   ├── config_schema.yaml  配置项定义
│   └── example.local.yaml  配置模板
│
├── src/                    ── 底层实现（一般不用改）──
│   ├── agent/
│   │   ├── task_executor.py    ★ 任务执行器（连接配置和执行的桥梁）
│   │   ├── task_manager.py     任务配置管理（读写YAML）
│   │   ├── smart_browser.py    智能浏览器（LLM选元素）
│   │   ├── smart_desktop.py    智能桌面（LLM选控件，金蝶/网点管家等）
│   │   ├── smart_data_processor.py  智能数据处理器（含数据理解）
│   │   ├── smart_recovery.py   智能异常自修复（LLM诊断+自动重试）
│   │   ├── delivery_service.py 文件交付服务
│   │   └── template_manager.py 模板管理
│   ├── auth/
│   │   └── auth_manager.py     用户认证、JWT
│   ├── core/
│   │   ├── config.py           配置加载
│   │   └── llm_client.py       LLM客户端（智谱/Ollama）
│   ├── storage/
│   │   ├── redis_manager.py    Redis操作（Cookie、锁）
│   │   ├── mysql_manager.py    MySQL操作
│   │   └── storage_manager.py  统一存储入口
│   ├── tools/
│   │   └── browser_controller.py  Playwright底层封装
│   └── web/
│       ├── api.py              FastAPI路由、WebSocket
│       └── html_templates.py   前端页面生成
│
└── test_smart_agent.py      命令行测试工具
```

---

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置
编辑 `config/config.yaml`：
- LLM：默认用智谱GLM-4-Flash（免费），填入API key
- Redis：本地装了Redis默认配置就行
- MySQL：填密码，数据库会自动创建

### 3. 启动
```bash
python start_web.py
```
打开 http://127.0.0.1:8000 ，用 admin / admin123 登录。

---

## 核心概念：一个任务怎么跑起来的？

```
用户在Web界面点击"执行"
    ↓
src/web/api.py              收到请求，调用 TaskExecutor
    ↓
src/agent/task_executor.py  读取 data/tasks/xxx.yaml，按步骤执行
    ↓
    ├── 步骤 type: browser/api  → 调 workflows/xxx.py 的 run() 函数
    ├── 步骤 type: data         → 调 data_clean/xxx.py 的 process() 函数
    └── 步骤 type: deliver      → 调 delivery_service 保存文件到指定位置
```

### YAML 和 Python 的关系

| 文件 | 作用 | 类比 |
|------|------|------|
| `data/tasks/xxx.yaml` | 任务配置（步骤、参数、描述） | 菜谱 |
| `workflows/xxx.py` | 浏览器/API自动化逻辑 | 厨师做菜 |
| `data_clean/xxx.py` | 数据清洗逻辑 | 摆盘装饰 |

**YAML 定义"做什么"，Python 实现"怎么做"。**

---

## Cookie 管理体系

两大模块配合工作：`sdk/cookie_manager.py`（存取 + 过滤）+ `sdk/platforms/__init__.py`（web_api 全链路防护）。

### 一、存取与过滤（cookie_manager.py）

| 能力 | 说明 |
|------|------|
| Redis 存取 | cookie → `agent:cookies:{key}`，默认 30 天过期。**读 cookie 不再自动续期**；续期只发生在两处「真的打请求验证过有效」的路径：① probe_cookie 探活HTTP通过（非缓存命中） ② web_api 真实请求通过 _is_expired 检测 |
| 按域名过滤 ✨新版 | 每个平台配 `cookie_domain`（如 `jd.com`），保留**域名匹配 + 核心cookie名**，丢弃第三方统计 cookie。比老版「只保留核心名」更稳，比全量保存更干净 |
| 核心 cookie 兜底 | `pin` / `thor` / `L_PASS_ID` 等核心名即使域名不匹配也强制保留 |
| 同名同域名去重 | 保留最后一个（即最新值） |
| 三道兜底 | ①核心名强制留 ②本地 JSON 永远保存全量备份 ③过滤日志打前后数量对比 |

每个平台的配置（`PLATFORM_CONFIG` 里）：
```python
"jd_shangzhi": {
    "login_url": "https://shop.jd.com/...",              # 探活和刷新用
    "cookie_domain": "jd.com",                             # 过滤用（关键新增）
    "core_cookies": ["pin", "thor", "pinId", "_pst"],      # 登录检测 + 兜底
    # ---------- 以下为可选字段，不填走默认兜底 ----------
    "critical_cookie": "thor",                             # 关键鉴权cookie，值长度≥16（防placeholder）
    "success_signals": ["退出", "注销", "商家中心", "商智"], # 页面成功信号（命中任一即视为已登录）
    "verify_url": "https://shop.jd.com/api/xxx",           # 【可选】真试验证接口URL
}
```

### 一点五、登录完成判定（三层信号，防止存到 placeholder/旧cookie）

当你在 Web 界面点「🔄 刷新」→ 浏览器打开让你登录 → `wait_login_auto()` 每 3 秒轮询一次，**必须同时通过前两层**才会保存 cookie（第三层可选预留）：

| 层级 | 名称 | 检查什么 | 不通过的常见原因 |
|------|------|---------|-----------------|
| ① | cookie 硬门槛 | a) 核心 cookie ≥ 2 个有值 <br> b) `critical_cookie` 指定值长度 ≥ 16 字符 | 密码还没输，平台先下发了个 placeholder `thor=1` |
| ② | 页面成功信号 | a) 当前 URL **不包含** `login / passport / 登录 / sso` 等关键字（不在登录页）<br> b) title 或正文前 2000 字命中任一 `success_signals` 关键词 | 扫码成功后还在跳转中，页面还在 `passport.jd.com/...` |
| ③ | 真试验证（预留，默认关闭） | 如果配了 `verify_url` 就发 GET 看是不是没跳登录 | — |

**卡在某层怎么看？** 终端 / 后台日志会每轮打印：
```
轮询#12 (36.0s): 核心cookie 1/4≥2 | 原因：关键cookie thor 值太短/缺失、页面仍在登录页或未发现登录成功信号 | URL: https://passport.jd.com/new/login.aspx
```
看到 `原因：xxx` 就知道差在哪一层了。

### 二、web_api 四步防护（PlatformBase）

每次调用 `web_api()` 都会按顺序执行以下流程（⚠️ 注意：探活只是**建议性质**，不当法官，不会乱删 cookie）：

```
调用 web_api(url, cookie_key, ...)
    ↓ ① TTL 预警（先检查再续期，看到的是真实剩余）
    TTL < 7 天 → 发「即将过期」钉钉提醒（12小时去重）

    ↓ ② 轻量探活【只是建议，不当法官】✨新行为
    · 若 cookie TTL 很接近 30 天（30 分钟内刚保存的）→ 信任新鲜cookie，跳过 ✅
    · 若 8 小时内探活缓存命中 → 跳过 ✅
    · 真发 GET login_url + cookie，allow_redirects=False
      → 跳登录 / 401 / 403 / 页面含「未登录」 → 疑似失效
         ❗ 只打 warning，**不删 cookie / 不抛异常**，继续走③
      → 通过 → 写8小时缓存 + 续TTL 30天

    ↓ ③ 真实 API 请求 + 响应过期检测【最终法官】
    子类 _is_expired() 判定失效 → 删 cookie + 发失效通知（5分钟去重）+ 抛CookieExpiredError

    ↓ ④ 成功调用 → 从这一刻起 TTL 续期 30 天
    返回解析后的 JSON
```

### 三、钉钉通知去重

用 Redis `SETNX + EX` 实现，不增加任何新依赖：

| 通知类型 | 去重周期 | Redis Key |
|---------|---------|-----------|
| Cookie 失效（最终法官判定） | 5 分钟 | `agent:dedup:cookie_notify:expired:{key}` |
| Cookie 即将过期（TTL预警） | 12 小时 | `agent:dedup:cookie_notify:warning:{key}` |
| 探活成功缓存 | 8 小时 | `agent:cookie_probe_ok:{key}` |

> **多个任务同时发现同一个 cookie 失效 → 只发 1 条钉钉。**

### 四、新增平台要填的 3+3 件事（3 必选 3 可选）

1. **必选**：`cookie_manager.PLATFORM_CONFIG` 里填 `login_url` / `cookie_domain` / `core_cookies`
2. **可选**：同处再补 `critical_cookie`（关键鉴权 cookie 名）+ `success_signals`（登录成功信号词列表），**填了能大幅降低误判保存概率**
3. `sdk/platforms/xxx.py` 继承 `PlatformBase`，至少实现 `_is_expired()`
4. 其他不用改 → 自动拥有：探活 / 去重 / 预警 / 续期 / 三层登录判定 / 30分钟新鲜cookie跳过探活 全套能力

---

## 平台工具类（sdk/platforms/）

每个平台一个工具类，封装该平台的 **Cookie管理 + API调用 + 失效检测 + 自动刷新**。
启动时自动扫描注册，新增平台只加文件不改核心代码。

### 已注册平台

| 平台 | 根域名 | Cookie Key | 失效检测 |
|------|--------|-----------|---------|
| 京东 (jd) | .jd.com | jd_shop, jd_shop_ibay, jd_shangzhi | 401/302 + 'login' + success:false |
| 拼多多 (pdd) | .pdd.com | pdd | 401/302/403 + 'login' + 错误码 |
| 微信支付 (wechat_pay) | .weixin.qq.com | wechat_pay | 401/302/403 + redirect + ret_code |

### 核心方法

```python
from sdk.platforms import get_platform

jd = get_platform("jd")

# Cookie管理
cookie_header = jd.get_cookie_header("jd_shop_ibay")   # 获取Cookie字符串
is_valid = jd.is_cookie_valid("jd_shop_ibay")           # 检查有效性
await jd.refresh_cookie("jd_shop_ibay")                  # 触发浏览器刷新

# API调用（自动注入Cookie + 失效检测 + 刷新重试）
data = await jd.web_api(
    url="https://vcf.jd.com/api/finance/saleBill/list",
    cookie_key="jd_shop_ibay",
    method="POST",
    data='[{"bizType":"4","page":1}]',
)

# 分页获取（通用分页逻辑）
all_data = await jd.fetch_paged(
    url="https://vcf.jd.com/api/finance/saleBill/list",
    cookie_key="jd_shop_ibay",
    body_template={"bizType": "4"},
    date_from="2026-08-01",
    date_to="2026-08-20",
)
```

### 新增平台

```python
# sdk/platforms/taobao.py
from sdk.platforms import register_platform, PlatformBase

@register_platform("taobao")
class TaobaoPlatform(PlatformBase):
    root_domain = ".taobao.com"
    default_headers = {"Referer": "https://shop.taobao.com/", ...}

    def _is_expired(self, resp, text):
        return resp.status in (401, 302) or "login" in text.lower()
```

保存后重启服务，自动注册。

---

## 实体类（sdk/entities/）

每个任务/数据表对应一个实体类，带 `table_name` 唯一标识。
配合 `MySQL SDK` 实现自动建表、数据存储、模糊匹配列名。

### 已注册实体

| 实体类 | 表名 | 平台 | Cookie Key |
|--------|------|------|-----------|
| JD_Ibay_Sales | jd_ibay_sales | jd | jd_shop_ibay |

### 用法

```python
from sdk.entities import get_entity
from sdk.mysql_sdk import MySQL

entity = get_entity("jd_ibay_sales")

# 自动建表 + 存Excel数据（模糊匹配列名）
MySQL.save("data/downloads/report.xlsx", table=entity)

# 查询
rows = MySQL.query(entity, limit=100)

# 插入单行
MySQL.insert(entity, {"order_no": "JD001", "amount": 99.5})
```

### 新增实体

```python
# sdk/entities/pdd_order.py
from sdk.entities import register_entity, Column

@register_entity("pdd_order")
class PDD_Order:
    table_name = "pdd_order"
    platform = "pdd"
    cookie_key = "pdd"

    order_id = Column("order_id", "VARCHAR(100)", "订单号")
    amount = Column("amount", "DECIMAL(10,2)", "金额")
    create_time = Column("create_time", "DATETIME", "创建时间")
```

保存后重启服务，自动注册。

---

## 新增一个自动化任务的步骤

### 第1步：写自动化脚本
在 `workflows/` 目录下新建 `.py` 文件：

```python
# workflows/my_task.py
from sdk.browser_sdk import Browser
from sdk.platforms import init_platforms, get_platform
from sdk.entities import init_entities, get_entity
from sdk.mysql_sdk import MySQL

init_platforms()
init_entities()

jd = get_platform("jd")
entity = get_entity("jd_ibay_sales")

async def run(date_from=None, date_to=None, output_dir=None, **kwargs):
    """主函数，参数名要和YAML的params_input对应"""

    # API版：用平台工具类（Cookie自动管理+失效自动刷新）
    data = await jd.fetch_paged(
        url="https://vcf.jd.com/api/finance/saleBill/list",
        cookie_key="jd_shop_ibay",
        body_template={"bizType": "4"},
        date_from=date_from,
        date_to=date_to,
    )

    # 存Excel + 存MySQL（实体类指定表名，自动建表）
    import pandas as pd
    df = pd.DataFrame(data)
    out_file = f"data/downloads/result.xlsx"
    df.to_excel(out_file, index=False)
    MySQL.save(out_file, table=entity)

    return out_file
```

### 第2步（可选）：写数据清洗脚本
在 `data_clean/` 目录下新建 `.py` 文件：

```python
# data_clean/my_task.py
import pandas as pd

def process(input_file, context=None, params=None, **kwargs):
    """清洗数据，返回输出文件路径"""
    df = pd.read_csv(input_file)
    # ... 处理逻辑
    output = "data/output/result.xlsx"
    df.to_excel(output, index=False)
    return output
```

### 第3步：创建任务配置
在 `data/tasks/` 目录下新建 `.yaml` 文件：

```yaml
name: 我的任务
description: 登录XXX网站，下载数据并清洗
department: finance
mode: browser
enabled: true
schedule: ''

params_input:
  - key: date_from
    label: 开始日期
    type: date
    required: true
  - key: date_to
    label: 结束日期
    type: date
    required: true
  - key: output_dir
    label: 保存位置
    type: path
    required: true

steps:
  - type: browser
    action: run_workflow
    description: 打开网站下载数据
    params:
      module: workflows.my_task        # 对应 workflows/my_task.py
      function: run                     # 对应 run() 函数

  - type: data
    action: process_data
    description: 清洗数据
    params:
      module: data_clean.my_task        # 对应 data_clean/my_task.py
      function: process                 # 对应 process() 函数

  - type: deliver
    action: deliver_file
    description: 保存到指定位置
    params:
      channels: [local]
      task_name: 我的任务
```

### 第4步：刷新Web界面
任务会自动出现在列表中，点击执行即可。

---

## Browser SDK 方法速查

SDK 封装了两类方法：**智能方法**（LLM自动找元素）和**原生方法**（直接操作）。

### 智能方法（用自然语言描述，LLM选元素）
```python
await b.click("点击交易中心菜单")         # 智能点击
await b.fill("手机号输入框", "138xxx")    # 智能填写
await b.wait("页面显示账单数据")          # 智能等待
await b.download("下载账单按钮")          # 智能下载
```

### 原生方法（精准操作，不经过LLM）
```python
await b.click_button_by_text("确 定")     # 按文本点按钮
await b.click_by_selector("#submit")      # 按CSS选择器点击
await b.type_text(".date-input", "2026-07-21")  # 逐字符输入
await b.press_key("Enter")                # 按键
await b.select_option("#city", label="北京")    # 选下拉框
await b.check("#agree")                   # 勾选
await b.hover(".menu")                    # 悬停
await b.drag("#src", "#dst")              # 拖拽
await b.scroll("down", 500)               # 滚动
await b.get_text(".total")                # 获取文本
await b.is_visible(".modal")              # 是否可见
await b.wait_for_selector(".loaded")      # 等元素出现
await b.switch_to_frame("iframe")         # 切换到iframe
await b.execute_js("return document.title")  # 执行JS
await b.upload_file("input", "C:/file.pdf")   # 上传文件
await b.screenshot("error")               # 截图
await b.click_and_download(text="确 定")  # 点击+捕获下载
```

完整方法清单见 `sdk/browser_sdk.py`（55个方法）。

---

## Desktop SDK 方法速查

桌面应用自动化 SDK，封装 Windows 桌面应用操作（金蝶K/3、网点管家、金蝶云等桌面客户端）。

### 智能方法（LLM驱动，用自然语言描述）
```python
from src.agent.smart_desktop import SmartDesktop

with SmartDesktop(app_name="金蝶K/3") as sd:
    sd.smart_click("点击登录按钮")              # LLM理解控件树，自己找按钮
    sd.smart_fill("用户名输入框", "admin")      # LLM找输入框
    sd.smart_select("选择账套", "测试账套")     # LLM找下拉框
    sd.smart_wait("登录成功显示主界面")         # LLM判断页面状态
    sd.smart_export("导出本月销售报表", "D:/report.xlsx")  # 智能导出
```

### 原生方法（精准操作，不经过LLM）
```python
from sdk.desktop_sdk import Desktop

with Desktop(app_name="金蝶K/3") as d:
    d.start_app("C:/Program Files/Kingdee/K3.exe")   # 启动应用
    d.click_button("登录")                            # 按文本点按钮
    d.fill_input("用户名", "admin")                   # 按标签填输入框
    d.fill_by_automation_id("username_edit", "admin") # 按AutomationId填
    d.select_menu(["文件", "导出", "Excel"])           # 多级菜单
    d.select_combobox("账套", "测试账套")             # 下拉框
    d.export_file(save_path="D:/report.xlsx")         # 通用导出流程
    d.press_key("Enter")                              # 按键
    d.check("记住密码")                               # 勾选复选框
    d.get_table_data()                                # 提取表格数据
    d.screenshot("D:/error.png")                      # 截图
```

### 图像识别方法（应对无控件树的古老应用）
```python
# 截图模板，后续用图像匹配点击
d.click_image("D:/templates/login_btn.png", confidence=0.8)
d.wait_image("D:/templates/loading.png", timeout=30)
pos = d.find_image("D:/templates/icon.png")  # 返回中心坐标 (x, y)
```

### 在 workflow 脚本中使用（异步）
```python
# workflows/jindie_export.py
from sdk.desktop_sdk import AsyncDesktop

async def run(save_path=None, **kwargs):
    async with AsyncDesktop(app_name="金蝶K/3") as d:
        await d.click_button("登录")
        await d.fill_input("用户名", "admin")
        await d.fill_input("密码", "123456")
        await d.click_button("确定")
        await d.wait_window("金蝶K/3 主控台", timeout=30)
        await d.select_menu(["基础设置", "核算项目", "物料"])
        path = await d.export_file(save_path=save_path)
        return path
```

### 在 YAML 任务中使用
```yaml
name: 金蝶物料导出
description: 从金蝶K/3导出物料清单
mode: desktop
enabled: true
department: finance

params_input:
  - key: save_path
    label: 保存位置
    type: path
    required: true

steps:
  - type: desktop
    action: start_app
    description: 启动金蝶K/3
    params:
      app_path: "C:/Program Files/Kingdee/K3.exe"
      app_name: "金蝶K/3"
      wait_seconds: 10

  - type: desktop
    action: smart_click
    description: 点击登录按钮
    params:
      intent: 点击登录按钮

  - type: desktop
    action: smart_fill
    description: 填写用户名
    params:
      intent: 用户名输入框
      value: admin

  - type: desktop
    action: smart_export
    description: 导出物料清单
    params:
      intent: 导出当前物料清单为Excel
      save_path: ${save_path}

  - type: data
    action: process_data
    description: 清洗数据
    params:
      module: data_clean.jindie_material
      function: process
```

完整方法清单见 `sdk/desktop_sdk.py` 和 `src/agent/smart_desktop.py`。

---

## 异常自修复（3.0 新增）

任务执行失败时，LLM 自动诊断错误原因并尝试修复重试，无需人工介入。

### 工作流程

```
步骤失败 → 规则匹配（快速）→ 命中 → 按策略重试
                ↓ 未命中
            LLM深度分析 → 给出修复策略 → 重试或上报
```

### 错误分类与处理策略

| 错误类型 | 触发关键字 | 处理策略 |
|---------|-----------|---------|
| 元素找不到 | not found, 找不到, selector | 延长超时×2，重试2次 |
| 超时 | timeout, 超时, timed out | 延长超时×3，指数退避重试3次 |
| 登录过期 | login, cookie, 401 | 清除会话，通知重新登录 |
| 网络错误 | network, connection, ECONN | 指数退避重试3次（10s/20s/40s） |
| 下载失败 | download, 下载 | 重新触发下载，重试2次 |
| 数据处理失败 | KeyError, 列名, column | LLM重新理解数据结构 |
| 权限不足 | permission, 403 | 上报，需人工处理 |

### 相关文件

- src/agent/smart_recovery.py - 异常自修复模块
- src/agent/task_executor.py - 集成自修复的步骤执行循环

### 修复日志

修复记录自动保存到 Redis（`agent:recovery_logs` 列表，保留最近100条），供 Web 端查询。

---

## 数据理解（3.0 新增）

LLM 自动理解数据结构，无需用户预先描述任务。

### 两个核心方法

**1. `understand_data(file_path)` - 自动理解数据结构**

LLM 分析 Excel/CSV 文件，自动识别：
- 每列的业务含义（如"这是金额列"、"这是订单日期"）
- 数据类型（数值/分类/日期/文本/ID）
- 业务主题（销售数据/财务账单/库存清单）
- 数据质量评估（缺失率、异常）
- 处理建议

**2. `detect_anomalies(file_path)` - 异常值检测**

- 统计方法：IQR（四分位距）检测数值列异常值
- LLM 判断：区分业务合理异常（大额订单）和数据错误（录入错误）

### 用法

```python
from src.agent.smart_data_processor import SmartDataProcessor

processor = SmartDataProcessor()

# 自动理解数据
understanding = processor.understand_data("data/downloads/账单.xlsx")
# 返回: {"topic": "财务账单", "columns": [...], "quality": {...}, "suggestions": [...]}

# 检测异常
anomalies = processor.detect_anomalies("data/downloads/账单.xlsx")
# 返回: {"anomalies": [...], "llm_analysis": {...}, "summary": "..."}
```

### 相关文件

- src/agent/smart_data_processor.py - 数据理解增强方法

---

## 数据存储

| 数据类型 | 存储位置 |
|---------|---------|
| 任务配置 | data/tasks/*.yaml |
| 用户账号 | data/auth/users.json |
| Cookie | Redis（30天过期） |
| 业务数据 | MySQL |
| 下载的文件 | data/downloads/ 或用户指定目录 |
| 截图 | data/screenshots/ |
| 任务执行历史 | data/task_history/ |

---

## 部门权限

- 管理员在Web"用户管理"里给同事创建账号、分配部门
- 财务用户只能看财务部任务，业务用户只能看业务部任务
