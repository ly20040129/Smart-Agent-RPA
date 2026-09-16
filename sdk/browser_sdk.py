# -*- coding: utf-8 -*-
"""
浏览器 SDK - 全部基于 browser-use 驱动

不再依赖 Playwright 手写选择器，所有操作由 AI 理解自然语言后执行。

用法：
    from sdk import Browser
    async with Browser(cookie_key="wechat_billing") as b:
        await b.open("https://pay.weixin.qq.com/")
        await b.click("下载业务明细账单")
        file = await b.download("下载文件")

原生操作（goto/type_text/press_key 等）仍保留，用于 browser-use 不擅长的精细操作。
内部通过 browser-use 的 Browser 对象获取 Playwright page。
"""
import sys
import os
import asyncio
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.tools.browser_use_agent import BrowserUseAgent
from src.storage import storage_manager
from sdk.cookie_manager import cookie_manager


class Cookie:
    """Cookie 管理（委托给 cookie_manager）"""

    @classmethod
    def save(cls, key, cookies, expire_days=30):
        return cookie_manager.save(key, cookies, expire_days)

    @classmethod
    def ttl(cls, key):
        return cookie_manager.ttl(key)

    @classmethod
    def is_valid(cls, key):
        return cookie_manager.is_valid(key)

    @classmethod
    def list_all(cls):
        return cookie_manager.list_all()

    @classmethod
    def load(cls, key):
        return cookie_manager.load(key)

    @classmethod
    def delete(cls, key):
        return cookie_manager.delete(key)


class Browser:
    """
    浏览器操作 SDK - browser-use 驱动

    智能方法（通过 AI 理解自然语言）：
        open(url)       - 打开页面
        click("下载")   - 点击按钮
        fill("手机号", "13800000000") - 填输入框
        download("下载文件") - 下载文件
        wait("页面加载完成") - 智能等待

    原生方法（直接操作 Playwright，不经过 AI，速度更快）：
        goto / type_text / press_key / scroll / screenshot 等
    """

    def __init__(self, cookie_key=None, headless=False):
        self.cookie_key = cookie_key
        self._agent = None          # BrowserUseAgent 实例
        self._browser = None       # browser-use 的 Browser 对象
        self._page = None           # Playwright page（惰性获取）
        self._headless = headless
        self._cookies_restored = False
        self._current_frame = None

    # ═══════════════════════════════════════════
    #  生命周期
    # ═══════════════════════════════════════════

    async def start(self):
        """启动浏览器（browser-use）"""
        if self._agent is None:
            self._agent = BrowserUseAgent()
            self._browser = await self._agent._get_or_create_browser(headless=self._headless)
            # 恢复 cookie
            if self.cookie_key:
                cookies = cookie_manager.load(self.cookie_key)
                if cookies:
                    try:
                        ctx = await self._browser._get_context()
                        if ctx:
                            await ctx.add_cookies(cookies)
                            self._cookies_restored = True
                            print(f"[Browser] 恢复Cookie: {self.cookie_key} ({len(cookies)}条)")
                    except Exception as e:
                        print(f"[Browser] Cookie恢复失败: {e}")
        return self

    async def close(self):
        """关闭浏览器，保存 cookie"""
        if self._browser:
            if self.cookie_key:
                try:
                    ctx = await self._browser._get_context()
                    if ctx:
                        cookies = await ctx.cookies()
                        if cookies:
                            cookie_manager.save(self.cookie_key, cookies)
                            print(f"[Browser] Cookie已保存: {len(cookies)}条")
                except Exception:
                    pass
            # browser-use 的 Browser 会自动清理
            self._browser = None
            self._agent = None
            self._page = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ═══════════════════════════════════════════
    #  智能操作（通过 browser-use AI 执行）
    # ═══════════════════════════════════════════

    @property
    def _ctx(self):
        """获取当前操作上下文"""
        if self._current_frame is not None:
            return self._current_frame
        return self.page

    @property
    async def _async_ctx(self):
        if self._current_frame is not None:
            return self._current_frame
        return await self._get_page()

    async def open(self, url):
        """打开页面"""
        await self.start()
        print(f"[Browser] 打开: {url}")
        await self._agent.run(task=f"打开页面 {url}", initial_url=url)

    async def click(self, description):
        """点击按钮/链接（自然语言描述）"""
        await self.start()
        print(f"[Browser] 点击: {description}")
        await self._agent.run(task=f"点击页面上的'{description}'按钮或链接")

    async def fill(self, description, value):
        """填输入框（自然语言描述）"""
        await self.start()
        print(f"[Browser] 填充: {description} <- {value}")
        await self._agent.run(task=f"在页面上的'{description}'输入框中填入：{value}")

    async def download(self, description, timeout=120):
        """下载文件（自然语言描述），返回文件路径"""
        await self.start()
        print(f"[Browser] 下载: {description}")
        result = await self._agent.run(
            task=f"下载页面上的'{description}'文件。下载完成后返回文件保存路径。"
        )
        if result:
            print(f"[Browser] 下载完成: {result}")
        return result

    async def wait(self, seconds=None, condition=None, timeout=30):
        """等待：传数字=等待秒数，传字符串=AI判断等待条件"""
        if seconds is not None and isinstance(seconds, str):
            condition = seconds
            seconds = None

        if seconds is not None and isinstance(seconds, (int, float)):
            print(f"[Browser] 等待 {seconds} 秒")
            await asyncio.sleep(seconds)
            return
        if condition is not None:
            await self.start()
            print(f"[Browser] 等待: {condition}")
            await self._agent.run(task=f"等待页面满足条件：{condition}。满足后返回。")

    async def sleep(self, seconds):
        """简单等待N秒"""
        print(f"[Browser] 等待 {seconds} 秒")
        await asyncio.sleep(seconds)

    async def screenshot(self, name=None):
        """截图"""
        await self.start()
        page = await self._get_page()
        import time as _t
        name = name or f"screenshot_{_t.strftime('%Y%m%d_%H%M%S')}"
        path = f"screenshots/{name}.png"
        os.makedirs("screenshots", exist_ok=True)
        await page.screenshot(path=path)
        print(f"[Browser] 截图: {path}")
        return path

    # ═══════════════════════════════════════════
    #  登录相关
    # ═══════════════════════════════════════════

    async def wait_login(self, prompt="请扫码登录，完成后按回车继续..."):
        """等用户扫码登录，按回车后自动保存cookie"""
        await self.start()
        print(f"\n[Browser] {prompt}\n")
        input()
        if self.cookie_key:
            try:
                ctx = await self._browser._get_context()
                if ctx:
                    cookies = await ctx.cookies()
                    cookie_manager.save(self.cookie_key, cookies)
                    print(f"[Browser] Cookie已保存: {len(cookies)}条")
            except Exception as e:
                print(f"[Browser] Cookie保存失败: {e}")

    async def wait_login_auto(self, timeout=300, interval=3, on_success=None, on_timeout=None, on_progress=None):
        """自动轮询检测登录完成（三层判定）"""
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
                ctx = await self._browser._get_context()
                if not ctx:
                    continue

                cookies = await ctx.cookies()
                cookie_names = {c.get("name", "") for c in cookies}
                found = [c for c in core_cookies if c in cookie_names and any(x.get("name") == c and x.get("value") for x in cookies)]
                missing = [c for c in core_cookies if c not in found]

                page = await self._get_page()
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
                ok = result["ok"]

                if ok:
                    cookie_manager.save(self.cookie_key, cookies)
                    print(f"[Browser] ✅ 登录成功（轮询#{poll_count}，耗时{elapsed}秒）")
                    if on_success:
                        r = on_success()
                        if asyncio.iscoroutine(r):
                            await r
                    return True
                else:
                    threshold = min(2, len(core_cookies))
                    print(f"[Browser] 轮询#{poll_count} ({elapsed}s): 核心 {len(found)}/{len(core_cookies)}≥{threshold} | {result['reason']}")

            except Exception as e:
                print(f"[Browser] 轮询#{poll_count} 异常: {e}")

        print(f"[Browser] ⏰ 登录超时（{timeout}秒）")
        if on_timeout:
            r = on_timeout()
            if asyncio.iscoroutine(r):
                await r
        return False

    async def check_login(self, login_url, success_hint="页面显示首页或工作台"):
        """检查是否已登录，未登录则自动等待"""
        await self.start()
        await self.open(login_url)

        if self._cookies_restored:
            await asyncio.sleep(2)
            try:
                page = await self._get_page()
                current_url = page.url
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

    # ═══════════════════════════════════════════
    #  原生 Playwright 操作（不经 AI，速度快）
    # ═══════════════════════════════════════════

    async def _get_page(self):
        """获取当前 Playwright page"""
        if self._page is None:
            ctx = await self._browser._get_context()
            if ctx and ctx.pages:
                self._page = ctx.pages[-1]
        return self._page

    @property
    def page(self):
        """同步获取 page（可能为 None，首次需要 await _get_page()）"""
        if self._page is not None:
            return self._page
        # 尝试从 browser 对象获取
        if self._browser:
            try:
                ctx = self._browser._context
                if ctx and ctx.pages:
                    self._page = ctx.pages[-1]
                    return self._page
            except Exception:
                pass
        return self._page

    async def goto(self, url, wait_until="domcontentloaded"):
        """导航到指定URL（原生 Playwright）"""
        await self.start()
        page = await self._get_page()
        print(f"[Browser] 导航: {url}")
        await page.goto(url, wait_until=wait_until)
        await asyncio.sleep(1)

    async def type_text(self, selector, text, delay=0):
        """逐字符输入文本"""
        await self.start()
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

    async def press_key(self, key):
        """按键"""
        await self.start()
        page = await self._get_page()
        print(f"[Browser] 按键: {key}")
        await page.keyboard.press(key)

    async def select_option(self, selector, value=None, label=None):
        """选择下拉框"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        if value:
            await loc.select_option(value=value)
        elif label:
            await loc.select_option(label=label)

    async def hover(self, selector):
        """鼠标悬停"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.hover()

    async def scroll(self, direction="down", pixels=None):
        """滚动页面"""
        await self.start()
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
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.scroll_into_view_if_needed()

    async def get_text(self, selector=None):
        """获取元素文本"""
        await self.start()
        page = await self._get_page()
        if selector:
            loc = page.locator(selector).first
            return await loc.text_content()
        return await page.inner_text("body")

    async def get_attribute(self, selector, attr):
        """获取元素属性"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        return await loc.get_attribute(attr)

    async def is_visible(self, selector, timeout=3000):
        """检查元素是否可见"""
        await self.start()
        page = await self._get_page()
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    async def wait_for_selector(self, selector, state="visible", timeout=30000):
        """等待元素"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state=state, timeout=timeout)

    async def wait_for_url(self, url_pattern, timeout=30000):
        """等待URL变化"""
        await self.start()
        page = await self._get_page()
        await page.wait_for_url(url_pattern, timeout=timeout)

    async def switch_tab(self, index=-1):
        """切换标签页"""
        await self.start()
        ctx = await self._browser._get_context()
        pages = ctx.pages
        if not pages:
            return False
        target = pages[index]
        await target.bring_to_front()
        self._page = target
        print(f"[Browser] 切换到标签页: {target.url}")
        return True

    async def close_tab(self, index=None):
        """关闭标签页"""
        await self.start()
        ctx = await self._browser._get_context()
        pages = ctx.pages
        if len(pages) <= 1:
            return False
        target_idx = index if index is not None else len(pages) - 1
        await pages[target_idx].close()
        print(f"[Browser] 关闭标签页 #{target_idx}")

    async def execute_js(self, script):
        """执行 JavaScript"""
        await self.start()
        page = await self._get_page()
        return await page.evaluate(script)

    async def upload_file(self, selector, file_path):
        """上传文件"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.set_input_files(file_path)
        print(f"[Browser] ✅ 上传完成: {file_path}")

    async def reload(self, wait_until="domcontentloaded"):
        """刷新页面"""
        await self.start()
        page = await self._get_page()
        await page.reload(wait_until=wait_until)

    async def go_back(self):
        """后退"""
        await self.start()
        page = await self._get_page()
        await page.go_back()

    async def go_forward(self):
        """前进"""
        await self.start()
        page = await self._get_page()
        await page.go_forward()

    async def get_url(self):
        """获取当前URL"""
        await self.start()
        page = await self._get_page()
        return page.url

    async def get_title(self):
        """获取页面标题"""
        await self.start()
        page = await self._get_page()
        return await page.title()

    async def click_button_by_text(self, text, exact=True, timeout=5000):
        """按文本点击按钮（原生 Playwright）"""
        await self.start()
        page = await self._get_page()
        for t in [text, text.replace(" ", "")]:
            try:
                loc = page.get_by_role("button", name=t)
                await loc.wait_for(state="visible", timeout=timeout)
                await loc.click(force=True, timeout=timeout)
                return True
            except Exception:
                continue
            try:
                loc = page.get_by_text(t, exact=exact)
                await loc.wait_for(state="visible", timeout=2000)
                await loc.click(force=True, timeout=timeout)
                return True
            except Exception:
                continue
        return False

    async def click_by_selector(self, selector, timeout=5000, force=True):
        """按 CSS 选择器点击"""
        await self.start()
        page = await self._get_page()
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.click(force=force, timeout=timeout)
            return True
        except Exception:
            return False

    async def click_and_download(self, text=None, selector=None, timeout=150000):
        """点击按钮并下载文件"""
        await self.start()
        page = await self._get_page()

        async def _do_click():
            if text:
                for t in [text, text.replace(" ", "")]:
                    try:
                        loc = page.get_by_text(t, exact=True)
                        await loc.click(force=True, timeout=5000)
                        return True
                    except Exception:
                        continue
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

    # ===== 补全方法 =====

    async def double_click(self, selector, timeout=5000):
        """双击"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.dblclick(timeout=timeout)

    async def right_click(self, selector, timeout=5000):
        """右键"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click(button="right", timeout=timeout)

    async def check(self, selector, timeout=5000):
        """勾选"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.check(timeout=timeout)

    async def uncheck(self, selector, timeout=5000):
        """取消勾选"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.uncheck(timeout=timeout)

    async def drag(self, from_selector, to_selector, timeout=5000):
        """拖拽"""
        await self.start()
        page = await self._get_page()
        src = page.locator(from_selector).first
        dst = page.locator(to_selector).first
        await src.wait_for(state="visible", timeout=timeout)
        await dst.wait_for(state="visible", timeout=timeout)
        await src.drag_to(dst, timeout=timeout)

    async def set_text(self, selector, text, timeout=5000):
        """直接设置值"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.fill(text, timeout=timeout)

    async def element_exists(self, selector, timeout=3000):
        """元素是否存在"""
        await self.start()
        page = await self._get_page()
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="attached", timeout=timeout)
            return True
        except Exception:
            return False

    async def element_count(self, selector):
        """元素数量"""
        await self.start()
        page = await self._get_page()
        loc = page.locator(selector)
        return await loc.count()

    async def screenshot_element(self, selector, name=None):
        """元素截图"""
        await self.start()
        page = await self._get_page()
        import time as _t
        name = name or f"element_{_t.strftime('%Y%m%d_%H%M%S')}"
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        path = f"screenshots/{name}.png"
        os.makedirs("screenshots", exist_ok=True)
        await loc.screenshot(path=path)
        return path

    async def screenshot_full(self, name=None):
        """整页截图"""
        await self.start()
        page = await self._get_page()
        import time as _t
        name = name or f"fullpage_{_t.strftime('%Y%m%d_%H%M%S')}"
        path = f"screenshots/{name}.png"
        os.makedirs("screenshots", exist_ok=True)
        await page.screenshot(path=path, full_page=True)
        return path

    async def new_tab(self, url=None):
        """新建标签页"""
        await self.start()
        ctx = await self._browser._get_context()
        page = await ctx.new_page()
        if url:
            await page.goto(url)
        await page.bring_to_front()
        self._page = page
        return page

    async def switch_to_frame(self, selector):
        """切换到 iframe"""
        await self.start()
        page = await self._get_page()
        self._current_frame = page.frame_locator(selector)

    async def switch_to_main_frame(self):
        """切回主页面"""
        self._current_frame = None

    async def get_cookies(self):
        """获取所有Cookie"""
        await self.start()
        ctx = await self._browser._get_context()
        return await ctx.cookies()

    async def set_cookie(self, name, value, domain=None, path="/"):
        """设置Cookie"""
        await self.start()
        ctx = await self._browser._get_context()
        cookie = {"name": name, "value": value, "path": path}
        if domain:
            cookie["domain"] = domain
        await ctx.add_cookies([cookie])

    async def delete_cookies(self, name=None):
        """删除Cookie"""
        await self.start()
        ctx = await self._browser._get_context()
        if name:
            await ctx.clear_cookies(name=name)
        else:
            await ctx.clear_cookies()
