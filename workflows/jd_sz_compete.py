# -*- coding: utf-8 -*-
"""
京东商智竞品数据统计（API型，影刀迁移）
"""
import re
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import pymysql
import pandas as pd
from loguru import logger
import workflows  # noqa: F401 — 自动设置项目根路径
from sdk.browser_sdk import Browser
from sdk.jd import web_api
from sdk.mysql_sdk import MySQL
from sdk.entities import init_entities, get_entity
from sdk.dingtalk_robot import build_robot
from src.core.config import get_config
from sdk.shop_account import get_shop_account

init_entities()

# ============ 配置 ============
COOKIE_KEY = "jd_shangzhi"
SHOP_ACCOUNT = "泳宇-数字人"

# TEMPLATE = Path(r"D:\ly\京东商智竞品数据统计\每日9730销量统计表-最新.xlsx")

DING_USERIDS = ["1783298686946923"]

def get_sms_code() -> str:
    """轮询短信"""

    cfg = get_config().config_data["mysql_pro"]

    start = datetime.now()
    for _ in range(20):
        begin = (start - timedelta(seconds=20)).strftime('%Y-%m-%d %H:%M:%S')
        end = (start + timedelta(seconds=60)).strftime('%Y-%m-%d %H:%M:%S')
        conn = pymysql.connect(
            host=cfg["host"], port=int(cfg["port"]),
            user=cfg["user"], password=cfg["password"],
            database=cfg["database"], charset=cfg.get("charset", "utf8mb4"),
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT payload, raw_body FROM webhook_inbox
                    WHERE received_at >= %s AND received_at <= %s
                      AND (payload LIKE '%%京东%%验证码%%' OR raw_body LIKE '%%京东%%验证码%%')
                    ORDER BY received_at DESC LIMIT 1
                """, (begin, end))
                row = cur.fetchone()
                if row:
                    m = re.search(r'验证码[：:]\s*(\d{6})',
                                  str(row.get('payload') or row.get('raw_body') or ''))
                    if m:
                        return m.group(1)
        finally:
            conn.close()
        time.sleep(2)
    raise RuntimeError("限定时间内未收到京东短信验证码")


async def login():
    """登录"""
    agent = Browser(cookie_key=COOKIE_KEY)
    acc = get_shop_account(SHOP_ACCOUNT)
    await agent.start()
    await agent.goto(
        "https://passport.shop.jd.com/login/index.action/jdm"
        "?ReturnUrl=https%3A%2F%2Fware.shop.jd.com%2Frest%2Fshop%2Fware%2Fnavigation"
    )

    await agent.type_text("input#loginname", acc["shop_account_username"], delay=300)
    await agent.type_text("input[placeholder='请输入登录密码']", acc["shop_account_password"], delay=300)
    await agent.click_by_selector("button.password__submit")
    await agent.sleep(3)

    # sms
    if await agent.is_visible("a.jdyverify-mobile", timeout=3000):
        logger.info("[Login] 需要短信验证码")
        await agent.click_by_selector("a.jdyverify-mobile")
        await agent.click_by_selector("a.sendMobileCode")
        code = await asyncio.to_thread(get_sms_code)
        await agent.type_text("input.jdyverify-mobilecode", code, delay=100)
        await agent.click_by_selector("button.jdyverify-btn")
        await agent.sleep(5)

    await agent.sleep(2)
    await agent.close()


def rank(item, i) -> str:
    """取数据项第i位的排名值，'12.0'→'12'，取不到给空串"""
    try:
        if len(item) > i and item[i]:
            return re.sub(r'\.0', '', str(item[i].get('range', '')))
    except Exception:
        pass
    return ""


def fill_template(date_str: str, sku_index: dict, excel_path: Path) -> tuple:
    """按SKU匹配填模板表格，返回 (输出文件路径, 记录列表)"""
    df = pd.read_excel(excel_path, header=None)
    records = []
    total = 0
    for idx in range(2, len(df)):
        sku_val = df.iloc[idx, 2]
        if pd.isna(sku_val) or not str(sku_val).strip():
            continue
        total += 1
        item = sku_index.get(re.sub(r'\D', '', str(sku_val)))
        if not item:
            logger.warning(f"[Match] 未命中: {sku_val}")
            continue
        r4, r6 = rank(item, 4), rank(item, 6)
        df.iloc[idx, 5] = r4
        df.iloc[idx, 6] = r6
        records.append({"stat_date": date_str, "sku": re.sub(r'\D', '', str(sku_val)),
                        "rank_4": r4, "rank_6": r6,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    out_file = excel_path.parent / f"每日9730销量统计表_{date_str}.xlsx"
    df.to_excel(out_file, index=False, header=False)
    logger.info(f"[Excel] 命中 {len(records)}/{total} -> {out_file}")
    return out_file, records


async def run(user_params: dict) -> dict:
    """主流程"""
    date_str = user_params.get("date") or \
        (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    excel_path = user_params.get("excel_path")
    excel_path = Path(excel_path)
    if not excel_path.exists():
        return {"status": "failed", "error": f"文件不存在: {excel_path}"}
    
    # 调用登录
    await login()

    #  API请求
    result = await web_api(
        "https://sz.jd.com/sz/api/competitionAnalysis/getCompeteProDetail.ajax?date=" + date_str + "&dateType=day&endDate=" + date_str + "&startDate=" + date_str + "&indChannel=99&unitType=1",
        {
            "headers": {
                "accept": "application/json, text/plain, */*",
                "Referer": "https://sz.jd.com/sz/view/competitionAnalysis/competePros.html",
                "user-mnp": "03b3610913a34f11b6b36b310a91a937",   
                "user-mup": "1786348233859",
                "uuid": "72d2684b74dbf22e9763-19feaa6e483",
                "x-requested-with": "XMLHttpRequest",
            },
            "body": None,
            "method": "GET"
        },
        cookie_key=COOKIE_KEY,
    )
    if result.get("status") != "0":
        return {"status": "failed", "error": f"商智接口异常: {str(result)[:200]}"}
    data_list = result.get("content", {}).get("data", [])
    if not data_list:
        return {"status": "failed", "error": f"{date_str} 无竞品数据"}

    sku_index = {re.sub(r'\D', '', str(it[1])): it
                 for it in data_list if len(it) > 1}
    logger.info(f"[API] 返回 {len(sku_index)} 个SKU")

    # 按SKU匹配填模板表格
    out_file, records = fill_template(date_str, sku_index,excel_path)

    # 存MySQL
    saved = MySQL.save(
        pd.DataFrame(records), 
        table=get_entity("jd_sz_compete")
        )
    logger.info(f"[MySQL] 入库 {saved} 行")

    # 钉钉发文件
    robot = build_robot()
    if not robot.enabled:
        return {"status": "failed", "error": "单聊机器人未配置(delivery.dingtalk)"}
    for uid in DING_USERIDS:
        res = robot.send_file(str(out_file), uid)
        if not res.get("success"):
            return {"status": "failed", "error": f"钉钉发送失败 {uid}: {res.get('error')}"}
        logger.info(f"[Ding] 已发送: {uid}")

    return {"status": "success",
            "message": f"{date_str} 统计完成，命中 {len(records)} 条，入库 {saved} 行",
            "matched": len(records), "saved_rows": saved}
