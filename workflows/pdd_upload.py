#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDD视频上传（重构版）

重构前：379 行，手动 Cookie 读取/预检查/回存、手动浏览器管理
重构后：~200 行，装饰器处理 Cookie/日志，核心上传逻辑不变

设计原则：拼多多 anti-content 机制需要 DrissionPage + webpack 注入，
这部分是业务特有的，保留原样。只把 Cookie 管理、日志交给装饰器。
"""
import sys
import os
import math
import time
import json
import random
import requests
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from DrissionPage import ChromiumPage, ChromiumOptions
from loguru import logger

from src.decorators import with_logging, validate_params
from sdk.cookie_manager import cookie_manager

# ============ 默认配置 ============

DEFAULT_VIDEO_FILE = r"Z:\团队文件-拼多多-已发布视频\宗-便携打印机-20260611\51.mp4"
DEFAULT_DESC = "TEST-TEST-TEST"
DEFAULT_GOODS_ID = 665175096143

COOKIE_KEY = "pdd"
ANCHOR_DECLARATION_TYPE = 11
CHUNK_MIN = 3 * 1024 * 1024
CHUNK_MAX = 7 * 1024 * 1024

PDD_VIDEO_PAGE = "https://live.pinduoduo.com/n-creator/video/home?msfrom=mms_sidenav"
SDK_VERSION = "js-0.0.32"
TAG_NAME = "backbone-video-sign"


def _random_chunk_size():
    return random.randint(CHUNK_MIN, CHUNK_MAX)


class PDDAPIUploader:
    """拼多多视频上传器（核心逻辑不变）"""

    def __init__(self, cookie_str=""):
        self.cookie_str = cookie_str
        self.page = None
        self.session = requests.Session()
        self._anti_func_ready = False

    def init_browser(self):
        co = ChromiumOptions()
        co.headless(False)
        co.set_argument("--disable-blink-features=AutomationControlled")
        self.page = ChromiumPage(co)

        logger.info("[1/3] 浏览器启动，注入Cookie...")
        self.page.get("https://live.pinduoduo.com")
        time.sleep(2)

        if not self.cookie_str:
            cookies = cookie_manager.load(COOKIE_KEY)
            if cookies:
                self.cookie_str = "; ".join(
                    f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value")
                )
                logger.info(f"  从Redis加载cookie: {len(cookies)}个")

        if self.cookie_str:
            for pair in self.cookie_str.split("; "):
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    self.page.set.cookies({"name": name.strip(), "value": value.strip(),
                                          "domain": ".pinduoduo.com", "path": "/"})

        self.page.get(PDD_VIDEO_PAGE)
        time.sleep(4)

        if "login" in self.page.url:
            logger.info("  Cookie已过期，请在浏览器中手动登录...")
            while "login" in self.page.url:
                time.sleep(2)
            logger.info("  登录成功，继续...")
            self.page.get(PDD_VIDEO_PAGE)
            time.sleep(4)

        logger.info("[2/3] 注入webpack获取anti-content生成函数...")
        self.page.run_js("""
        self.webpackChunk_N_E.push([['_hack'],{},function(wpReq){
            try { var exp = wpReq(59026); if (exp && typeof exp.cN === 'function') window.__getAnti = exp.cN; }
            catch(e) { window.__hack_error = e.message; }
        }]);
        """)
        time.sleep(1)

        has_func = self.page.run_js('return typeof window.__getAnti === "function";')
        if not has_func:
            err = self.page.run_js("return window.__hack_error || 'unknown';")
            logger.error(f"  [FAIL] 获取cN函数失败: {err}")
            return False

        self._anti_func_ready = True
        logger.info("[3/3] anti-content生成函数就绪!")
        return True

    def get_anti_content(self):
        return self.page.run_js("return (async () => { try { return await window.__getAnti(); } catch(e) { return null; } })();")

    def browser_api(self, url, method="POST", body=None):
        anti = self.get_anti_content()
        if not anti:
            return None
        js_code = f"""return (async () => {{
            try {{
                var resp = await fetch({json.dumps(url)}, {{
                    method: {json.dumps(method)},
                    headers: {{ 'content-type': 'application/json', 'anti-content': {json.dumps(anti)} }},
                    body: {json.dumps(json.dumps(body)) if body is not None else 'null'},
                    credentials: 'include'
                }});
                var text = await resp.text();
                return JSON.stringify({{status: resp.status, body: text}});
            }} catch(e) {{ return JSON.stringify({{error: e.message}}); }}
        }})();"""
        result = self.page.run_js(js_code)
        if result:
            data = json.loads(result)
            if "error" in data:
                logger.error(f"    [JS错误] {data['error']}")
                return None
            return data
        return None

    def file_api(self, url, method="POST", body=None, files=None):
        headers = {"accept": "*/*", "Referer": "https://live.pinduoduo.com/"}
        if files:
            return self.session.post(url, headers=headers, files=files)
        headers["content-type"] = "application/json"
        return self.session.post(url, headers=headers, json=body)

    def upload(self, video_path, desc, goods_id):
        file_size = os.path.getsize(video_path)
        file_name = os.path.basename(video_path)
        logger.info(f"视频: {file_name} | {file_size/1024/1024:.2f} MB")

        # Step 1: 签名
        logger.info("[Step 1] 获取上传签名...")
        url = f"https://live.pinduoduo.com/live/galerie/signature?sdk_version={SDK_VERSION}&tag_name={TAG_NAME}"
        result = self.browser_api(url, "POST", {"bucket_tag": TAG_NAME})
        if not result:
            return False
        resp_data = json.loads(result["body"])
        signature = resp_data.get("signature")
        if not signature:
            logger.error(f"  [FAIL] {result['body'][:200]}")
            return False

        # Step 2: 初始化
        logger.info("[Step 2] 初始化分片上传...")
        url = f"https://file-b.pinduoduo.com/api/galerie/large_file/v1/video/upload_init?sdk_version={SDK_VERSION}&tag_name={TAG_NAME}"
        resp = self.file_api(url, body={"content_type": "video/mp4", "create_media": True, "sign": signature})
        sign = resp.json().get("sign")
        if not sign:
            logger.error(f"  [FAIL] {resp.text[:200]}")
            return False

        # Step 3: 分片上传
        logger.info("[Step 3] 分片上传...")
        url = "https://file-b.pinduoduo.com/api/galerie/large_file/v1/video/upload_part"
        part_num, uploaded_bytes = 0, 0
        with open(video_path, "rb") as f:
            while True:
                chunk = f.read(_random_chunk_size())
                if not chunk:
                    break
                part_num += 1
                files = {"sign": (None, sign), "part_num": (None, str(part_num)),
                         "part_file": ("blob", chunk, "application/octet-stream")}
                resp = self.file_api(url, files=files)
                if "uploaded_part_num" not in resp.json():
                    logger.error(f"  [{part_num}] [FAIL]")
                    return False
                uploaded_bytes += len(chunk)
                logger.debug(f"  [{part_num}] {len(chunk)//1024}KB ({uploaded_bytes*100/file_size:.0f}%)")

        # Step 4: 完成上传
        logger.info("[Step 4] 完成上传...")
        url = "https://file-b.pinduoduo.com/api/galerie/large_file/v1/video/upload_complete"
        resp = self.file_api(url, body={"sign": sign, "large_file_size": file_size})
        vid = resp.json().get("vid", "")
        if not vid:
            return False

        # Step 5-6: 查询声明 + 校验商品
        self.browser_api("https://live.pinduoduo.com/api/backbone/video/publish/page/query", "POST", {})
        logger.info(f"[Step 6] 校验商品 (ID: {goods_id})...")
        self.browser_api("https://live.pinduoduo.com/api/backbone/goods/check", "POST", {"goodsIds": [goods_id]})

        # Step 7: 预发布
        logger.info("[Step 7] 预发布...")
        body = {"prePublishFeedVOList": [{"goodsList": [{"goodsId": goods_id, "specialType": 2}],
                "title": file_name, "desc": desc, "coverUrl": "", "vid": vid,
                "allowSync": True, "syncVideo": True, "newPushPxq": 0,
                "useRecRelatedGoods": False, "anchorDeclarationType": ANCHOR_DECLARATION_TYPE}]}
        result = self.browser_api("https://live.pinduoduo.com/mms/amco/prePublish/add", "POST", body)
        if not result or not json.loads(result["body"]).get("success"):
            return False

        # Step 8: 发布
        logger.info("[Step 8] 发布...")
        body = {"feeds": [{"desc": desc, "goodsIdList": [goods_id], "vid": vid,
                "syncVideo": True, "needCreateCoverUrl": True, "newPushPxq": 0,
                "useRecRelatedGoods": False, "anchorDeclarationType": ANCHOR_DECLARATION_TYPE}],
                "fromAwardFilm": False, "fromCourseTopicActivity": False,
                "goodsPermission": False, "commonPermission": False}
        result = self.browser_api("https://live.pinduoduo.com/api/backbone/video/publish", "POST", body)
        if result and json.loads(result["body"]).get("success"):
            logger.info(f"  [OK] 发布成功!")
            return True
        return False


@with_logging("拼多多视频上传")
@validate_params("video_file")
def run(video_file=None, desc=None, goods_id=None, **kwargs):
    """任务执行入口（被 task_executor 调用）"""
    video_file = video_file or DEFAULT_VIDEO_FILE
    desc = desc or DEFAULT_DESC
    goods_id = int(goods_id or DEFAULT_GOODS_ID)

    if not os.path.exists(video_file):
        raise RuntimeError(f"视频文件不存在: {video_file}")

    # Cookie 预检查
    if not cookie_manager.ensure_valid(COOKIE_KEY):
        raise RuntimeError(f"Cookie不存在或已过期（{COOKIE_KEY}），请去Web界面刷新")

    uploader = PDDAPIUploader()
    try:
        if not uploader.init_browser():
            raise RuntimeError("浏览器初始化失败")
        if not uploader.upload(video_file, desc, goods_id):
            raise RuntimeError("拼多多视频上传失败")
        # 回存最新 Cookie
        cookie_manager.capture_from_drissionpage(uploader.page, COOKIE_KEY)
    finally:
        if uploader.page:
            time.sleep(3)
            try:
                uploader.page.quit()
            except Exception:
                pass

    logger.info("[SUCCESS] 视频上传发布完成!")
    return video_file


if __name__ == "__main__":
    run()