# -*- coding: utf-8 -*-
"""
浏览器 SDK —— 纯 Playwright 选择器驱动

设计原则（对标 workflows/tm_video_up.py 的写法）：
  一个类、一条路径：所有方法都是确定性操作，出问题直接看日志定位。
  不内置任何 LLM/AI 调用；易变页面的 AI 操作后续由 Midscene 侧车提供。

用法：
    from sdk.browser_sdk import Browser

    agent = Browser(cookie_key="tm_video_up")
    await agent.start()
    await agent.goto("https://xxx.com")
    await agent.type_text("input[name='user']", "账号")
    ...
    await agent.close()

    # 或用 async with（退出自动保存 cookie 并关闭）
    async with Browser(cookie_key="tm_video_up") as agent:
        await agent.goto("https://xxx.com")

Cookie 生命周期：
    start() 时从 Redis 恢复 → close() 时自动抓取保存
"""
import sys
import os
import asyncio
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from playwright.async_api import async_playwright
from sdk.cookie_manager import cookie_manager


class Browser:
    """浏览器操作 SDK（纯 Playwright，无 AI）"""

    def __init__(self, cookie_key=None, headless=None):
        """
        Args:
            headless: None=跟随 config.yaml 的 browser.headless（部署到服务器时设 true）；
                      True/False = 本次强制指定
        """
        self.cookie_key = cookie_key
        if headless is None:
            try:
                from src.core.config import get_config
                headless = get_config().browser.headless
            except Exception:
                headless = False
        self._headless = headless
        self._pw = None            # Playwright 实例
        self._pw_browser = None    # Chromium 浏览器
        self._pw_context = None    # 浏览器上下文（cookie 挂在这里）
        self._page = None          # 当前页面
        self._cookies_restored = False

    # ═══════════════════════════════════════════
    #  生命周期
    # ═══════════════════════════════════════════

    async def start(self):
        """启动浏览器，恢复 cookie"""
        if self._pw is not None:
            return self
        self._pw = await async_playwright().start()
        self._pw_browser = await self._pw.chromium.launch(
            headless=self._headless,
            channel="msedge",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._pw_context = await self._pw_browser.new_context()
        # 隐藏 navigator.webdriver，降低被识别为自动化的概率
        await self._pw_context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        self._page = await self._pw_context.new_page()

        if self.cookie_key:
            cookies = cookie_manager.load(self.cookie_key)
            if cookies:
                try:
                    await self._pw_context.add_cookies(cookies)
                    self._cookies_restored = True
                    print(f"[Browser] 恢复Cookie: {self.cookie_key} ({len(cookies)}条)")
                except Exception as e:
                    print(f"[Browser] Cookie恢复失败: {e}")
        return self

    async def close(self):
        """关闭浏览器，保存 cookie"""
        if self._pw_context:
            if self.cookie_key:
                try:
                    cookies = await self._pw_context.cookies()
                    if cookies:
                        cookie_manager.save(self.cookie_key, cookies)
                        print(f"[Browser] Cookie已保存: {len(cookies)}条")
                except Exception:
                    pass
            await self._pw_context.close()
            await self._pw.stop()
        self._pw = None
        self._pw_browser = None
        self._pw_context = None
        self._page = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ═══════════════════════════════════════════
    #  页面访问
    # ═══════════════════════════════════════════

    async def _get_page(self):
        """获取当前 Playwright page"""
        await self.start()
        return self._page

    @property
    def page(self):
        """同步获取 page（start 之后才有值）"""
        return self._page

    async def goto(self, url, wait_until="domcontentloaded"):
        """导航到指定URL"""
        page = await self._get_page()
        print(f"[Browser] 导航: {url}")
        await page.goto(url, wait_until=wait_until)
        await asyncio.sleep(1)

    async def open(self, url):
        """打开页面（goto 的别名，语义更直白）"""
        await self.goto(url)

    async def reload(self, wait_until="domcontentloaded"):
        """刷新页面"""
        page = await self._get_page()
        await page.reload(wait_until=wait_until)

    async def go_back(self):
        """后退"""
        page = await self._get_page()
        await page.go_back()

    async def go_forward(self):
        """前进"""
        page = await self._get_page()
        await page.go_forward()

    async def get_url(self):
        """获取当前URL"""
        page = await self._get_page()
        return page.url

    async def get_title(self):
        """获取页面标题"""
        page = await self._get_page()
        return await page.title()

    async def new_tab(self, url=None):
        """新建标签页"""
        ctx = self._pw_context
        page = await ctx.new_page()
        if url:
            await page.goto(url)
        await page.bring_to_front()
        self._page = page
        return page

    async def switch_tab(self, index=-1):
        """切换标签页"""
        pages = self._pw_context.pages
        if not pages:
            return False
        target = pages[index]
        await target.bring_to_front()
        self._page = target
        print(f"[Browser] 切换到标签页: {target.url}")
        return True

    async def close_tab(self, index=None):
        """关闭标签页"""
        pages = self._pw_context.pages
        if len(pages) <= 1:
            return False
        target_idx = index if index is not None else len(pages) - 1
        await pages[target_idx].close()
        print(f"[Browser] 关闭标签页 #{target_idx}")

    # ═══════════════════════════════════════════
    #  等待
    # ═══════════════════════════════════════════

    async def sleep(self, seconds):
        """等待N秒"""
        print(f"[Browser] 等待 {seconds} 秒")
        await asyncio.sleep(seconds)

    async def wait_for_selector(self, selector, state="visible", timeout=30000):
        """等待元素出现"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state=state, timeout=timeout)

    async def wait_for_url(self, url_pattern, timeout=30000):
        """等待URL变化"""
        page = await self._get_page()
        await page.wait_for_url(url_pattern, timeout=timeout)

    async def is_visible(self, selector, timeout=3000):
        """检查元素是否可见"""
        page = await self._get_page()
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    # ═══════════════════════════════════════════
    #  点击 / 输入
    # ═══════════════════════════════════════════

    async def type_text(self, selector, text, delay=0):
        """点击元素后逐字符输入文本"""
        page = await self._get_page()
        print(f"[Browser] 输入: {selector} <- {text}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.click()
        await asyncio.sleep(0.2)
        await loc.press("Control+a")
        await loc.press("Delete")
        await page.keyboard.type(text, delay=delay)
        print(f"[Browser] ✅ 输入完成")

    async def set_text(self, selector, text, timeout=5000):
        """直接设置输入框的值（不逐字符）"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.fill(text, timeout=timeout)

    async def press_key(self, key):
        """按键"""
        page = await self._get_page()
        print(f"[Browser] 按键: {key}")
        await page.keyboard.press(key)

    async def click_by_selector(self, selector, timeout=5000, force=True):
        """按 CSS 选择器点击"""
        page = await self._get_page()
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.click(force=force, timeout=timeout)
            return True
        except Exception:
            return False

    async def click_button_by_text(self, text, exact=True, timeout=5000):
        """按文本点击按钮/链接"""
        page = await self._get_page()
        for t in [text, text.replace(" ", "")]:
            try:
                loc = page.get_by_role("button", name=t)
                await loc.wait_for(state="visible", timeout=timeout)
                await loc.click(force=True, timeout=timeout)
                return True
            except Exception:
                pass
            try:
                loc = page.get_by_text(t, exact=exact)
                await loc.wait_for(state="visible", timeout=2000)
                await loc.click(force=True, timeout=timeout)
                return True
            except Exception:
                pass
        return False

    async def click_and_download(self, text=None, selector=None, timeout=150000):
        """点击按钮并捕获下载文件，返回文件路径"""
        page = await self._get_page()

        async def _do_click():
            if text:
                for t in [text, text.replace(" ", "")]:
                    try:
                        loc = page.get_by_text(t, exact=True)
                        await loc.click(force=True, timeout=5000)
                        return True
                    except Exception:
                        pass
            if selector:
                try:
                    loc = page.locator(selector).first
                    await loc.click(force=True, timeout=5000)
                    return True
                except Exception:
                    pass
            return False

        try:
            async with page.expect_download(timeout=timeout) as di:
                await _do_click()
            dw = await di.value
            save_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(save_dir, exist_ok=True)
            import time as _t
            ts = _t.strftime("%Y%m%d_%H%M%S")
            fname = f"download_{ts}_" + (dw.suggested_filename or "file")
            fpath = os.path.join(save_dir, fname)
            await dw.save_as(fpath)
            print(f"[Browser] ✅ 下载完成: {fpath}")
            return fpath
        except Exception as e:
            print(f"[Browser] ❌ 下载失败: {e}")
            return None

    async def double_click(self, selector, timeout=5000):
        """双击"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.dblclick(timeout=timeout)

    async def right_click(self, selector, timeout=5000):
        """右键"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click(button="right", timeout=timeout)

    async def check(self, selector, timeout=5000):
        """勾选复选框"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.check(timeout=timeout)

    async def uncheck(self, selector, timeout=5000):
        """取消勾选"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.uncheck(timeout=timeout)

    async def hover(self, selector):
        """鼠标悬停"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.hover()

    async def drag(self, from_selector, to_selector, timeout=5000):
        """拖拽"""
        page = await self._get_page()
        src = page.locator(from_selector).first
        dst = page.locator(to_selector).first
        await src.wait_for(state="visible", timeout=timeout)
        await dst.wait_for(state="visible", timeout=timeout)
        await src.drag_to(dst, timeout=timeout)

    async def upload_file(self, selector, file_path):
        """上传文件（往 input[type=file] 填文件）"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.set_input_files(file_path)
        print(f"[Browser] ✅ 上传完成: {file_path}")

    async def select_option(self, selector, value=None, label=None):
        """选择下拉框"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        if value:
            await loc.select_option(value=value)
        elif label:
            await loc.select_option(label=label)

    # ═══════════════════════════════════════════
    #  读取 / 执行
    # ═══════════════════════════════════════════

    async def get_text(self, selector=None):
        """获取元素文本（不传selector则取整个页面）"""
        page = await self._get_page()
        if selector:
            loc = page.locator(selector).first
            return await loc.text_content()
        return await page.inner_text("body")

    async def get_attribute(self, selector, attr):
        """获取元素属性"""
        page = await self._get_page()
        loc = page.locator(selector).first
        return await loc.get_attribute(attr)

    async def element_exists(self, selector, timeout=3000):
        """元素是否存在"""
        page = await self._get_page()
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="attached", timeout=timeout)
            return True
        except Exception:
            return False

    async def element_count(self, selector):
        """匹配元素的数量"""
        page = await self._get_page()
        return await page.locator(selector).count()

    async def execute_js(self, script):
        """执行 JavaScript"""
        page = await self._get_page()
        return await page.evaluate(script)

    async def scroll(self, direction="down", pixels=None):
        """滚动页面"""
        page = await self._get_page()
        if pixels:
            dx = pixels if direction == "right" else (-pixels if direction == "left" else 0)
            dy = pixels if direction == "down" else (-pixels if direction == "up" else 0)
            await page.mouse.wheel(dx, dy)
        else:
            d = 300 if direction == "down" else -300
            await page.evaluate(f"window.scrollBy({{top: {d}, behavior: 'smooth'}})")

    async def scroll_to_element(self, selector):
        """滚动到元素"""
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.scroll_into_view_if_needed()

    # ═══════════════════════════════════════════
    #  截图
    # ═══════════════════════════════════════════

    async def screenshot(self, name=None):
        """当前视口截图"""
        page = await self._get_page()
        import time as _t
        name = name or f"screenshot_{_t.strftime('%Y%m%d_%H%M%S')}"
        path = f"data/screenshots/{name}.png"
        os.makedirs("data/screenshots", exist_ok=True)
        await page.screenshot(path=path)
        print(f"[Browser] 截图: {path}")
        return path

    async def screenshot_element(self, selector, name=None):
        """元素截图"""
        page = await self._get_page()
        import time as _t
        name = name or f"element_{_t.strftime('%Y%m%d_%H%M%S')}"
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        path = f"data/screenshots/{name}.png"
        os.makedirs("data/screenshots", exist_ok=True)
        await loc.screenshot(path=path)
        return path

    async def screenshot_full(self, name=None):
        """整页截图"""
        page = await self._get_page()
        import time as _t
        name = name or f"fullpage_{_t.strftime('%Y%m%d_%H%M%S')}"
        path = f"data/screenshots/{name}.png"
        os.makedirs("data/screenshots", exist_ok=True)
        await page.screenshot(path=path, full_page=True)
        return path

    # ═══════════════════════════════════════════
    #  Cookie 直接操作
    # ═══════════════════════════════════════════

    async def get_cookies(self):
        """获取当前上下文所有Cookie"""
        await self.start()
        return await self._pw_context.cookies()

    async def set_cookie(self, name, value, domain=None, path="/"):
        """设置Cookie"""
        await self.start()
        cookie = {"name": name, "value": value, "path": path}
        if domain:
            cookie["domain"] = domain
        await self._pw_context.add_cookies([cookie])

    async def delete_cookies(self, name=None):
        """删除Cookie"""
        await self.start()
        if name:
            await self._pw_context.clear_cookies(name=name)
        else:
            await self._pw_context.clear_cookies()

    # ═══════════════════════════════════════════
    #  登录
    # ═══════════════════════════════════════════

    async def wait_login(self, prompt="请扫码登录，完成后按回车继续..."):
        """等用户扫码登录，按回车后自动保存cookie"""
        await self.start()
        print(f"\n[Browser] {prompt}\n")
        input()
        if self.cookie_key:
            try:
                cookies = await self._pw_context.cookies()
                cookie_manager.save(self.cookie_key, cookies)
                print(f"[Browser] Cookie已保存: {len(cookies)}条")
            except Exception as e:
                print(f"[Browser] Cookie保存失败: {e}")

    async def wait_login_auto(self, timeout=300, interval=3, on_success=None, on_timeout=None, on_progress=None):
        """自动轮询检测登录完成（cookie硬门槛 + 页面成功信号两层判定）"""
        import time as _time
        await self.start()

        if not self.cookie_key:
            print("[Browser] 未设置cookie_key，无法自动检测登录")
            return False

        core_cookies = cookie_manager.get_core_cookies(self.cookie_key)
        if not core_cookies:
            return await self.wait_login("请登录后按回车继续")

        print(f"[Browser] 开始自动检测登录（cookie_key={self.cookie_key}，超时{timeout}秒）")
        start = _time.time()
        poll_count = 0

        while _time.time() - start < timeout:
            await asyncio.sleep(interval)
            poll_count += 1
            elapsed = round(_time.time() - start, 1)

            try:
                cookies = await self._pw_context.cookies()
                page = self._page
                url = ""
                title = ""
                body_text = ""
                if page:
                    try:
                        url = page.url or ""
                    except Exception:
                        url = ""
                    try:
                        title = await page.title() or ""
                    except Exception:
                        title = ""
                    try:
                        raw = await page.inner_text("body")
                        body_text = (raw or "")[:2000]
                    except Exception:
                        body_text = ""

                result = cookie_manager.check_login_complete(
                    cookies, self.cookie_key,
                    url=url, title=title, body_text=body_text,
                )

                if result["ok"]:
                    cookie_manager.save(self.cookie_key, cookies)
                    print(f"[Browser] ✅ 登录成功（轮询#{poll_count}，耗时{elapsed}秒）")
                    if on_success:
                        r = on_success()
                        if asyncio.iscoroutine(r):
                            await r
                    return True
                else:
                    print(f"[Browser] 轮询#{poll_count} ({elapsed}s): {result['reason']}")
                    if on_progress:
                        r = on_progress({"elapsed": elapsed, "reason": result["reason"]})
                        if asyncio.iscoroutine(r):
                            await r

            except Exception as e:
                print(f"[Browser] 轮询#{poll_count} 异常: {e}")

        print(f"[Browser] ⏰ 登录超时（{timeout}秒）")
        if on_timeout:
            r = on_timeout()
            if asyncio.iscoroutine(r):
                await r
        return False

    async def check_login(self, login_url):
        """打开登录页，cookie有效则跳过登录，否则等待人工登录"""
        await self.start()
        await self.open(login_url)

        if self._cookies_restored:
            await asyncio.sleep(2)
            try:
                current_url = self._page.url
                if "login" in current_url.lower() or "passport" in current_url.lower():
                    print(f"[Browser] Cookie已过期，需要重新登录")
                    self._cookies_restored = False
                else:
                    print(f"[Browser] Cookie有效，已自动登录")
                    return True
            except Exception:
                pass

        if not self._cookies_restored:
            await self.wait_login("请扫码登录，完成后按回车，Cookie自动保存")

        return True
