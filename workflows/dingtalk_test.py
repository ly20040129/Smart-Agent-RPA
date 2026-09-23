# -*- coding: utf-8 -*-
"""
钉钉测试 workflow

生成 Excel 并按 single/group 模式发送到钉钉。
"""
from datetime import datetime

import workflows  # noqa: F401 — 自动设置项目根路径

import pandas as pd
from loguru import logger

from sdk.delivery import DeliveryService


async def test_send_file(user_params: dict) -> dict:
    """生成测试 Excel 并发送到钉钉。

    send_mode=single 走单聊，group 走群聊。本 workflow 自己完成发送，
    因此不返回 output_file，避免编排层重复交付。
    """
    send_mode = (user_params.get("send_mode") or "single").strip().lower()
    userid = (user_params.get("dingtalk_userid") or "").strip()
    open_conversation_id = (user_params.get("open_conversation_id") or "").strip()
    robot_code = (user_params.get("robot_code") or "").strip()

    if send_mode == "group":
        if not open_conversation_id:
            return {"status": "failed", "error": "缺少 open_conversation_id"}
        if not robot_code:
            return {"status": "failed", "error": "缺少 robot_code"}
    elif not userid:
        return {"status": "failed", "error": "缺少 dingtalk_userid"}

    # 生成测试 Excel
    out_dir = workflows._ROOT / "data" / "output" / "钉钉测试"
    out_dir.mkdir(parents=True, exist_ok=True)
    file = out_dir / f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    pd.DataFrame({
        "序号": [1, 2, 3], "商品": ["A", "B", "C"], "时间": [datetime.now()] * 3,
    }).to_excel(str(file), index=False)
    logger.info(f"生成文件: {file}")

    # 按模式发送
    if send_mode == "group":
        from sdk.dingtalk_robot import build_robot
        res = build_robot().send_group_file(
            file_path=str(file), open_conversation_id=open_conversation_id, robot_code=robot_code)
    else:
        res = await DeliveryService().deliver(
            file_path=str(file), user_config={}, task_name="钉钉测试",
            channels=["dingtalk"], dingtalk_userid=userid)

    return {"status": "success", "file": str(file), "result": res}


async def test_send_webhook(user_params: dict) -> dict:
    """钉钉【群聊 Webhook 机器人】测试：把 message 文本发到群里。

    data/tasks/test_webhook.yaml 指向本函数；webhook 与 secret 从
    config.yaml 的 notifications.dingtalk 读取。
    """
    from sdk.dingtalk_webhook import build_webhook

    message = (user_params.get("message") or "").strip()
    if not message:
        return {"status": "failed", "error": "缺少 message"}

    res = build_webhook().send_text(message)
    if not res.get("success"):
        return {"status": "failed", "error": res.get("error") or "Webhook 发送失败"}
    return {"status": "success", "message": message}
