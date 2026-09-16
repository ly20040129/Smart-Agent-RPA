# -*- coding: utf-8 -*-
"""步骤类型注册表 —— 任务编排层通过 STEP_HANDLERS 分发到具体实现"""
from . import api, browser, data, deliver, desktop, loop, notify, workflow

STEP_HANDLERS = {
    "browser": browser.run,
    "desktop": desktop.run,
    "data": data.run,
    "api": api.run,
    "deliver": deliver.run,
    "notify": notify.run,
    "workflow": workflow.run,
    "loop": loop.run,
}
