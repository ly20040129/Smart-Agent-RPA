# -*- coding: utf-8 -*-
# 京东艾贝自营仓销售出库自动化任务（浏览器方案）
# 使用复制粘贴方式获取表格数据，绕过ant-design复杂DOM结构
#
# 运行：python workflows/jd_ibay_self.py

import os, sys, asyncio
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sdk import Browser, LocalConfig
from entity_class import JdSalesModel, DailyFinanceReport

# ====== 任务配置 ======
TASK_NAME = "京东艾贝自营仓销售出库正式"
COOKIE_KEY = "jd_shop_ibay"
LOGIN_URL = "https://shop.jd.com/jdm/home"

CURRENT_USER = os.environ.get("SMART_AGENT_USER", "admin")
EXCEL_TEMPLATE = LocalConfig.get_path_for_user(CURRENT_USER, "templates.finance.jd_sales_template")


async def run(date_from=None, date_to=None, output_dir=None, progress_callback=None, **kwargs):
    """
    供 task_executor 调用的入口函数（浏览器方案）

    Args:
        date_from: 开始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        output_dir: 输出目录路径
        progress_callback: 可选的进度回调 callback(step, message)
    
    Returns:
        (table_data, out_file) 元组
    """
    if not date_from:
        date_from = kwargs.get('date_from', '')
    if not date_to:
        date_to = kwargs.get('date_to', '')
    if not date_from or not date_to:
        raise RuntimeError("请提供 date_from 和 date_to 参数")

    def log(step, msg):
        print(f"[{step}] {msg}")
        if progress_callback:
            progress_callback(step, msg)

    log(1, f"开始执行：{TASK_NAME}，日期范围 {date_from} ~ {date_to}")

    async with Browser(cookie_key=COOKIE_KEY, headless=False) as b:
        await b.open(LOGIN_URL)

        if not b._cookies_restored:
            log(1, "首次登录请先手动登录，完成登录之后回车，会自动保存cookies到redis")
            await b.wait_login("首次登录请先尝试手动登录，完成登录之后回车，会自动保存cookies到redis")

        await b.wait("页面成功进入后台")

        # 导航到实销实结明细页面
        log(2, "导航到实销实结明细页面")
        await b.open("https://vcnew.jd.com/finance/actualSalesSolidDetails")
        await asyncio.sleep(3)
        await b.wait("页面显示实销实结明细列表或者业务日期筛选框")

        # 自动填写日期：先通过JS直接改 value + 触发 React input 事件，
        # 再用 keyboard 做一次逐字符兜底（ant-design 是受控组件，必须触发 onChange）
        log(3, f"填写日期范围: {date_from} ~ {date_to}")
        try:
            page = b._sb.browser.page
            # ant-design RangePicker 有2个input，第一个开始日期，第二个结束日期
            # 关键：ant-design 是 React 受控组件，直接改 DOM value 不生效，
            # 必须先获取 React 的内部 state setter，或通过原生 value setter + dispatchEvent 触发 onChange
            js_set_date = """(idx, dateStr) => {
                // 1. 找到可见的 input
                var inputs = document.querySelectorAll('.ant-picker-input input');
                if (inputs.length === 0) {
                    inputs = document.querySelectorAll('.ant-picker input');
                }
                inputs = Array.from(inputs).filter(i => i.offsetParent !== null);
                if (inputs.length <= idx) {
                    return 'fail: found ' + inputs.length + ' visible inputs, idx=' + idx;
                }
                var input = inputs[idx];

                // 2. 聚焦
                input.focus();

                // 3. 用原生 descriptor 设 value（绕过 React 的拦截）
                try {
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeInputValueSetter.call(input, dateStr);
                } catch(e) {
                    // 兜底：直接赋值
                    input.value = dateStr;
                }

                // 4. 触发 React 需要的事件（input + change），让受控组件更新 state
                var ev1 = new Event('input', { bubbles: true });
                input.dispatchEvent(ev1);
                var ev2 = new Event('change', { bubbles: true });
                input.dispatchEvent(ev2);

                // 5. 再 select 一次，确保后续键盘输入能整体替换
                try { input.select(); } catch(e2){}

                return 'ok: set idx=' + idx + ' to ' + dateStr;
            }"""

            # 填开始日期
            log(3, "填入开始日期: " + date_from)
            r1 = await page.evaluate(js_set_date, 0, date_from)
            log(3, f"  set结果: {r1}")
            # 兜底：再逐字符输入一次（React 已更新 state 后不影响；如果 JS 方式没生效则补上）
            await asyncio.sleep(0.3)
            await page.keyboard.type(date_from, delay=50)
            await asyncio.sleep(0.5)
            await page.keyboard.press('Enter')
            await asyncio.sleep(1)

            # 填结束日期
            log(3, "填入结束日期: " + date_to)
            r2 = await page.evaluate(js_set_date, 1, date_to)
            log(3, f"  set结果: {r2}")
            await asyncio.sleep(0.3)
            await page.keyboard.type(date_to, delay=50)
            await asyncio.sleep(0.5)
            await page.keyboard.press('Enter')
            await asyncio.sleep(1)

            log(3, "日期填写完成")
        except Exception as e:
            log(3, f"自动填日期失败({e})，请手动在页面上选择日期范围")
            input("请在页面上选好日期后按回车继续...")

        # 点击查询
        log(4, "点击查询按钮")
        await b.click("点击查询按钮，按钮上显示'查 询'字样")
        await b.wait("页面显示实销实结明细表格数据，有多行数据行")

        # 设置分页到1000条/页
        log(5, "设置分页为1000条/页")
        await b.set_page_size(1000)
        await asyncio.sleep(5)

        # 滚动加载所有数据
        log(6, "滚动加载数据")
        await b.scroll_to_bottom(times=10, wait=1.0)
        await asyncio.sleep(2)
        await b.scroll_to_bottom(times=3, wait=0.5)

        # 用复制粘贴方式提取表格
        log(7, "提取表格数据")
        table_data = await b.extract_table(start_col_name="单据类型")

        if not table_data:
            await b.screenshot("table_empty_debug")
            raise RuntimeError("没有提取到表格数据")

        log(8, f"提取到 {len(table_data)} 行数据")

    # 保存到Excel
    import pandas as pd
    from datetime import datetime

    df = pd.DataFrame(table_data)
    # 输出目录：优先用用户传的，否则用默认
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = Path(r"E:\smart_agent_platform\data\downloads")
    out_dir.mkdir(exist_ok=True, parents=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"{TASK_NAME}_{today}.xlsx"
    df.to_excel(str(out_file), index=False)
    log(9, f"已保存到: {out_file}（共 {len(df)} 行 x {len(df.columns)} 列）")

    return table_data, str(out_file)


async def main():
    print(f"程序开始：{TASK_NAME}")

    async with Browser(cookie_key=COOKIE_KEY, headless=False) as b:
        await b.open(LOGIN_URL)

        if not b._cookies_restored:
            await b.wait_login("首次登录请先尝试手动登录，完成登录之后回车，会自动保存cookies到redis")

        await b.wait("页面成功进入后台")

        # 导航到实销实结明细页面
        await b.open("https://vcnew.jd.com/finance/actualSalesSolidDetails")
        await asyncio.sleep(3)
        await b.wait("页面显示实销实结明细列表或者业务日期筛选框")

        # 用户手动选择日期
        print("\n请在页面上选择日期范围，选好后回到控制台按回车...")
        input()

        # 点击查询
        await b.click("点击查询按钮，按钮上显示'查 询'字样")
        await b.wait("页面显示实销实结明细表格数据，有多行数据行")

        # 设置分页到1000条/页
        await b.set_page_size(1000)
        print("等待数据加载...")
        await asyncio.sleep(5)

        # 滚动加载所有数据
        print("滚动加载数据...")
        await b.scroll_to_bottom(times=10, wait=1.0)
        await asyncio.sleep(2)
        await b.scroll_to_bottom(times=3, wait=0.5)

        # 用复制粘贴方式提取表格
        table_data = await b.extract_table(start_col_name="单据类型")

        if not table_data:
            print("❌ 没提取到表格数据")
            await b.screenshot("table_empty_debug")
            return

        print(f"\n✅ 提取到 {len(table_data)} 行数据")
        print(f"   表头: {list(table_data[0].keys())}")

    # 保存到Excel
    import pandas as pd
    from datetime import datetime

    df = pd.DataFrame(table_data)
    out_dir = Path(r"C:\Users\31557\Desktop")
    out_dir.mkdir(exist_ok=True, parents=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"{TASK_NAME}_{today}.xlsx"
    df.to_excel(str(out_file), index=False)
    print(f"\n✅ 已保存到: {out_file}")
    print(f"   共 {len(df)} 行 x {len(df.columns)} 列")


if __name__ == "__main__":
    asyncio.run(main())
