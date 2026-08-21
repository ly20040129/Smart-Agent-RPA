# -*- coding: utf-8 -*-
# 京东艾贝自营仓销售出库 - API接口版，cookie从Redis自动读取

import sys, asyncio, json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sdk.platforms import init_platforms, get_platform
from sdk.entities import init_entities, get_entity
from sdk.mysql_sdk import MySQL

# 初始化注册
init_platforms()
init_entities()

# 获取京东平台工具类和实体类
jd = get_platform("jd")
entity = get_entity("jd_ibay_sales")

TASK_NAME = "京东艾贝自营仓销售出库(API接口版)"
COOKIE_KEY = entity.cookie_key  # "jd_shop_ibay"
API_URL = "https://vcf.jd.com/api/finance/saleBill/list"


async def run_api(date_from=None, date_to=None, progress_callback=None, **kwargs):
    """
    执行API采集任务（非官方网页API版）

    调用 jd.fetch_paged() → 内部走 jd.web_api()（非官方接口，cookie认证）
    cookie管理、失效检测、自动刷新由JDPlatform.web_api()处理，
    不再需要手动转换cookie格式和检测失效。

    如该接口有官方开放平台版本，可改用 jd.official_api()（无需cookie）。

    progress_callback(step, message) 用于进度回调
    返回: (数据列表, 文件路径)
    """
    date_from = date_from or kwargs.get('date_from', '')
    date_to = date_to or kwargs.get('date_to', '')
    if not date_from or not date_to:
        raise RuntimeError("请提供 date_from 和 date_to 参数")

    # 1. 检查cookie是否有效（平台工具类）
    if not jd.is_cookie_valid(COOKIE_KEY):
        raise RuntimeError(
            f"Cookie不存在或已过期（平台: {COOKIE_KEY}）。\n"
            f"请去Web界面 → Cookie管理 → 点击「刷新」按钮重新登录京东。"
        )

    if progress_callback:
        progress_callback(1, f"Cookie已加载（{COOKIE_KEY}）")

    # 2. 分页获取数据（平台工具类的fetch_paged自动处理cookie注入+失效检测+刷新重试）
    all_data = await jd.fetch_paged(
        url=API_URL,
        cookie_key=COOKIE_KEY,
        body_template={"bizType": "4"},
        date_from=date_from,
        date_to=date_to,
        page_size=1000,
        progress_callback=progress_callback,
    )

    if not all_data:
        raise RuntimeError("没有获取到数据")

    if progress_callback:
        progress_callback(4, f"正在保存 {len(all_data)} 条数据...")

    # 3. 保存到Excel
    import pandas as pd
    from datetime import datetime

    df = pd.DataFrame(all_data)
    out_dir = kwargs.get('output_dir', '')
    if not out_dir:
        out_dir = str(Path(r"E:\smart_agent_platform\data\downloads"))
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True, parents=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"{TASK_NAME}_{today}.xlsx"
    df.to_excel(str(out_file), index=False)

    # 4. 同时存到MySQL（实体类指定表名，自动建表）
    try:
        MySQL.save(str(out_file), table=entity)
    except Exception as e:
        print(f"[MySQL] 存储失败（不影响Excel）: {e}")

    if progress_callback:
        progress_callback(5, f"完成！已保存到: {out_file}")

    return all_data, str(out_file)


async def main():
    print(f"程序开始：{TASK_NAME}")

    if not jd.is_cookie_valid(COOKIE_KEY):
        print("❌ Redis中没有找到有效cookies，请先去Web界面刷新Cookie")
        return

    print(f"Cookie有效（{COOKIE_KEY}）")

    date_from = input("请输入开始日期(YYYY-MM-DD): ").strip() or "2026-07-21"
    date_to = input("请输入结束日期(YYYY-MM-DD): ").strip() or "2026-07-31"
    print(f"查询日期范围: {date_from} ~ {date_to}")

    try:
        data, file_path = await run_api(date_from, date_to)
        print(f"获取完成: {len(data)} 条数据")
        print(f"   表头: {list(data[0].keys()) if data else []}")
        print(f"   已保存到: {file_path}")
    except Exception as e:
        print(f"执行失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
