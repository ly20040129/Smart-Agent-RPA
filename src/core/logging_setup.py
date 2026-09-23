# -*- coding: utf-8 -*-
"""
日志统一配置 —— 全项目只在这里配一次，其他模块不要自行调 logger.add()。

背景（实测结论）：
    在加这个模块之前，全项目没有任何一处 logger.add()，loguru 只剩它默认的
    stderr sink —— 日志只在终端显示，进程一退出就没了，重启后查不到上一次
    为什么失败。

策略：
    终端 → 保留原有观感（彩色，时间/级别/代码位置）
    文件 → data/logs/app_日期.log    全量，INFO 及以上
           data/logs/error_日期.log  只留 ERROR 及以上
    切分 → 每天 0 点换新文件，自动清理 30 天前的

安全（重要）：
    diagnose 固定 False。loguru 默认会把异常回溯里的局部变量一起打出来，
    而 workflows 里有明文账号密码（例如 tm_video_up.py 的 psw），
    打开就等于把凭据写进日志文件。

入口：
    main.py 启动时调一次；start_server() 里再兜底调一次（重复调用无副作用），
    保证不管从哪个入口起服务，日志都落盘。data/logs/ 已在 .gitignore 中忽略。
"""
import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "logs"

_APPLIED = False

# 终端格式：跟 loguru 默认观感一致，避免和之前看惯的输出差太多
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# 文件格式：带毫秒，排查任务时序问题时有用
_FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} - {message}"

# 两个文件 sink 共用的参数
_SINK_KWARGS = dict(
    format=_FILE_FORMAT,
    encoding="utf-8",   # 必须显式 utf-8：Windows 默认跟随 locale(gbk)，中文会写坏，
                        # 详见 src/core/output_encoding.py
    rotation="00:00",
    retention="30 days",
    enqueue=False,      # 不加 enqueue：走后台线程缓冲的话，进程被强杀时最后几条会丢，
                        # 而这里要的正是崩溃后能查到现场。loguru 默认 sink 本身线程安全。
    backtrace=True,
    diagnose=False,     # 见模块开头「安全」一节，不要改成 True
)


def setup_logging(level: str = "INFO") -> None:
    """配置日志：终端 + 落盘。入口处调用一次，重复调用无副作用。"""
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 去掉 loguru 默认的 stderr sink，否则会和下面这个控制台 sink 重复输出
    logger.remove()

    logger.add(sys.stderr, level=level, format=_CONSOLE_FORMAT, colorize=True)
    logger.add(LOG_DIR / "app_{time:YYYY-MM-DD}.log", level=level, **_SINK_KWARGS)
    logger.add(LOG_DIR / "error_{time:YYYY-MM-DD}.log", level="ERROR", **_SINK_KWARGS)
