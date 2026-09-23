"""
智能体平台主入口文件
"""
import os
import sys

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from loguru import logger

from src.core.output_encoding import setup_output_encoding
from src.core.logging_setup import setup_logging

setup_output_encoding()  # 输出编码全项目只在这里定一次，见 src/core/output_encoding.py
setup_logging()  # 日志落盘全项目只在这里定一次，见 src/core/logging_setup.py

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


if __name__ == "__main__":
    main()