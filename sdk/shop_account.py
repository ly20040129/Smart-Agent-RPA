# -*- coding: utf-8 -*-
"""
店铺账号查询
============
各平台店铺的账号密码统一存在本地库 shop_accounts 表，代码和 config 里都不写密码。

表结构（按 shop_account_username 精确取）：
    shop_account_id / phone / shop_name / shop_account_username
    shop_account_password / platform / created_at / updated_at

用法：
    from sdk.shop_account import get_shop_account
    acc = get_shop_account("泳宇-数字人")
    await agent.type_text("input#loginname", acc["shop_account_username"], delay=300)
    await agent.type_text("input[type=password]", acc["shop_account_password"], delay=300)
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger

from src.storage import storage_manager


class AccountNotFound(RuntimeError):
    """库里查不到该店铺账号"""


def get_shop_account(shop_account_username: str) -> dict:
    """
    按账号名精确查 shop_accounts，返回整行 dict。

    查不到直接抛 AccountNotFound —— 不带着空密码去登录浪费时间。
    """
    if not shop_account_username:
        raise AccountNotFound("未指定店铺账号（shop_account_username 为空）")

    rows = storage_manager.execute_sql(
        "SELECT * FROM shop_accounts WHERE shop_account_username = :name LIMIT 1",
        {"name": shop_account_username},
    )
    if not rows:
        raise AccountNotFound(
            f"shop_accounts 表里查不到账号 {shop_account_username!r}，"
            f"确认该平台账号已同步到本地库"
        )

    row = rows[0]
    logger.info(
        f"[Account] 已取到账号: {row.get('shop_account_username')} "
        f"({row.get('platform')} / {row.get('shop_name')})"
    )
    return row
