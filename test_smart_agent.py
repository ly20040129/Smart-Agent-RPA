# -*- coding: utf-8 -*-
"""
测试入口 - 验证LLM是否真正参与

运行方式：
    python test_smart_agent.py           # 列出所有任务
    python test_smart_agent.py list      # 列出所有任务
    python test_smart_agent.py run 公众号资金账单  # 执行指定任务
"""
import asyncio
import sys
import os

# 添加项目根路径（确保 src 包可被发现）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.task_manager import TaskManager
from src.agent.task_executor import TaskExecutor


async def list_tasks():
    """列出所有任务"""
    tm = TaskManager()
    tasks = tm.list_tasks()

    print("\n" + "=" * 60)
    print(f"  共 {len(tasks)} 个任务")
    print("=" * 60)

    for task in tasks:
        status = "✅启用" if task.get("enabled") else "❌禁用"
        print(f"\n  [{status}] {task.get('name', '未命名')}")
        print(f"  描述: {task.get('description', '无')}")
        print(f"  步骤数: {len(task.get('steps', []))}")
        print(f"  定时: {task.get('schedule', '无')}")

        # 打印步骤
        for i, step in enumerate(task.get("steps", [])):
            print(f"    {i+1}. [{step.get('type')}/{step.get('action')}] {step.get('description', '')}")

    print("\n" + "=" * 60)


async def run_task(task_id: str):
    """执行指定任务"""
    print(f"\n🚀 开始执行任务: {task_id}\n")

    executor = TaskExecutor()
    result = await executor.execute_task(task_id)

    print("\n" + "=" * 60)
    print("执行结果:")
    print(f"  状态: {result.get('status')}")
    print(f"  任务: {result.get('task_name', task_id)}")

    if result.get('status') == 'success':
        print(f"  耗时: {result.get('elapsed_time')}秒")
        ctx = result.get('context', {})
        if 'data_result' in ctx:
            dr = ctx['data_result']
            print(f"  数据处理说明: {dr.get('explanation', '')}")
            print(f"  LLM生成的代码: {dr.get('code', '')[:200]}...")
            print(f"  验证结果: {dr.get('validation', {})}")
        if 'downloaded_file' in ctx:
            print(f"  下载文件: {ctx['downloaded_file']}")
    else:
        print(f"  错误: {result.get('error')}")

    print("=" * 60)


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "list":
        asyncio.run(list_tasks())
    elif sys.argv[1] == "run":
        if len(sys.argv) < 3:
            print("用法: python test_smart_agent.py run <任务名称>")
            return
        asyncio.run(run_task(sys.argv[2]))
    else:
        print("用法:")
        print("  python test_smart_agent.py list")
        print("  python test_smart_agent.py run <任务名称>")


if __name__ == "__main__":
    main()
