# -*- coding: utf-8 -*-
"""钉钉测试 workflow：生成 Excel，并按 single/group 模式发送。"""
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agent.delivery_service import DeliveryService
from loguru import logger


async def test_send_file(**kwargs):
    send_mode = (kwargs.get("send_mode") or "single").strip().lower()
    userid = (kwargs.get("dingtalk_userid") or "").strip()
    open_conversation_id = (kwargs.get("open_conversation_id") or "").strip()
    robot_code = (kwargs.get("robot_code") or "").strip()
    if send_mode == "group":
        if not open_conversation_id:
            return {"status": "failed", "error": "缺少 open_conversation_id"}
        if not robot_code:
            return {"status": "failed", "error": "缺少 robot_code"}
    elif not userid:
        return {"status": "failed", "error": "缺少 dingtalk_userid"}

    # 1) 生成测试Excel
    out_dir = _ROOT / "data" / "output" / "钉钉测试"
    out_dir.mkdir(parents=True, exist_ok=True)
    file = out_dir / f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    pd.DataFrame({
        "序号": [1, 2, 3],
        "商品": ["A", "B", "C"],
        "时间": [datetime.now()] * 3,
    }).to_excel(str(file), index=False)
    logger.info(f"生成文件: {file}")

    # 2) 按模式发送：默认保持原单聊；group 模式复用同一文件生成逻辑发送到群
    if send_mode == "group":
        from src.agent.dingtalk_robot import build_robot
        res = build_robot().send_group_file(
            file_path=str(file),
            open_conversation_id=open_conversation_id,
            robot_code=robot_code,
        )
    else:
        res = await DeliveryService().deliver(
            file_path=str(file),
            user_config={},
            task_name="钉钉测试",
            channels=["dingtalk"],
            dingtalk_userid=userid,
        )
    return {"file": str(file), "result": res}
