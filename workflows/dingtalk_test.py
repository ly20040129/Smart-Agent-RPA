# -*- coding: utf-8 -*-
"""钉钉测试 workflow：生成Excel + 单聊发给 dingtalk_userid"""
import sys, asyncio
from pathlib import Path
from datetime import datetime
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agent.delivery_service import DeliveryService
from loguru import logger


async def test_send_file(**kwargs):
    userid = (kwargs.get("dingtalk_userid") or "").strip()
    if not userid:
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

    # 2) 单聊发钉钉（config.yaml里的delivery.dingtalk会被DeliveryService自己读取）
    res = await DeliveryService().deliver(
        file_path=str(file),
        user_config={},
        task_name="钉钉测试",
        channels=["dingtalk"],
        dingtalk_userid=userid,
    )
    return {"file": str(file), "result": res}


if __name__ == "__main__":
    USERID = ""   # 本地调试时填自己的 userid
    if USERID:
        asyncio.run(test_send_file(dingtalk_userid=USERID))
    else:
        print("先在 __main__ 里填 USERID，或直接跑Web任务")
