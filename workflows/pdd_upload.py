#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDD商家版视频自动上传工具
策略：DrissionPage浏览器生成anti-content + requests分片上传 + 浏览器fetch调live接口

通过Web界面触发时，参数从YAML配置传入：
  video_file: 视频文件路径
  desc:       视频描述
  goods_id:   商品ID
  cookie:     拼多多Cookie字符串（从浏览器F12复制）

也可单独运行：python workflows/pdd_upload.py
"""
import sys
import os
import math
import time
import json
import random
import requests
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from DrissionPage import ChromiumPage, ChromiumOptions

# ============ 默认配置（测试运行时用，Web触发时由参数覆盖）============

DEFAULT_VIDEO_FILE = r"Z:\团队文件-拼多多-已发布视频\宗-便携打印机-20260611\51.mp4"
DEFAULT_DESC = "TEST-TEST-TEST"
DEFAULT_GOODS_ID = 665175096143

# PDD cookie的Redis key
COOKIE_KEY = "pdd"

# 内容声明类型
# 11=内容无需标注 | 1=含AI生成内容 | 5=含虚构演绎内容 | 7=内容含营销信息 | 3=内容为转载 | 8=个人观点仅供参考
ANCHOR_DECLARATION_TYPE = 11

# 分片大小随机范围（3MB~7MB），让上传pattern不固定
CHUNK_MIN = 3 * 1024 * 1024
CHUNK_MAX = 7 * 1024 * 1024

PDD_VIDEO_PAGE = "https://live.pinduoduo.com/n-creator/video/home?msfrom=mms_sidenav"
SDK_VERSION = "js-0.0.32"
TAG_NAME = "backbone-video-sign"


def _random_chunk_size():
    return random.randint(CHUNK_MIN, CHUNK_MAX)


class PDDAPIUploader:
    """拼多多视频上传器"""

    def __init__(self, cookie_str=""):
        """
        Args:
            cookie_str: cookie字符串（name=value; name=value格式）
                        如果为空，会从Redis自动读取
        """
        self.cookie_str = cookie_str
        self.page = None
        self.session = requests.Session()
        self._anti_func_ready = False

    def init_browser(self):
        """启动浏览器，注入cookie，获取anti-content生成函数"""
        co = ChromiumOptions()
        co.headless(False)
        co.set_argument('--disable-blink-features=AutomationControlled')
        self.page = ChromiumPage(co)

        print("[1/3] 浏览器启动，注入Cookie...")
        self.page.get("https://live.pinduoduo.com")
        time.sleep(2)

        # 如果没有传cookie字符串，从Redis读取
        if not self.cookie_str:
            from sdk.cookie_manager import cookie_manager
            cookies = cookie_manager.load(COOKIE_KEY)
            if cookies:
                # Redis格式: [{"name":"x","value":"y"}] → 字符串 "x=y; a=b"
                self.cookie_str = "; ".join(
                    f"{c['name']}={c['value']}" for c in cookies if c.get('name') and c.get('value')
                )
                print(f"  从Redis加载cookie: {len(cookies)}个")
            else:
                print(f"  Redis中没有 {COOKIE_KEY} 的cookie，需要手动登录")

        if self.cookie_str:
            for pair in self.cookie_str.split("; "):
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    self.page.set.cookies({"name": name.strip(), "value": value.strip(),
                                          "domain": ".pinduoduo.com", "path": "/"})

        self.page.get(PDD_VIDEO_PAGE)
        time.sleep(4)

        if "login" in self.page.url:
            print("  Cookie已过期，请在浏览器中手动登录...")
            while "login" in self.page.url:
                time.sleep(2)
            print("  登录成功，继续...")
            self.page.get(PDD_VIDEO_PAGE)
            time.sleep(4)

        print("[2/3] 注入webpack获取anti-content生成函数...")
        self.page.run_js("""
        self.webpackChunk_N_E.push([['_hack'],{},function(wpReq){
            try {
                var exp = wpReq(59026);
                if (exp && typeof exp.cN === 'function') {
                    window.__getAnti = exp.cN;
                }
            } catch(e) {
                window.__hack_error = e.message;
            }
        }]);
        """)
        time.sleep(1)

        has_func = self.page.run_js('return typeof window.__getAnti === "function";')
        if not has_func:
            err = self.page.run_js("return window.__hack_error || 'unknown';")
            print(f"  [FAIL] 获取cN函数失败: {err}")
            return False

        test = self.page.run_js("""
        return (async () => {
            var anti = await window.__getAnti();
            return JSON.stringify({ok: anti && anti.startsWith('0aq'), len: anti ? anti.length : 0});
        })();
        """)
        print(f"  cN()验证: {test}")
        self._anti_func_ready = True
        print("[3/3] anti-content生成函数就绪!")
        return True

    def get_anti_content(self):
        """调用浏览器中的cN()生成新的anti-content"""
        return self.page.run_js("""
        return (async () => {
            try { return await window.__getAnti(); }
            catch(e) { return null; }
        })();
        """)

    def browser_api(self, url, method="POST", body=None):
        """通过浏览器fetch调用live.pinduoduo.com接口（自动携带cookie+生成anti-content）"""
        anti = self.get_anti_content()
        if not anti:
            return None

        js_code = f"""
        return (async () => {{
            try {{
                var resp = await fetch({json.dumps(url)}, {{
                    method: {json.dumps(method)},
                    headers: {{
                        'content-type': 'application/json',
                        'anti-content': {json.dumps(anti)}
                    }},
                    body: {json.dumps(json.dumps(body)) if body is not None else 'null'},
                    credentials: 'include'
                }});
                var text = await resp.text();
                return JSON.stringify({{status: resp.status, body: text}});
            }} catch(e) {{
                return JSON.stringify({{error: e.message}});
            }}
        }})();
        """
        result = self.page.run_js(js_code)
        if result:
            data = json.loads(result)
            if "error" in data:
                print(f"    [JS错误] {data['error']}")
                return None
            return data
        return None

    def file_api(self, url, method="POST", body=None, files=None):
        """通过requests调用file-b.pinduoduo.com接口（不需要anti-content）"""
        headers = {"accept": "*/*", "Referer": "https://live.pinduoduo.com/"}
        if files:
            resp = self.session.post(url, headers=headers, files=files)
        else:
            headers["content-type"] = "application/json"
            resp = self.session.post(url, headers=headers, json=body)
        return resp

    def upload(self, video_path, desc, goods_id):
        """完整上传流程：签名→初始化→分片上传→完成→查询声明→校验商品→预发布→发布"""
        file_size = os.path.getsize(video_path)
        file_name = os.path.basename(video_path)

        print(f"\n{'='*60}")
        print(f"视频: {file_name} | {file_size/1024/1024:.2f} MB")
        print(f"{'='*60}")

        # Step 1: 获取签名
        print("\n[Step 1] 获取上传签名...")
        url = f"https://live.pinduoduo.com/live/galerie/signature?sdk_version={SDK_VERSION}&tag_name={TAG_NAME}"
        result = self.browser_api(url, "POST", {"bucket_tag": TAG_NAME})
        if not result:
            return False
        resp_data = json.loads(result['body'])
        if not resp_data.get("signature"):
            print(f"  [FAIL] {result['body'][:200]}")
            return False
        signature = resp_data["signature"]
        print(f"  [OK] signature: {signature[:60]}...")

        # Step 2: 初始化分片上传
        print("\n[Step 2] 初始化分片上传...")
        url = f"https://file-b.pinduoduo.com/api/galerie/large_file/v1/video/upload_init?sdk_version={SDK_VERSION}&tag_name={TAG_NAME}"
        resp = self.file_api(url, body={"content_type": "video/mp4", "create_media": True, "sign": signature})
        data = resp.json()
        sign = data.get("sign")
        if not sign:
            print(f"  [FAIL] {resp.text[:200]}")
            return False
        print(f"  [OK] upload sign: {sign}")

        # Step 3: 分片上传
        print(f"\n[Step 3] 分片上传 (随机大小)...")
        url = "https://file-b.pinduoduo.com/api/galerie/large_file/v1/video/upload_part"
        part_num = 0
        uploaded_bytes = 0
        with open(video_path, "rb") as f:
            while True:
                chunk = f.read(_random_chunk_size())
                if not chunk:
                    break
                part_num += 1
                files = {
                    "sign": (None, sign),
                    "part_num": (None, str(part_num)),
                    "part_file": ("blob", chunk, "application/octet-stream"),
                }
                resp = self.file_api(url, files=files)
                rdata = resp.json()
                if "uploaded_part_num" not in rdata:
                    print(f"  [{part_num}] [FAIL] {resp.text[:100]}")
                    return False
                uploaded_bytes += len(chunk)
                pct = uploaded_bytes * 100 / file_size
                print(f"  [{part_num}] {len(chunk)//1024}KB ({pct:.0f}%)")
        print(f"  [OK] {part_num}片全部上传完成")

        # Step 4: 完成上传
        print("\n[Step 4] 完成上传...")
        url = "https://file-b.pinduoduo.com/api/galerie/large_file/v1/video/upload_complete"
        resp = self.file_api(url, body={"sign": sign, "large_file_size": file_size})
        data = resp.json()
        vid = data.get("vid", "")
        if not vid:
            print(f"  [FAIL] {resp.text[:200]}")
            return False
        print(f"  [OK] vid: {vid}")

        # Step 5: 查询内容声明
        print("\n[Step 5] 查询内容声明列表...")
        result = self.browser_api("https://live.pinduoduo.com/api/backbone/video/publish/page/query", "POST", {})
        if result:
            rdata = json.loads(result['body'])
            if rdata.get("result"):
                decl_list = rdata["result"].get("anchorDeclarationList", [])
                valid_types = [d["type"] for d in decl_list]
                if ANCHOR_DECLARATION_TYPE not in valid_types:
                    print(f"  [WARN] ANCHOR_DECLARATION_TYPE={ANCHOR_DECLARATION_TYPE} 不在可用列表中!")

        # Step 6: 校验商品
        print(f"\n[Step 6] 校验商品 (ID: {goods_id})...")
        result = self.browser_api("https://live.pinduoduo.com/api/backbone/goods/check", "POST", {"goodsIds": [goods_id]})
        if result:
            rdata = json.loads(result['body'])
            if rdata.get("success"):
                print("  [OK] 商品校验通过")

        # Step 7: 预发布
        print("\n[Step 7] 预发布...")
        body = {
            "prePublishFeedVOList": [{
                "goodsList": [{"goodsId": goods_id, "specialType": 2}],
                "title": file_name, "desc": desc, "coverUrl": "",
                "cutStartTime": None, "cutEndTime": None,
                "vid": vid, "allowSync": True, "syncVideo": True,
                "newPushPxq": 0, "useRecRelatedGoods": False,
                "anchorDeclarationType": ANCHOR_DECLARATION_TYPE,
            }]
        }
        result = self.browser_api("https://live.pinduoduo.com/mms/amco/prePublish/add", "POST", body)
        if not result or not json.loads(result['body']).get("success"):
            print(f"  [FAIL] 预发布失败")
            return False
        print("  [OK] 预发布成功")

        # Step 8: 发布
        print("\n[Step 8] 发布...")
        body = {
            "feeds": [{
                "desc": desc, "goodsIdList": [goods_id], "outVideoUrl": "",
                "useRecRelatedGoods": False, "anchorDeclarationType": ANCHOR_DECLARATION_TYPE,
                "cover": "", "vid": vid, "syncVideo": True,
                "needCreateCoverUrl": True, "newPushPxq": 0,
            }],
            "fromAwardFilm": False, "fromCourseTopicActivity": False,
            "goodsPermission": False, "commonPermission": False,
            "commonPermissionVer": "", "highQualityGoodsFeedPermission": False,
            "defaultAvatarOrName": False,
        }
        result = self.browser_api("https://live.pinduoduo.com/api/backbone/video/publish", "POST", body)
        if result:
            rdata = json.loads(result['body'])
            if rdata.get("success"):
                feed_ids = rdata.get("result", {}).get("feedIds", [])
                print(f"  [OK] 发布成功! Feed ID: {feed_ids}")
                return True
        print("  [FAIL] 发布失败")
        return False


def run(video_file=None, desc=None, goods_id=None, **kwargs):
    """
    任务执行入口（被task_executor调用）

    参数从Web界面传入，对应YAML中的params_input：
      video_file: 视频文件路径
      desc:       视频描述
      goods_id:   商品ID（数字）

    cookie不再需要用户传入，自动从Redis读取（cookie_manager）。
    前提：先用浏览器登录过拼多多，cookie已自动存入Redis。
    """
    video_file = video_file or DEFAULT_VIDEO_FILE
    desc = desc or DEFAULT_DESC
    goods_id = int(goods_id or DEFAULT_GOODS_ID)

    if not os.path.exists(video_file):
        raise RuntimeError(f"视频文件不存在: {video_file}")

    # cookie从Redis自动读取，不传给PDDAPIUploader时它会自己读
    uploader = PDDAPIUploader()
    try:
        if not uploader.init_browser():
            raise RuntimeError("浏览器初始化失败，无法获取anti-content函数")
        success = uploader.upload(video_file, desc, goods_id)

        # 上传完成后，把最新cookie保存回Redis
        from sdk.cookie_manager import cookie_manager
        cookie_manager.capture_from_drissionpage(uploader.page, COOKIE_KEY)
    except Exception as e:
        import traceback
        traceback.print_exc()
        success = False
    finally:
        if uploader.page:
            time.sleep(3)
            try:
                uploader.page.quit()
            except Exception:
                pass

    print("\n" + "=" * 60)
    if success:
        print("[SUCCESS] 视频上传发布完成!")
        return video_file
    else:
        print("[FAILED] 上传失败")
        raise RuntimeError("拼多多视频上传失败")


if __name__ == "__main__":
    run()
