# 浏览器工具包
# 封装了浏览器操作和Cookie持久化
#
# 用法：
#   from sdk import Browser
#   async with Browser(cookie_key="wechat_billing") as b:
#       await b.open("https://pay.weixin.qq.com/")
#       await b.wait_login("请扫码登录")
#       file = await b.download("点击下载业务明细账单")
import sys
import os
import asyncio
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.agent.smart_browser import SmartBrowser
from src.storage import storage_manager
from sdk.cookie_manager import cookie_manager


class Cookie:
    """Cookie管理 - 委托给 cookie_manager，自动按平台精简"""

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
    """浏览器操作，传cookie_key就自动存取登录态"""

    def __init__(self, cookie_key=None, headless=False):
        self.cookie_key = cookie_key
        self._sb = None
        self._headless = headless
        self._cookies_restored = False
        self._current_frame = None

    def _ctx(self):
        """获取当前操作上下文：如果在iframe中则返回frame_locator，否则返回page"""
        if self._sb is None:
            raise RuntimeError("浏览器未启动，请先调用 start() 或使用 async with Browser() as b:")
        page = self._sb.browser.page
        if self._current_frame is not None:
            return self._current_frame
        return page

    async def start(self):
        if self._sb is None:
            self._sb = SmartBrowser()
            await self._sb.start(headless=self._headless)
            # 启动时从Redis恢复cookie
            if self.cookie_key:
                cookies = cookie_manager.load(self.cookie_key)
                if cookies:
                    try:
                        ctx = getattr(self._sb.browser, "context", None)
                        if ctx:
                            await ctx.add_cookies(cookies)
                            self._cookies_restored = True
                            print(f"[Browser] 恢复Cookie成功: {self.cookie_key} ({len(cookies)}条)")
                    except Exception as e:
                        print(f"[Browser] Cookie恢复失败: {e}")
        return self._sb

    async def close(self):
        if self._sb:
            # 关闭前抓取最新cookie，但只在已登录时才保存
            # 避免未登录状态下把好cookie覆盖成坏的
            if self.cookie_key:
                try:
                    ctx = getattr(self._sb.browser, "context", None)
                    if ctx:
                        # logged_in=None 让cookie_manager自动检测是否已登录
                        cookie_manager.capture_from_context(ctx, self.cookie_key, logged_in=None)
                except Exception:
                    pass
            try:
                await self._sb.close()
            except (Exception, asyncio.CancelledError):
                pass
            self._sb = None

    async def open(self, url):
        await self.start()
        print(f"[Browser] 打开: {url}")
        await self._sb.navigate(url)

    async def click(self, description):
        # 用自然语言描述点哪里，比如 "点击：下载按钮"
        await self.start()
        print(f"[Browser] 点击: {description}")
        await self._sb.smart_click(description)

    async def fill(self, description, value):
        # 填输入框，比如 fill("手机号输入框", "13800138000")
        await self.start()
        print(f"[Browser] 填充: {description}")
        await self._sb.smart_fill(description, value)

    async def download(self, description, timeout=120):
        # 下载文件，自动处理弹窗，返回文件路径
        await self.start()
        print(f"[Browser] 下载: {description}")
        path = await self._sb.smart_download(description, timeout=timeout)
        if path:
            print(f"[Browser] 下载完成: {path}")
        return path

    async def scroll_to_bottom(self, times=3, wait=1.5):
        # 滚动到底部，times=滚几次（防止懒加载）
        await self.start()
        print(f"[Browser] 滚动到底部（{times}次）")
        await self._sb.scroll_to_bottom(times=times, wait=wait)

    async def extract_table(self, start_col_name=None):
        # 提取页面表格，start_col_name从哪一列开始（如"单据类型"）
        await self.start()
        print(f"[Browser] 提取表格" + (f"（从列：{start_col_name}开始）" if start_col_name else ""))
        return await self._sb.extract_table(start_col_name)

    async def set_page_size(self, size=1000):
        # 设置分页条数：1000条/页
        await self.start()
        print(f"[Browser] 设置分页大小: {size}条/页")
        ok = await self._sb.set_page_size(size)
        if ok:
            print(f"[Browser] 已设置: {size}条/页")
        else:
            print(f"[Browser] 设置分页失败，请手动选择{size}条/页，然后按回车继续")
            # 等待用户手动设置
            try:
                input()
            except:
                pass
        return ok

    async def screenshot(self, name=None):
        await self.start()
        return await self._sb.browser.screenshot(name) if hasattr(self._sb.browser, "screenshot") else None

    async def wait_login(self, prompt="请扫码登录，完成后按回车继续..."):
        # 需要人工扫码时调用，扫完按回车自动存cookie
        await self.start()
        print(f"\n{'='*50}")
        print(f"[Browser] {prompt}")
        print(f"{'='*50}\n")
        input()
        if self.cookie_key:
            # 用户已手动确认登录成功，明确传 logged_in=True
            ctx = getattr(self._sb.browser, "context", None)
            if ctx:
                cookies = await ctx.cookies()
                cookie_manager.save(self.cookie_key, cookies)
                print(f"[Browser] 登录完成，Cookie已保存: {len(cookies)}条")

    async def wait_login_auto(self, timeout=300, interval=3000, on_success=None, on_timeout=None):
        """
        自动轮询检测登录成功（不阻塞事件循环，不需要用户在终端操作）

        每 interval 秒检查一次浏览器cookie，当核心cookie出现（表示已登录）时自动保存。
        适用于Web界面触发的Cookie刷新场景。

        Args:
            timeout: 最大等待秒数（默认5分钟）
            interval: 轮询间隔秒数（默认3天）
            on_success: 登录成功时的回调（同步或异步函数）
            on_timeout: 超时时的回调

        Returns:
            True=登录成功，False=超时
        """
        import time as _time
        await self.start()

        if not self.cookie_key:
            print("[Browser] 未设置cookie_key，无法自动检测登录")
            return False

        core_cookies = cookie_manager.get_core_cookies(self.cookie_key)
        if not core_cookies:
            print(f"[Browser] {self.cookie_key}: 未配置核心cookie，回退到手动确认")
            return await self.wait_login("请登录后按回车继续")

        print(f"[Browser] 开始自动检测登录（cookie_key={self.cookie_key}，超时{timeout}秒）")
        start = _time.time()

        while _time.time() - start < timeout:
            await asyncio.sleep(interval)
            try:
                ctx = getattr(self._sb.browser, "context", None)
                if not ctx:
                    continue
                cookies = await ctx.cookies()
                # 检查核心cookie是否出现
                for c in cookies:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    if name in core_cookies and value:
                        # 登录成功！保存cookie
                        cookie_manager.save(self.cookie_key, cookies)
                        elapsed = round(_time.time() - start, 1)
                        print(f"[Browser] 自动检测到登录成功（耗时{elapsed}秒），Cookie已保存: {len(cookies)}条")
                        if on_success:
                            result = on_success()
                            if asyncio.iscoroutine(result):
                                await result
                        return True
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[Browser] 轮询检测异常: {e}")

        # 超时
        print(f"[Browser] ⏰ 登录超时（{timeout}秒）")
        if on_timeout:
            result = on_timeout()
            if asyncio.iscoroutine(result):
                await result
        return False

    async def check_login(self, login_url, success_hint="页面显示首页或工作台"):
        """
        检查是否已登录，未登录则自动打开登录页面等待
        
        流程：
        1. 打开网站
        2. 如果cookie有效且页面显示登录后的内容 → 自动跳过登录
        3. 如果cookie过期或未保存 → 提示扫码登录，扫完自动保存
        """
        await self.start()
        await self.open(login_url)
        
        if self._cookies_restored:
            # cookie已恢复，等一下看是否真的登录成功了
            await asyncio.sleep(2)
            try:
                # 用LLM检查是否已登录
                from src.agent.smart_browser import SmartBrowser
                # 简单检测：看URL是否还在登录页
                current_url = self._sb.browser.page.url
                if "login" in current_url.lower() or "passport" in current_url.lower():
                    # 还在登录页，cookie已过期
                    print(f"[Browser] Cookie已过期，需要重新登录")
                    self._cookies_restored = False
                else:
                    print(f"[Browser] Cookie有效，已自动登录")
                    return True
            except Exception:
                pass
        
        # 需要登录
        if not self._cookies_restored:
            await self.wait_login("请扫码登录，完成后按回车，Cookie自动保存30天")
        
        return True

    async def click_button_by_text(self, text, exact=True, timeout=5000):
        """用 Playwright 原生 API 按文本直接点击按钮（不经过 LLM）"""
        await self.start()
        page = self._sb.browser.page
        print(f'[Browser] 按文本点击按钮: {text}')
        # 尝试 get_by_role > get_by_text > CSS
        try:
            loc = page.get_by_role('button', name=text)
            await loc.wait_for(state='visible', timeout=timeout)
            await loc.click(force=True, timeout=timeout)
            print(f'[Browser] ✅ 点击成功: {text}')
            return True
        except Exception:
            pass
        try:
            loc = page.get_by_text(text, exact=exact)
            await loc.wait_for(state='visible', timeout=timeout)
            await loc.click(force=True, timeout=timeout)
            print(f'[Browser] ✅ 点击成功: {text}')
            return True
        except Exception:
            pass
        for css in [f".el-button--primary:has-text('{text}')", f"button:has-text('{text}')"]:
            try:
                loc = page.locator(css).first
                await loc.wait_for(state='visible', timeout=2000)
                await loc.click(force=True, timeout=timeout)
                print(f'[Browser] ✅ 点击成功(CSS): {text}')
                return True
            except Exception:
                continue
        print(f'[Browser] ❌ 点击失败: {text}')
        return False

    async def click_by_selector(self, selector, timeout=5000, force=True):
        """用 Playwright 原生 CSS 选择器直接点击（不经过 LLM）"""
        await self.start()
        page = self._sb.browser.page
        print(f'[Browser] 按选择器点击: {selector}')
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state='visible', timeout=timeout)
            await loc.click(force=force, timeout=timeout)
            print(f'[Browser] ✅ 点击成功: {selector}')
            return True
        except Exception as e:
            print(f'[Browser] ❌ 点击失败: {selector}: {e}')
            return False

    async def click_and_download(self, text=None, selector=None, timeout=150000):
        """点击按钮并捕获下载文件，返回文件路径"""
        await self.start()
        page = self._sb.browser.page
        download_path = None

        async def _do_click():
            if text:
                for t in [text, text.replace(' ', '')]:
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
            import os, time
            save_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
            os.makedirs(save_dir, exist_ok=True)
            ts = time.strftime('%Y%m%d_%H%M%S')
            fname = f'download_{ts}_' + (dw.suggested_filename or 'file')
            fpath = os.path.join(save_dir, fname)
            await dw.save_as(fpath)
            download_path = fpath
            print(f'[Browser] ✅ 下载完成: {fpath}')
        except Exception as e:
            print(f'[Browser] ❌ 下载失败: {e}')
        return download_path

    # ===== 原生操作（不经过 LLM，直接调 Playwright）=====

    async def goto(self, url, wait_until="domcontentloaded"):
        """导航到指定URL（同 open，但可指定等待策略）"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 导航: {url}")
        await page.goto(url, wait_until=wait_until)
        await asyncio.sleep(1)

    async def type_text(self, selector, text, delay=0):
        """逐字符输入文本（触发前端框架的状态更新，如React/Vue）"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 输入文本: {selector} <- {text}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.click()
        await asyncio.sleep(0.2)
        await loc.press("Control+a")
        await loc.press("Delete")
        await page.keyboard.type(text, delay=delay)
        print(f"[Browser] ✅ 输入完成")

    async def press_key(self, key):
        """按键，如 Enter / Tab / Escape / ArrowDown"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 按键: {key}")
        await page.keyboard.press(key)

    async def select_option(self, selector, value=None, label=None):
        """选择下拉框选项，可按value或label选"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 选择下拉: {selector}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        if value:
            await loc.select_option(value=value)
        elif label:
            await loc.select_option(label=label)
        print(f"[Browser] ✅ 选择完成")

    async def hover(self, selector):
        """鼠标悬停（触发悬停菜单等）"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 悬停: {selector}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        await loc.hover()
        print(f"[Browser] ✅ 悬停完成")

    async def scroll(self, direction="down", pixels=None):
        """滚动页面，direction=down/up/left/right，pixels=指定像素"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 滚动: {direction}" + (f" {pixels}px" if pixels else ""))
        if pixels:
            dx = pixels if direction == "right" else (-pixels if direction == "left" else 0)
            dy = pixels if direction == "down" else (-pixels if direction == "up" else 0)
            await page.mouse.wheel(dx, dy)
        else:
            await page.evaluate(f"window.scrollBy({{'top': {300 if direction == 'down' else -300}, 'behavior': 'smooth'}})")

    async def scroll_to_element(self, selector):
        """滚动到指定元素可见"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 滚动到元素: {selector}")
        loc = page.locator(selector).first
        await loc.scroll_into_view_if_needed()
        print(f"[Browser] ✅ 已滚动到元素")

    async def get_text(self, selector=None):
        """获取元素文本，不传selector则获取整页文本"""
        await self.start()
        page = self._sb.browser.page
        if selector:
            loc = page.locator(selector).first
            return await loc.text_content()
        else:
            return await page.inner_text("body")

    async def get_attribute(self, selector, attr):
        """获取元素属性"""
        await self.start()
        page = self._sb.browser.page
        loc = page.locator(selector).first
        return await loc.get_attribute(attr)

    async def is_visible(self, selector, timeout=3000):
        """检查元素是否可见"""
        await self.start()
        page = self._sb.browser.page
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    async def wait_for_selector(self, selector, state="visible", timeout=30000):
        """等待元素出现/消失/可点击"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 等待元素: {selector} ({state})")
        loc = page.locator(selector).first
        await loc.wait_for(state=state, timeout=timeout)
        print(f"[Browser] ✅ 元素已{state}")

    async def wait_for_url(self, url_pattern, timeout=30000):
        """等待URL变化（包含指定模式）"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 等待URL: {url_pattern}")
        await page.wait_for_url(url_pattern, timeout=timeout)
        print(f"[Browser] ✅ URL已匹配")

    async def switch_tab(self, index=-1):
        """切换浏览器标签页，index=-1表示切到最新打开的"""
        await self.start()
        ctx = self._sb.browser.context
        pages = ctx.pages
        if not pages:
            return False
        target = pages[index]
        await target.bring_to_front()
        self._sb.browser.page = target
        print(f"[Browser] 切换到标签页: {target.url}")
        return True

    async def close_tab(self, index=None):
        """关闭标签页，不传则关闭当前页"""
        await self.start()
        ctx = self._sb.browser.context
        pages = ctx.pages
        if len(pages) <= 1:
            return False
        target_idx = index if index is not None else len(pages) - 1
        await pages[target_idx].close()
        print(f"[Browser] 关闭标签页 #{target_idx}")

    async def execute_js(self, script):
        """执行JavaScript，返回结果"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 执行JS: {script[:80]}...")
        result = await page.evaluate(script)
        return result

    async def upload_file(self, selector, file_path):
        """上传文件"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 上传文件: {file_path}")
        loc = page.locator(selector).first
        await loc.set_input_files(file_path)
        print(f"[Browser] ✅ 上传完成")

    async def reload(self, wait_until="domcontentloaded"):
        """刷新页面"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 刷新页面")
        await page.reload(wait_until=wait_until)
        await asyncio.sleep(1)

    async def go_back(self):
        """后退"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 后退")
        await page.go_back()
        await asyncio.sleep(1)

    async def go_forward(self):
        """前进"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 前进")
        await page.go_forward()
        await asyncio.sleep(1)

    async def get_url(self):
        """获取当前页面URL"""
        await self.start()
        return self._sb.browser.page.url

    async def get_title(self):
        """获取页面标题"""
        await self.start()
        return await self._sb.browser.page.title()

    # ===== 补全方法（对标影刀RPA xbot）=====

    async def wait(self, seconds=None, condition=None, timeout=30):
        """
        等待：传数字=等待秒数，传字符串=智能等待条件（LLM判断）
        兼容旧调用: b.wait("条件描述") 或 b.wait("条件描述", timeout=30)
        新调用: b.wait(3) 或 b.wait(condition="条件")
        """
        # 兼容旧调用: b.wait("条件描述") → seconds 是字符串，转给 condition
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
            await self._sb.smart_wait(condition, timeout=timeout)
            return

    async def sleep(self, seconds):
        """简单等待N秒"""
        print(f"[Browser] 等待 {seconds} 秒")
        await asyncio.sleep(seconds)

    async def double_click(self, selector, timeout=5000):
        """双击元素"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 双击: {selector}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.dblclick(timeout=timeout)
        print(f"[Browser] ✅ 双击完成")

    async def right_click(self, selector, timeout=5000):
        """右键点击元素"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 右键: {selector}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click(button="right", timeout=timeout)
        print(f"[Browser] ✅ 右键完成")

    async def check(self, selector, timeout=5000):
        """勾选复选框"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 勾选: {selector}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.check(timeout=timeout)
        print(f"[Browser] ✅ 已勾选")

    async def uncheck(self, selector, timeout=5000):
        """取消勾选复选框"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 取消勾选: {selector}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.uncheck(timeout=timeout)
        print(f"[Browser] ✅ 已取消勾选")

    async def drag(self, from_selector, to_selector, timeout=5000):
        """拖拽元素：从 A 拖到 B"""
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 拖拽: {from_selector} -> {to_selector}")
        src = page.locator(from_selector).first
        dst = page.locator(to_selector).first
        await src.wait_for(state="visible", timeout=timeout)
        await dst.wait_for(state="visible", timeout=timeout)
        await src.drag_to(dst, timeout=timeout)
        print(f"[Browser] ✅ 拖拽完成")

    async def set_text(self, selector, text, timeout=5000):
        """
        直接设置元素值（不触发键盘事件，不触发前端框架状态更新）
        适用于非受控组件；React/Vue 等受控组件请用 type_text
        """
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 设值: {selector} <- {text}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.fill(text, timeout=timeout)
        print(f"[Browser] ✅ 设值完成")

    async def element_exists(self, selector, timeout=3000):
        """元素是否存在（不要求可见，只要DOM中有就返回True）"""
        await self.start()
        page = self._sb.browser.page
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="attached", timeout=timeout)
            return True
        except Exception:
            return False

    async def element_count(self, selector):
        """获取匹配元素的数量"""
        await self.start()
        page = self._sb.browser.page
        loc = page.locator(selector)
        return await loc.count()

    async def screenshot_element(self, selector, name=None):
        """对单个元素截图"""
        await self.start()
        page = self._sb.browser.page
        import time as _t
        name = name or f"element_{_t.strftime('%Y%m%d_%H%M%S')}"
        print(f"[Browser] 元素截图: {selector}")
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=10000)
        path = f"screenshots/{name}.png"
        os.makedirs("screenshots", exist_ok=True)
        await loc.screenshot(path=path)
        print(f"[Browser] ✅ 截图已保存: {path}")
        return path

    async def screenshot_full(self, name=None):
        """整页截图"""
        await self.start()
        page = self._sb.browser.page
        import time as _t
        name = name or f"fullpage_{_t.strftime('%Y%m%d_%H%M%S')}"
        path = f"screenshots/{name}.png"
        os.makedirs("screenshots", exist_ok=True)
        await page.screenshot(path=path, full_page=True)
        print(f"[Browser] ✅ 整页截图: {path}")
        return path

    async def new_tab(self, url=None):
        """新建标签页（可指定URL）"""
        await self.start()
        ctx = self._sb.browser.context
        page = await ctx.new_page()
        if url:
            await page.goto(url)
        await page.bring_to_front()
        self._sb.browser.page = page
        print(f"[Browser] 新建标签页: {page.url}")
        return page

    async def switch_to_frame(self, selector):
        """
        切换到指定 iframe
        selector 可以是 iframe 的 CSS 选择器、name 属性或 URL 匹配
        """
        await self.start()
        page = self._sb.browser.page
        print(f"[Browser] 切换到 iframe: {selector}")
        # Playwright 的 frame 操作：通过 selector 定位 iframe 元素
        frame = page.frame_locator(selector)
        # 把 frame 存起来，后续操作需要用这个 frame 而不是 page
        self._current_frame = frame
        print(f"[Browser] ✅ 已切换到 iframe")

    async def switch_to_main_frame(self):
        """从 iframe 切回主页面"""
        await self.start()
        self._current_frame = None
        print(f"[Browser] ✅ 已切回主页面")

    async def get_cookies(self):
        """获取当前页面所有Cookie"""
        await self.start()
        ctx = self._sb.browser.context
        return await ctx.cookies()

    async def set_cookie(self, name, value, domain=None, path="/"):
        """设置单个Cookie"""
        await self.start()
        ctx = self._sb.browser.context
        cookie = {"name": name, "value": value, "path": path}
        if domain:
            cookie["domain"] = domain
        await ctx.add_cookies([cookie])
        print(f"[Browser] ✅ Cookie已设置: {name}={value}")

    async def delete_cookies(self, name=None):
        """删除Cookie，不传name则删除全部"""
        await self.start()
        ctx = self._sb.browser.context
        if name:
            await ctx.clear_cookies(name=name)
            print(f"[Browser] ✅ 已删除Cookie: {name}")
        else:
            await ctx.clear_cookies()
            print(f"[Browser] ✅ 已清空所有Cookie")

    async def download_file(self, url, save_path=None, timeout=120):
        """
        直接通过URL下载文件（不需要点击按钮）
        用浏览器上下文发起请求，自动带Cookie
        """
        await self.start()
        page = self._sb.browser.page
        import time as _t
        print(f"[Browser] URL下载: {url}")
        if not save_path:
            save_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"download_{_t.strftime('%Y%m%d_%H%M%S')}")
        try:
            # 用页面的请求上下文下载（自动带cookie）
            resp = await page.context.request.get(url, timeout=timeout * 1000)
            if resp.ok:
                body = await resp.body()
                with open(save_path, "wb") as f:
                    f.write(body)
                print(f"[Browser] ✅ 下载完成: {save_path} ({len(body)} bytes)")
                return save_path
            else:
                print(f"[Browser] ❌ 下载失败: HTTP {resp.status}")
                return None
        except Exception as e:
            print(f"[Browser] ❌ 下载失败: {e}")
            return None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *a):
        await self.close()
