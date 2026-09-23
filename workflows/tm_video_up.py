import os
import asyncio
from ftplib import FTP
from loguru import logger
from sdk.browser_sdk import Browser
from sdk.dingtalk_ai_table import DingTalkAITable
from sdk.shop_account import get_shop_account
from src.core.config import get_config

_browser_agent = None   #全局函数
COOKIE_KEY="tm_video_up"

SHOP_ACCOUNT = "伟彩嘉木专卖店:数据"

ftp_config = get_config().config_data.get("ftp")

AITable_config = {
    "operator_id":"1783298686946923",
    "base_id":"lyQod3RxJK36qrYYIlLPzkgnJkb4Mw9r",
    "sheet_name":"数据表"
}

local_path = "D:\\"

filed_map={
    "ftp_path": "视频文件NAS绝对地址",
    "video_txt": "视频描述文本",
    "topic_Tags": "内容标签",
    "Topic": "话题",
    "shop_id": "商品ID"
}

def ftp_download(local_dir: str, ftp_path: str, ftp_config: dict) -> str:
    """从 FTP 下载视频到本地目录，返回本地文件完整路径（阻塞操作，调用处用 to_thread 执行）"""

    if ftp_path.startswith("/vol1/@team/"):
        ftp_path = ftp_path.replace("/vol1/@team/", "/团队文件-", 1)

    os.makedirs(local_dir, exist_ok=True)
    parts = ftp_path.strip("/").split("/")
    filename = parts[-1]
    file_path = os.path.join(local_dir, filename)

    ftp = FTP()
    try:
        ftp.connect(ftp_config["host"], ftp_config["port"], timeout=10)
        ftp.login(ftp_config["user"], ftp_config["password"])
        ftp.encoding = "utf-8"
        ftp.set_pasv(True)

        # 切换到目标目录
        for part in parts[:-1]:
            ftp.cwd(part)

        # 下载文件
        with open(file_path, 'wb') as f:
            ftp.retrbinary(f'RETR {filename}', f.write)
    finally:
        #无论成功失败都断开连接，避免连接泄漏
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    logger.info(f"[FTP] 已下载: {file_path}")
    return file_path

async def read_and_update(sheet_name: str, base_id: str, filter_conditions: dict=None,update_fields: dict=None,max_records: int=20) -> list:
    """读取指定记录并更新字段"""
    table = DingTalkAITable(
        operator_id=AITable_config["operator_id"],
    )
    # 读
    result = table.list_records(
        base_id=base_id, 
        sheet_name=sheet_name, 
        filter_conditions=filter_conditions, 
        max_records=max_records
        )
    records = result.get("records", [])
    logger.info(f"[AITable] 读取到 {len(records)} 条记录")

    # 改
    if update_fields and records:
        table.update_records(
            base_id=base_id,
            sheet_name=sheet_name,
            records=[{"id": rec["id"], "fields": update_fields} for rec in records]
        )
    return records

async def login(user_params: dict = None):
    global _browser_agent
    acc = get_shop_account(SHOP_ACCOUNT)
    agent = Browser(cookie_key=COOKIE_KEY)
    await agent.start()
    await agent.goto("https://creator.guanghe.taobao.com/page/unify/creation-tool/batch-publish")
    await agent.sleep(5)

    # 检查是否已登录
    is_logged_in = await agent.is_visible("div.upload-clip--pnNVlbki", timeout=3000)
    if is_logged_in:
        logger.info("[Browser] 已登录，跳过登录流程")
        _browser_agent = agent
        return {"status": "success", "already_logged_in": True}

    # 未登录，执行登录流程
    logger.info("[Browser] 未登录，开始登录...")
    await agent.type_text("input[name='fm-login-id']", acc["shop_account_username"], delay=300)
    await agent.type_text("input[name='fm-login-password']", acc["shop_account_password"], delay=300)
    await agent.check("input[type='checkbox']")
    await agent.click_by_selector("button[type='submit'].fm-submit")

    await agent.sleep(30)
    _browser_agent = agent
    return {"status": "success"}


async def tm_video_upload(user_params: dict) -> dict:
    """天猫视频上传主流程"""

    records = await read_and_update(
        sheet_name=AITable_config["sheet_name"],
        base_id=AITable_config["base_id"],
        filter_conditions={
            "conditions": [{
                "field": "处理状态",
                "operator": "equal",
                "value": ["待上传"]
            }]
        }
    )

    if not records:
        logger.info("[AITable] 没有待上传的记录")
        return {"code": 0, "message": "无待处理记录", "data": {}}

    success_count = 0
    await login() #调用login

    for rec in records:
        fields = rec["fields"]
        record_id = rec["id"]

        ftp_path = fields.get(filed_map["ftp_path"])
        video_txt = fields.get(filed_map["video_txt"])
        topic_Tags = fields.get(filed_map["topic_Tags"])
        Topic = fields.get(filed_map["Topic"])
        shop_id = fields.get(filed_map["shop_id"])
        local_dir = user_params.get("local_path", local_path)

        #下载
        downloaded_path = await asyncio.to_thread(ftp_download, local_dir, ftp_path, ftp_config)
        logger.info(f"[Upload] 本地文件: {downloaded_path}")

        agent = _browser_agent

        #上传
        try:
            #上传文件
            file_input_selector = "div.next-upload-inner input[type='file']"
            await agent.upload_file(file_input_selector, downloaded_path)
            logger.info(f"[Upload] 文件已填入: {downloaded_path}")
        
            # 切到 iframe
            page = await agent._get_page()
            frame = page.frame_locator("iframe.publish-content--Cl3CtTGD")
        
            # 等待上传完成
            await frame.locator("div:has-text('已上传')").first.wait_for(timeout=30000)
            logger.info("[Upload] 视频上传完成")
            # 填写视频标题
            await frame.locator("input[placeholder='加个标题让内容更吸引人']").fill(video_txt)
            logger.info(f"[Meta] 标题已填: {video_txt}")
    
            # 填写描述（富文本）
            await frame.locator("div.rich-text-content").click()
            await agent.sleep(0.5)
            # 三击全选该元素内所有文本
            await frame.locator("div.rich-text-content").click(click_count=3)
            await agent.sleep(0.5)
            await page.keyboard.press("Backspace")
            await agent.sleep(0.5)
    
            # 逐个输入标签，触发联想变成有效标签
            tags = topic_Tags.split("#")
            tags = [t for t in tags if t.strip()]
            for tag in tags:
                await page.keyboard.type(f"#{tag}", delay=200)
                await agent.sleep(2)
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
                await agent.sleep(1)
    
            logger.info("[Meta] 描述标签已填")
    
            # 添加 Topic
            await frame.locator("div.publish-content__topic-v2--select_left--35kmJN8").click()
            await agent.sleep(2)
            await frame.locator("input[aria-label='输入关键词搜索']").fill(Topic)
            await agent.sleep(1)
    
            # 点击搜索按钮
            await frame.locator("button.next-btn-primary:has-text('搜索')").click()
            await agent.sleep(2)
    
            # 选搜索结果中的第一个话题
            await frame.locator(f"div[data-autolog*='text=可选话题:{Topic}']").first.click()
            await agent.sleep(1)
    
            # 点确认
            await frame.locator("button.next-btn-primary:has-text('确认提交')").click()
            await agent.sleep(2)
            logger.info(f"[Meta] Topic 已选: {Topic}")
    
            # 添加商品
            await frame.locator("div.publish-content__item-v2--items-trigger--2iz-IUO").click()
            await agent.sleep(2)
            await frame.locator("input[aria-label='搜索']").fill(shop_id)
            await agent.sleep(1)
            await frame.locator("i.next-icon-search").click()
            await agent.sleep(2)
            await frame.locator("label.next-checkbox-wrapper").first.click()
            await agent.sleep(1)
            await frame.locator("button.next-btn-primary span.next-btn-helper").click()
            await agent.sleep(2)
            logger.info(f"[Meta] 商品已选: {shop_id}")
    
            await frame.locator("span.next-radio-label:has-text('内容无需标注')").click()
            await agent.sleep(1)
            logger.info("[Meta] 已选择内容无需标注")
    
            # 点击批量发布
            await frame.locator("button.next-btn-primary:has-text('批量发布')").click()
            await agent.sleep(5)
            logger.info("[Upload] 批量发布已点击")

            table = DingTalkAITable(operator_id=AITable_config["operator_id"])
            table.update_records(
                base_id=AITable_config["base_id"],
                sheet_name=AITable_config["sheet_name"],
                records=[{"id": record_id, "fields": {"处理状态": "已上传"}}]
            )

            success_count += 1

        except Exception as e:
            logger.error(f"[Upload] 记录{record_id} 上传失败: {e}")
            # 留下错误现场截图，服务器无头部署时排障靠它
            try:
                await agent.screenshot(f"tm_error_{record_id}")
            except Exception:
                pass
            table = DingTalkAITable(operator_id=AITable_config["operator_id"])
            table.update_records(
                base_id=AITable_config["base_id"],
                sheet_name=AITable_config["sheet_name"],
                records=[{"id": record_id, "fields": {"处理状态": "上传失败"}}]
            )
        finally:
            # 不关浏览器，下一条继续用；最后再关
            pass

    await _browser_agent.close()
    return {"status": "success", "message": f"已处理 {len(records)} 条记录，成功上传 {success_count} 条"}
