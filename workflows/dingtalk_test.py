# -*- coding: utf-8 -*-
import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.agent.delivery_service import DeliveryService
from src.core.config import get_config


async def test_send_file(**kwargs):
    """
    测试钉钉发送文件
    """
    print("开始测试钉钉文件发送...")

    # 1. 创建一个测试 Excel 文件
    test_data = pd.DataFrame({
        "测试列1": [1, 2, 3],
        "测试列2": ["A", "B", "C"],
        "测试时间": [datetime.now()] * 3
    })
    
    out_dir = Path(r"C:\Users\31557\Desktop")
    out_dir.mkdir(exist_ok=True, parents=True)
    file_path = out_dir / f"钉钉测试文件_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    test_data.to_excel(str(file_path), index=False)
    print(f"✅ 测试文件已生成: {file_path}")

    # 2. 获取配置（使用 config_data 属性访问原始字典）
    config = get_config()
    delivery_config = config.config_data.get("delivery", {})
    dingtalk_config = delivery_config.get("dingtalk", {})
    
    user_config = {
        "delivery": {
            "dingtalk": dingtalk_config
        }
    }

    print(f"📋 钉钉配置: app_key={dingtalk_config.get('app_key', '未配置')[:10]}...")

    # 3. 发送钉钉文件
    delivery = DeliveryService()
    result = await delivery.deliver(
        file_path=str(file_path),
        user_config=user_config,
        task_name="钉钉测试",
        channels=["dingtalk"],
        dingtalk_userid="1783298686946923"  # ← 改成你的钉钉 userid
    )

    print(f"✅ 钉钉发送结果: {result}")
    return {"file": str(file_path), "result": result}


if __name__ == "__main__":
    asyncio.run(test_send_file())