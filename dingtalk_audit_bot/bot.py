# -*- coding: utf-8 -*-
"""钉钉审单卡片机器人

群消息含「审核」→ 发卡片 → 用户自己选店铺 → 确认 → POST 影刀 webhook
配置：config/config.yaml -> audit_bot 节点
存储：Redis，key = agent:audit_task:{task_id}，24 小时过期
启动：cd E:\\smart-agent-rpa && python -m dingtalk_audit_bot.bot
"""
import asyncio
import json
import os
import time
import urllib.request
import uuid

import dingtalk_stream
from dingtalk_stream import AckMessage
from loguru import logger

from alibabacloud_dingtalk.card_1_0 import models as card_models
from alibabacloud_dingtalk.card_1_0.client import Client as CardClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from src.core.config import get_config
from src.storage.redis_manager import RedisManager

CFG = get_config().config_data.get("audit_bot", {})

APP_KEY = CFG.get("app", {}).get("app_key") or os.getenv("APP_KEY", "")
APP_SECRET = CFG.get("app", {}).get("app_secret") or os.getenv("APP_SECRET", "")
ROBOT_CODE = CFG.get("app", {}).get("robot_code") or APP_KEY
CARD_TEMPLATE_ID = CFG.get("card_template_id", "")
YINGDAO_WEBHOOK = CFG.get("yingdao_webhook", "")
TRIGGER_KEYWORD = CFG.get("trigger_keyword", "审")
SHOP_LIST = CFG.get("shops", [])

TASK_TTL = 24 * 3600
_redis = None
_token_cache = {"value": None, "expire_at": 0}


def init_storage():
    global _redis
    redis_cfg = get_config().config_data.get("storage", {}).get("redis", {})
    _redis = RedisManager(
        host=redis_cfg.get("host", "127.0.0.1"),
        port=int(redis_cfg.get("port", 6379)),
        db=int(redis_cfg.get("db", 0)),
        password=redis_cfg.get("password", ""),
        prefix=redis_cfg.get("prefix", "agent:"),
    )
    if _redis.client is None:
        raise RuntimeError("Redis 连接失败，请检查 config.yaml 的 storage.redis")


def save_task(task_id, task):
    _redis.set(f"audit_task:{task_id}", task, expire=TASK_TTL)


def load_task(task_id):
    return _redis.get(f"audit_task:{task_id}") or {}


def _shop_options():
    return [{"value": shop, "text": {"zh_CN": shop, "zh_TW": shop, "en_US": shop}} for shop in SHOP_LIST]


def _selected_shops(params):
    """卡片下拉回传结构: {"multiSelect": {"value": [...]}}"""
    raw = params.get("multiSelect")
    if isinstance(raw, dict):
        raw = raw.get("value") or []
    if not isinstance(raw, list):
        return []
    return [item.get("value") if isinstance(item, dict) else item for item in raw if item]


def _post_json(url, payload, headers=None, timeout=15):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


async def get_token():
    if _token_cache["value"] and _token_cache["expire_at"] > time.time() + 60:
        return _token_cache["value"]
    data = await asyncio.to_thread(
        _post_json, "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        {"appKey": APP_KEY, "appSecret": APP_SECRET},
    )
    if not data.get("accessToken"):
        raise RuntimeError(f"获取 accessToken 失败: {data}")
    _token_cache["value"] = data["accessToken"]
    _token_cache["expire_at"] = time.time() + int(data.get("expireIn", 7200))
    return _token_cache["value"]


async def send_card(conversation_id, user_id, task_id):
    """发卡片，不预选店铺，由用户自己挑"""
    token = await get_token()
    headers = card_models.CreateAndDeliverHeaders()
    headers.x_acs_dingtalk_access_token = token

    card_data = card_models.CreateAndDeliverRequestCardData(card_param_map={
        "order_summary": "请选择要审核的店铺",
        "shop_options": json.dumps(_shop_options(), ensure_ascii=False),
        "default_indexes": "[]",
        "task_id": task_id,
    })
    request = card_models.CreateAndDeliverRequest(
        user_id=user_id,
        card_template_id=CARD_TEMPLATE_ID,
        out_track_id=f"audit-{task_id}",
        callback_type="STREAM",
        card_data=card_data,
        open_space_id=f"dtv1.card//im_group.{conversation_id}",
        im_group_open_deliver_model=card_models.CreateAndDeliverRequestImGroupOpenDeliverModel(
            robot_code=ROBOT_CODE,
            at_user_ids={user_id: "操作人"},
            recipients=[user_id],
        ),
        im_group_open_space_model=card_models.CreateAndDeliverRequestImGroupOpenSpaceModel(
            support_forward=True,
            last_message_i18n={"ZH_CN": "请确认要审核的店铺"},
        ),
        user_id_type=1,
    )
    await CardClient(open_api_models.Config(protocol="https", region_id="central")).create_and_deliver_with_options_async(
        request, headers, util_models.RuntimeOptions()
    )


async def update_card(task_id, shops, summary=None):
    """回调后回写卡片，把选中项渲染出来"""
    try:
        token = await get_token()
        headers = card_models.UpdateCardHeaders()
        headers.x_acs_dingtalk_access_token = token
        indexes = [SHOP_LIST.index(shop) for shop in shops if shop in SHOP_LIST]
        request = card_models.UpdateCardRequest(
            card_data=card_models.UpdateCardRequestCardData(card_param_map={
                "order_summary": summary or f"已选中 {len(indexes)} 家店铺，点「确认执行」提交",
                "shop_options": json.dumps(_shop_options(), ensure_ascii=False),
                "default_indexes": json.dumps(indexes),
            }),
            out_track_id=f"audit-{task_id}",
            user_id_type=1,
        )
        await CardClient(open_api_models.Config(protocol="https", region_id="central")).update_card_with_options_async(
            request, headers, util_models.RuntimeOptions()
        )
    except Exception as e:
        logger.warning(f"[Card] 更新卡片失败: {e}")


def start_rpa(task_id, shops):
    """一次请求带上全部店铺：shops 是数组，shop 是逗号拼好的文本，影刀两种都能取"""
    if not YINGDAO_WEBHOOK:
        logger.info(f"[RPA] 未配置 webhook，跳过: {shops}")
        return "未配置"
    payload = {"task_id": task_id, "shops": shops, "shop": "、".join(shops)}
    req = urllib.request.Request(
        YINGDAO_WEBHOOK,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    logger.info(f"[RPA] {len(shops)} 家响应: {raw[:200]}")
    return "已提交"


def push_group_text(origin, text):
    origin = origin or {}
    if not origin.get("open_conversation_id"):
        return
    try:
        token = _post_json("https://api.dingtalk.com/v1.0/oauth2/accessToken",
                           {"appKey": APP_KEY, "appSecret": APP_SECRET}).get("accessToken")
        _post_json("https://api.dingtalk.com/v1.0/robot/groupMessages/send", {
            "robotCode": ROBOT_CODE,
            "openConversationId": origin["open_conversation_id"],
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": text}, ensure_ascii=False),
        }, {"x-acs-dingtalk-access-token": token})
    except Exception as e:
        logger.warning(f"[DingTalk] 回推群消息失败: {e}")


class AuditBotHandler(dingtalk_stream.ChatbotHandler):
    async def process(self, callback: dingtalk_stream.CallbackMessage):
        message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        text = (message.text.content or "").strip()
        if TRIGGER_KEYWORD not in text:
            return AckMessage.STATUS_OK, "OK"

        task_id = uuid.uuid4().hex[:10]
        save_task(task_id, {
            "shops": [],
            "status": "pending",
            "origin": {"open_conversation_id": message.conversation_id, "user_id": message.sender_staff_id},
        })
        try:
            await send_card(message.conversation_id, message.sender_staff_id, task_id)
            logger.info(f"[Card] 已发卡片 task={task_id}")
        except Exception as e:
            logger.error(f"[Card] 发卡片失败: {e}")
            self.reply_text(f"卡片发送失败：{e}", message)
        return AckMessage.STATUS_OK, "OK"


class CardCallbackHandler(dingtalk_stream.CallbackHandler):
    async def process(self, callback: dingtalk_stream.CallbackMessage):
        data = callback.data or {}
        content = json.loads(data.get("content") or "{}")
        private = content.get("cardPrivateData") or {}
        params = private.get("params") or {}
        action = params.get("action") or (private.get("actionIds") or [""])[0]
        out_track_id = data.get("outTrackId") or ""
        task_id = params.get("task_id") or out_track_id.replace("audit-", "", 1)
        logger.info(f"[Card] action={action} task={task_id} params={params}")

        task = load_task(task_id)
        if not task:
            return AckMessage.STATUS_OK, "OK"

        # 用户改了选择：存下来并回写卡片
        if "multiSelect" in str(action):
            task["shops"] = _selected_shops(params)
            save_task(task_id, task)
            await update_card(task_id, task["shops"])
            return AckMessage.STATUS_OK, "OK"

        # 用户点确认：把全部已选店铺一次性提交给影刀
        if "confirm_audit" not in str(action) or task["status"] != "pending":
            return AckMessage.STATUS_OK, "OK"
        shops = _selected_shops(params) or task["shops"]
        if not shops:
            # 下拉变更回调可能丢失（Stream 重连或重复起进程），记录下来方便排查
            logger.warning(f"[Card] 确认时没有店铺，回调原始数据: {data}")
            await update_card(task_id, [], "未收到你的选择，请重新勾选后再点「确认执行」")
            return AckMessage.STATUS_OK, "OK" 

        task["status"] = "reviewing"
        save_task(task_id, task)

        try:
            result = await asyncio.to_thread(start_rpa, task_id, shops)
        except Exception as e:
            result = f"失败 {e}"
            logger.error(f"[RPA] 提交失败: {e}")

        summary = f"{result}：{'、'.join(shops)}"
        task["status"] = "done" if "失败" not in result else "failed"
        task["result"] = summary
        save_task(task_id, task)
        await update_card(task_id, shops, summary)
        await asyncio.to_thread(push_group_text, task.get("origin"), summary)
        return AckMessage.STATUS_OK, "OK"


def main():
    if not APP_KEY or not APP_SECRET:
        raise SystemExit("缺少 audit_bot.app.app_key / app_secret")
    if not CARD_TEMPLATE_ID:
        raise SystemExit("缺少 audit_bot.card_template_id")
    if not SHOP_LIST:
        raise SystemExit("缺少 audit_bot.shops")

    init_storage()
    client = dingtalk_stream.DingTalkStreamClient(dingtalk_stream.Credential(APP_KEY, APP_SECRET))
    client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, AuditBotHandler())
    client.register_callback_handler("/v1.0/card/instances/callback", CardCallbackHandler())
    logger.info(f"[Bot] 启动 | 店铺 {len(SHOP_LIST)} 家 | 模板 {CARD_TEMPLATE_ID}")
    client.start_forever()


if __name__ == "__main__":
    main()
