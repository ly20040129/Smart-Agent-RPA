"""
智能体平台主入口文件
"""
import os
import sys

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asyncio
from loguru import logger

from src.core.config import get_config
from src.web.api import start_server


def main():
    """
    主入口函数
    
    功能：
    1. 加载配置
    2. 启动Web服务器
    """
    try:
        # 加载配置
        config = get_config()
        
        logger.info("=" * 60)
        logger.info("智能体平台启动")
        logger.info("=" * 60)
        logger.info(f"配置文件: {config.config_path}")
        logger.info(f"LLM模型: {config.llm.model}")
        logger.info(f"浏览器类型: {config.browser.browser_type}")
        logger.info(f"Web地址: http://{config.web.host}:{config.web.port}")
        logger.info("=" * 60)
        
        # 启动Web服务器
        start_server()
        
    except Exception as e:
        logger.error(f"启动失败: {e}")
        raise


def run_cli():
    """
    命令行接口 - 直接执行工作流（不启动Web服务器）
    """
    import sys
    
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python main.py cli wechat_pay_billing")
        print("  python main.py web")
        return
    
    command = sys.argv[1]
    
    if command == "wechat_pay_billing":
        # 直接执行公众号账单流程
        async def run_workflow():
            workflow = WeChatPayBillingWorkflow()
            result = await workflow.execute()
            
            print("\n执行结果:")
            print(f"状态: {result['status']}")
            
            if result['status'] == 'success':
                print(f"销售额: {result['sales_amount']}")
                print(f"退款额: {result['refund_amount']}")
                print(f"输出文件: {result['output_path']}")
            else:
                print(f"错误: {result['error']}")
        
        asyncio.run(run_workflow())
    
    elif command == "web":
        # 启动Web服务器
        main()
    
    else:
        print(f"未知命令: {command}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        run_cli()
    else:
        main()