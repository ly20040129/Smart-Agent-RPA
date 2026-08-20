# -*- coding: utf-8 -*-
# 京东艾贝自营仓销售出库 - API接口版（简化版）
# 直接调用京东后台API获取数据
#
# 运行：python workflows/jd_ibay_self_api.py
# 或通过Web界面触发

import os, sys, asyncio, json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sdk.cookie_manager import cookie_manager

TASK_NAME = "京东艾贝自营仓销售出库(API接口版)"
COOKIE_KEY = "jd_shop_ibay"
API_URL = "https://vcf.jd.com/api/finance/saleBill/list"
PAGE_SIZE = 1000


def _cookies_to_header(cookies):
    """把cookie列表转成HTTP Cookie header字符串"""
    jd_cookies = [c for c in cookies if 'jd.com' in c.get('domain', '')]
    return '; '.join(f"{c['name']}={c['value']}" for c in jd_cookies)


async def _fetch_page(cookie_header, date_from, date_to, page):
    """调用京东API获取一页数据（真异步）"""
    import aiohttp

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookie_header,
        "Referer": "https://vcnew.jd.com/",
        "Origin": "https://vcnew.jd.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    }
    body = json.dumps([{
        "bizType": "4",
        "pageSize": PAGE_SIZE,
        "page": page,
        "refDateFrom": f"{date_from} 00:00:00",
        "refDateTo": f"{date_to} 23:59:59"
    }])

    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, headers=headers, data=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            text = await resp.text()
            result = json.loads(text)

            # 检测cookie过期：京东API通常返回 {"success": false} 或重定向到登录页
            if resp.status == 401 or resp.status == 302 or 'login' in text.lower()[:500]:
                from sdk.cookie_manager import cookie_manager
                cookie_manager.delete(COOKIE_KEY)
                raise RuntimeError(
                    f"京东API返回登录过期，cookie已自动清除。\n"
                    f"请去Web界面 → Cookie管理 → 点击「刷新」按钮重新登录京东。"
                )

            return result, resp.status


async def run_api(date_from=None, date_to=None, progress_callback=None, **kwargs):
    """
    执行API采集任务
    progress_callback(step, message) 用于进度回调
    
    返回: (数据列表, 文件路径)
    """
    # 参数：支持位置参数或kwargs
    date_from = date_from or kwargs.get('date_from', '')
    date_to = date_to or kwargs.get('date_to', '')
    if not date_from or not date_to:
        raise RuntimeError("请提供 date_from 和 date_to 参数")
    
    # 1. 获取cookies（从Redis读取，检查是否有效）
    if not cookie_manager.ensure_valid(COOKIE_KEY):
        raise RuntimeError(
            f"Cookie不存在或已过期（平台: {COOKIE_KEY}）。\n"
            f"请去Web界面 → Cookie管理 → 点击「刷新」按钮重新登录京东。"
        )
    cookies = cookie_manager.load(COOKIE_KEY)
    
    cookie_header = _cookies_to_header(cookies)
    
    if progress_callback:
        progress_callback(1, f"已加载 {len(cookies)} 条cookies")

    # 2. 分页获取数据
    all_data = []
    page = 1
    total = 0

    while True:
        if progress_callback:
            progress_callback(2, f"正在获取第{page}页数据...")
        
        result, status = await _fetch_page(cookie_header, date_from, date_to, page)
        
        if status != 200:
            raise RuntimeError(f"API返回状态码: {status}")

        # 京东API返回: {success: true, data: {list: [...], total: N}}
        if not isinstance(result, dict) or result.get('success') is False:
            raise RuntimeError(f"API返回失败: {json.dumps(result, ensure_ascii=False)[:200]}")

        data = result.get('data', {})
        rows = data.get('list') or data.get('rows') or []
        total = data.get('total', 0)

        if not rows:
            break

        all_data.extend(rows)
        if progress_callback:
            progress_callback(3, f"第{page}页获取 {len(rows)} 条，累计 {len(all_data)} 条/共 {total}")

        if len(all_data) >= total or len(rows) < PAGE_SIZE:
            break

        page += 1
        await asyncio.sleep(2)  # 防风控

    if not all_data:
        raise RuntimeError("没有获取到数据")

    # 3. 保存到Excel
    import pandas as pd
    from datetime import datetime
    
    if progress_callback:
        progress_callback(4, f"正在保存 {len(all_data)} 条数据...")

    df = pd.DataFrame(all_data)
    # 支持从kwargs获取输出目录（用户运行时选择的保存位置）
    out_dir = kwargs.get('output_dir', '')
    if not out_dir:
        out_dir = str(Path(r"E:\smart_agent_platform\data\downloads"))
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True, parents=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"{TASK_NAME}_{today}.xlsx"
    df.to_excel(str(out_file), index=False)

    if progress_callback:
        progress_callback(5, f"✅ 完成！已保存到: {out_file}")

    return all_data, str(out_file)


async def main():
    print(f"程序开始：{TASK_NAME}")
    
    # 获取cookies
    cookies = cookie_manager.load(COOKIE_KEY)
    if not cookies:
        print("❌ Redis中没有找到cookies，请先用浏览器方式登录一次")
        return
    
    print(f"✅ 已加载cookies: {len(cookies)}条")
    
    date_from = input("请输入开始日期(YYYY-MM-DD): ").strip() or "2026-07-21"
    date_to = input("请输入结束日期(YYYY-MM-DD): ").strip() or "2026-07-31"
    print(f"查询日期范围: {date_from} ~ {date_to}")
    
    try:
        data, file_path = await run_api(date_from, date_to)
        print(f"\n✅ 获取完成: {len(data)} 条数据")
        print(f"   表头: {list(data[0].keys()) if data else []}")
        print(f"   已保存到: {file_path}")
    except Exception as e:
        print(f"❌ 执行失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
