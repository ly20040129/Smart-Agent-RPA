# -*- coding: utf-8 -*-
"""
定时清理脚本 - 清理过期的本地文件

清理目录：
  - data/output/        任务输出文件
  - data/user_uploads/  用户上传文件
  - data/screenshots/   浏览器/桌面截图
  - data/downloads/     下载文件

默认保留期限：30 天
"""
import os
import time
from pathlib import Path

from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent

# 清理配置：(目录, 保留天数)
_CLEANUP_DIRS = [
    ("data/output", 30),
    ("data/user_uploads", 30),
    ("data/screenshots", 30),
    ("data/downloads", 30),
]


def cleanup_expired_files(dry_run: bool = False) -> dict:
    """清理过期文件。

    Args:
        dry_run: True 只统计不删除

    Returns:
        {"cleaned": 删除文件数, "freed_mb": 释放空间MB, "details": [...]}
    """
    now = time.time()
    results = {"cleaned": 0, "freed_mb": 0.0, "details": []}

    for rel_dir, keep_days in _CLEANUP_DIRS:
        target = _PROJECT_ROOT / rel_dir
        if not target.exists():
            continue

        dir_count = 0
        dir_size = 0.0

        for root, dirs, files in os.walk(target):
            for f in files:
                fp = Path(root) / f
                try:
                    mtime = fp.stat().st_mtime
                    age_days = (now - mtime) / 86400
                    if age_days > keep_days:
                        size_mb = fp.stat().st_size / (1024 * 1024)
                        if dry_run:
                            logger.info(f"[Cleanup] 将删除: {fp} ({size_mb:.2f}MB, {age_days:.0f}天)")
                        else:
                            fp.unlink()
                            logger.info(f"[Cleanup] 已删除: {fp} ({size_mb:.2f}MB, {age_days:.0f}天)")
                        dir_count += 1
                        dir_size += size_mb
                except Exception as e:
                    logger.warning(f"[Cleanup] 跳过: {fp} — {e}")

        if dir_count > 0:
            results["details"].append({"dir": rel_dir, "count": dir_count, "size_mb": round(dir_size, 2)})
        results["cleaned"] += dir_count
        results["freed_mb"] += dir_size

    results["freed_mb"] = round(results["freed_mb"], 2)
    logger.info(f"[Cleanup] 完成: 删除 {results['cleaned']} 个文件, 释放 {results['freed_mb']}MB")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="清理过期本地文件")
    parser.add_argument("--dry-run", action="store_true", help="只统计不删除")
    args = parser.parse_args()
    cleanup_expired_files(dry_run=args.dry_run)
