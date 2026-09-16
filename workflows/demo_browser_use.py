# -*- coding: utf-8 -*-
"""
browser-use 装饰器 demo —— 照着抄就能写浏览器任务

三种写法（从简单到灵活），选最顺手的用：
  1. @browser_task   单步任务
  2. @browser_flow   多步链式
  3. BrowserSession  上下文管理器（最灵活）
"""
from src.tools.browser_decorator import browser_task, browser_flow, BrowserSession


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  写法1：@browser_task  —— 一句话就是一个浏览器任务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@browser_task(
    task="打开百度，搜索'今天北京天气'，把搜索结果的第一条标题返回给我",
    initial_url="https://www.baidu.com",
)
async def search_weather(result=None):
    """搜索天气 demo"""
    print(f"AI搜索结果: {result}")
    return {"status": "success", "weather": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  写法2：@browser_flow  —— 多步链式，同一浏览器会话
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@browser_flow(
    initial_url="https://www.baidu.com",
    steps=[
        "打开百度首页",
        "搜索关键词'京东'，点击第一个搜索结果进入京东首页",
        "在京东首页搜索框输入'惠普A4纸'并搜索",
        "获取搜索结果中第一个商品的价格",
    ],
)
async def search_jd_price(results=None):
    """京东搜价格 demo"""
    # results[0] = 第一步结果
    # results[1] = 第二步结果
    # results[3] = 最后一步（价格信息）
    price = results[-1] if results else "无结果"
    print(f"京东价格: {price}")
    return {"status": "success", "price": price}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  写法3：BrowserSession  —— 上下文管理器，最灵活
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def complex_search():
    """
    复杂流程 demo：带分支判断

    和前两种写法的区别：
    - @browser_task / @browser_flow：步骤固定，写死在装饰器里
    - BrowserSession：可以在中间写 if/for/while，动态决定下一步做什么
    """
    async with BrowserSession(
        cookie_domain="baidu.com",
        initial_url="https://www.baidu.com",
    ) as session:
        # 第1步：搜索
        await session.do("搜索'北京天气'")

        # 第2步：获取结果
        data = await session.get("把页面上第一条搜索结果的标题和摘要返回给我")

        # 第3步：根据结果判断下一步
        if "下雨" in str(data):
            await session.do("搜索'北京雨伞推荐'")
        elif "晴天" in str(data):
            await session.do("搜索'北京防晒霜推荐'")

        # 最终结果
        final = await session.get("返回当前页面的主要内容")
        return {"status": "success", "weather_info": data, "final_page": final}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  实际任务示例：京东价格统计（替代 Playwright 手写选择器）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@browser_flow(
    initial_url="https://www.jd.com",
    cookie_domain="jd.com",
    steps=[
        "如果需要登录就先登录京东（会弹出验证码就等用户手动处理）",
        "在搜索框输入'{sku_name}'并搜索",
        "获取搜索结果中第一个商品的名称和价格",
        "把商品名称和价格以 JSON 格式返回，如 {{\"name\": \"...\", \"price\": \"...\"}}",
    ],
)
async def fetch_jd_price(results=None, **kwargs):
    """
    获取京东商品价格（替代原来的 Playwright 手写选择器）

    和原来 jd_price_stats.py 的区别：
    - 原来：page.goto(url) → page.locator(".price").text → 页面改版就崩
    - 现在：AI 自己找价格元素，页面改版也能适应
    """
    import json
    try:
        last = results[-1] if results else "{}"
        # 尝试解析 AI 返回的 JSON
        data = json.loads(last) if isinstance(last, str) else last
        return {"status": "success", "data": data}
    except Exception:
        return {"status": "success", "raw": results}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  测试入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import sys

    async def main():
        print("=" * 50)
        print("browser-use 装饰器 demo")
        print("=" * 50)

        # 选一个 demo 跑（改数字就行）
        choice = sys.argv[1] if len(sys.argv) > 1 else "1"

        if choice == "1":
            print("\n▶ 运行: @browser_task 搜索天气")
            result = await search_weather()
            print(f"结果: {result}")

        elif choice == "2":
            print("\n▶ 运行: @browser_flow 京东搜价格")
            result = await search_jd_price()
            print(f"结果: {result}")

        elif choice == "3":
            print("\n▶ 运行: BrowserSession 复杂搜索")
            result = await complex_search()
            print(f"结果: {result}")

        else:
            print(f"用法: python {sys.argv[0]} [1|2|3]")
            print("  1 = @browser_task 单步任务")
            print("  2 = @browser_flow 多步链式")
            print("  3 = BrowserSession 上下文管理器")

    asyncio.run(main())
