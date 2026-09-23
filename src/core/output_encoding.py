# -*- coding: utf-8 -*-
"""
进程输出编码 —— 全项目只在这里决定，其他模块不要自行 reconfigure。

背景（实测结论，不是推测）：

    Windows 上 Python 的输出编码跟随 locale。输出被重定向到文件/管道时，
    sys.stdout.encoding 实测为 gbk(cp936)，于是日志文件里落地的是 GBK 字节；
    而下游工具（编辑器、日志收集、CI、Linux 容器）默认按 UTF-8 读，就会乱码。

    输出直接接在交互式控制台上时，Python 走 Windows 控制台 API，中文正常，
    不需要干预（start.bat 里已经 chcp 65001）。

策略：

    重定向（非交互）→ 固定 UTF-8，保证日志文件与跨平台一致
    交互式控制台    → 保持平台默认，cmd.exe 里中文才正常

反面教材：曾经 workflows/pdd_upload.py 在 import 时直接
    sys.stdout.reconfigure(encoding="utf-8")
这是一个 workflow 模块去改「整个进程」的 I/O —— 会影响所有任务的日志，
而且是否乱码取决于模块导入顺序。这类全局副作用必须收敛到入口一处。
"""
import sys

_APPLIED = False


def setup_output_encoding(force_utf8: bool = None) -> None:
    """按「是否交互式控制台」决定输出编码。入口处调用一次，重复调用无副作用。

    force_utf8=None  由 stream.isatty() 自动判断（默认，推荐）
    force_utf8=True  强制 UTF-8（确信终端支持 UTF-8 时）
    force_utf8=False 强制保持平台默认
    """
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True

    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        need_utf8 = force_utf8 if force_utf8 is not None else not stream.isatty()
        if not need_utf8:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
