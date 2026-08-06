"""
浏览器控制工具 - 基于Playwright的网页自动化
"""
import asyncio
import time
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright, Browser, Page, BrowserContext, Error as PlaywrightError

from src.core.config import get_config

# 存储模块（懒加载，可选）
try:
    from src.storage import storage_manager
    HAS_STORAGE = True
except ImportError:
    HAS_STORAGE = False


class BrowserController:
    """
    浏览器控制器
    
    功能：
    1. 封装Playwright，提供稳定的浏览器自动化能力
    2. 支持扫码登录等人工介入场景
    3. 智能等待和元素检测
    4. 异常自动重试
    5. 截图和日志记录
    """
    
    def __init__(self):
        """初始化浏览器控制器"""
        self.config = get_config()
        self.browser_config = self.config.browser
        
        # 浏览器实例
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # 登录等待回调函数
        self.login_callback: Optional[Callable] = None

        # Cookie持久化配置
        self.cookie_domain: Optional[str] = None  # 当前任务的cookie域名标识
        self._page_url_for_cookies: str = ""      # 用于提取域名
        
        logger.info("浏览器控制器初始化完成")
    
    async def start(self, headless: Optional[bool] = None) -> None:
        """
        启动浏览器
        
        Args:
            headless: 是否无头模式，如果不指定则使用配置文件中的设置
        """
        try:
            # 启动Playwright
            self.playwright = await async_playwright().start()
            
            # 根据配置选择浏览器类型
            browser_type = self.browser_config.browser_type
            headless = headless if headless is not None else self.browser_config.headless
            
            logger.info(f"正在启动浏览器: {browser_type}, headless={headless}")
            
            # 启动浏览器
            if browser_type == "chromium":
                self.browser = await self.playwright.chromium.launch(
                    headless=headless,
                    args=self.browser_config.args,
                    slow_mo=self.browser_config.slow_mo
                )
            elif browser_type == "firefox":
                self.browser = await self.playwright.firefox.launch(
                    headless=headless,
                    args=self.browser_config.args,
                    slow_mo=self.browser_config.slow_mo
                )
            elif browser_type == "webkit":
                self.browser = await self.playwright.webkit.launch(
                    headless=headless,
                    args=self.browser_config.args,
                    slow_mo=self.browser_config.slow_mo
                )
            else:
                raise ValueError(f"不支持的浏览器类型: {browser_type}")
            
            # 创建上下文（可在这里设置cookies、user-agent等）
            self.context = await self.browser.new_context()

            # 从Redis恢复cookie（如果配置了）
            if HAS_STORAGE and self.cookie_domain:
                await self._restore_cookies()

            # 创建页面
            self.page = await self.context.new_page()

            logger.info("浏览器启动成功")
            
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            raise
    
    async def close(self) -> None:
        """关闭浏览器"""
        try:
            # 关闭前保存cookie到Redis
            if HAS_STORAGE and self.cookie_domain and self.context:
                await self._save_cookies()

            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            logger.info("浏览器已关闭")
            
        except Exception as e:
            logger.error(f"关闭浏览器时出错: {e}")
    

    def set_cookie_domain(self, domain: str) -> None:
        """
        设置当前任务的cookie域名标识

        在任务开始前调用，start()时会自动恢复cookie，close()时会自动保存cookie

        Args:
            domain: 域名标识，如 'wechat_pay', 'jd_shop'
        """
        self.cookie_domain = domain
        logger.info(f"Cookie持久化域名标识: {domain}")

    async def _save_cookies(self) -> bool:
        """保存当前浏览器cookie到Redis"""
        if not self.context or not self.cookie_domain:
            return False
        try:
            cookies = await self.context.cookies()
            if cookies and HAS_STORAGE:
                storage_manager.save_cookies(self.cookie_domain, cookies)
                return True
        except Exception as e:
            logger.warning(f"保存cookie失败: {e}")
        return False

    async def _restore_cookies(self) -> bool:
        """从Redis恢复cookie到浏览器"""
        if not self.context or not self.cookie_domain:
            return False
        try:
            if HAS_STORAGE:
                cookies = storage_manager.load_cookies(self.cookie_domain)
                if cookies:
                    await self.context.add_cookies(cookies)
                    logger.info(f"Cookie已恢复: {self.cookie_domain} ({len(cookies)}条)")
                    return True
                else:
                    logger.info(f"Redis中无Cookie: {self.cookie_domain}，需要手动登录")
        except Exception as e:
            logger.warning(f"恢复cookie失败: {e}")
        return False

    async def navigate(self, url: str) -> None:
        """
        导航到指定URL
        
        Args:
            url: 目标URL
        """
        if not self.page:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        
        try:
            logger.info(f"正在导航到: {url}")
            await self.page.goto(url, timeout=self.browser_config.timeout)
            logger.info("页面加载完成")
            
        except PlaywrightError as e:
            logger.error(f"导航失败: {e}")
            if self.browser_config.screenshot_on_error:
                await self.screenshot("navigation_error")
            raise
    
    async def wait_for_element(
        self,
        selector: str,
        timeout: Optional[int] = None,
        state: str = "visible"
    ) -> bool:
        """
        等待元素出现
        
        Args:
            selector: CSS选择器
            timeout: 超时时间（毫秒）
            state: 元素状态 ("visible", "hidden", "attached", "detached")
            
        Returns:
            是否找到元素
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")
        
        timeout = timeout or self.browser_config.timeout
        
        try:
            await self.page.wait_for_selector(selector, timeout=timeout, state=state)
            logger.info(f"元素已找到: {selector}")
            return True
            
        except PlaywrightError as e:
            logger.warning(f"等待元素超时: {selector}, {e}")
            return False
    
    async def click(
        self,
        selector: str,
        timeout: Optional[int] = None,
        force: bool = False
    ) -> bool:
        """
        点击元素
        
        Args:
            selector: CSS选择器
            timeout: 超时时间
            force: 是否强制点击（即使元素不可见）
            
        Returns:
            是否成功点击
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")
        
        try:
            await self.page.click(selector, timeout=timeout or self.browser_config.timeout, force=force)
            logger.info(f"已点击元素: {selector}")
            return True
            
        except PlaywrightError as e:
            logger.error(f"点击元素失败: {selector}, {e}")
            if self.browser_config.screenshot_on_error:
                await self.screenshot("click_error")
            return False
    
    async def fill_text(self, selector: str, text: str, timeout: Optional[int] = None) -> bool:
        """
        填充文本
        
        Args:
            selector: CSS选择器
            text: 要填充的文本
            timeout: 超时时间
            
        Returns:
            是否成功填充
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")
        
        try:
            await self.page.fill(selector, text, timeout=timeout or self.browser_config.timeout)
            logger.info(f"已填充文本到元素: {selector}")
            return True
            
        except PlaywrightError as e:
            logger.error(f"填充文本失败: {selector}, {e}")
            return False
    
    async def get_text(self, selector: str) -> Optional[str]:
        """
        获取元素文本内容
        
        Args:
            selector: CSS选择器
            
        Returns:
            元素文本内容
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")
        
        try:
            text = await self.page.text_content(selector)
            return text
            
        except PlaywrightError as e:
            logger.error(f"获取文本失败: {selector}, {e}")
            return None
    
    async def screenshot(self, name: str = "screenshot") -> str:
        """
        截图
        
        Args:
            name: 截图名称
            
        Returns:
            截图文件路径
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")
        
        try:
            # 创建截图目录
            screenshot_dir = Path("data/screenshots")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{name}_{timestamp}.png"
            filepath = screenshot_dir / filename
            
            # 截图
            await self.page.screenshot(path=str(filepath))
            
            logger.info(f"截图已保存: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"截图失败: {e}")
            return ""
    
    async def wait_for_login(
        self,
        check_selector=None,
        timeout: int = 300,
        message: str = "请完成登录操作",
        expected_url=None
    ) -> bool:
        """
        等待人工完成登录（支持扫码等方式）

        支持多种检测方式，任意一种成功即判定登录成功：
        1. 元素检测 - check_selector 可以是字符串或列表
        2. URL关键词 - 登录后URL中包含 expected_url 即判定成功
        3. 自动URL检测 - 不传任何条件时，自动判断URL是否变化

        Args:
            check_selector: 登录成功后的元素选择器，支持 str 或 list
            timeout: 等待超时时间（秒）
            message: 提示消息
            expected_url: 登录成功后URL中应包含的关键词（可选）

        Returns:
            是否成功登录
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")

        # 统一处理 check_selector 为列表
        if check_selector is None:
            selectors = []
        elif isinstance(check_selector, str):
            selectors = [check_selector]
        else:
            selectors = list(check_selector)

        logger.info(f"等待人工登录: {message}")
        logger.info(f"  检测选择器: {selectors if selectors else '无'}")
        logger.info(f"  期望URL关键词: {expected_url if expected_url else '自动检测URL变化'}")

        # 记录登录前的URL，用于自动检测变化
        login_url = self.page.url
        logger.info(f"  登录前URL: {login_url}")

        # 如果设置了回调函数，调用它通知Web界面
        if self.login_callback:
            await self.login_callback({
                "type": "login_required",
                "message": message,
                "timeout": timeout
            })

        # 截图并保存，用于Web界面显示
        screenshot_path = await self.screenshot("login_required")

        start_time = time.time()

        while True:
            elapsed = time.time() - start_time

            # 检查是否超时
            if elapsed > timeout:
                logger.error(f"登录等待超时（{timeout}秒）")
                await self.screenshot("login_timeout")
                logger.info(f"  超时时的URL: {self.page.url}")
                return False

            current_url = self.page.url

            # 检测方式1: URL关键词匹配
            if expected_url and expected_url in current_url:
                logger.info(f"登录成功（URL匹配: {expected_url}）")
                return True

            # 检测方式2: 自动URL变化检测（无选择器且无expected_url时）
            if not selectors and not expected_url:
                if current_url != login_url:
                    logger.info(f"登录成功（URL已变化）")
                    logger.info(f"  新URL: {current_url}")
                    await asyncio.sleep(2)
                    return True

            # 检测方式3: 元素选择器检测
            for selector in selectors:
                try:
                    element = await self.page.wait_for_selector(
                        selector,
                        timeout=3000,
                        state="visible"
                    )
                    if element:
                        logger.info(f"登录成功（找到元素: {selector}）")
                        return True
                except:
                    pass

            # 每10秒输出一次等待日志
            if int(elapsed) > 0 and int(elapsed) % 10 == 0:
                logger.info(f"等待登录中... 已等待 {int(elapsed)}秒, 当前URL: {current_url}")

            await asyncio.sleep(2)

    async def download_file(
        self,
        download_selector: str,
        save_path: Optional[str] = None,
        timeout: int = 60000
    ) -> Optional[str]:
        """
        下载文件
        
        Args:
            download_selector: 下载按钮选择器
            save_path: 保存路径（可选）
            timeout: 下载超时时间
            
        Returns:
            下载文件路径
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")
        
        try:
            logger.info("开始下载文件...")
            
            # 监听下载事件
            async with self.page.expect_download(timeout=timeout) as download_info:
                await self.page.click(download_selector)
            
            download = await download_info.value
            
            # 确定保存路径
            if save_path:
                filepath = Path(save_path)
            else:
                # 默认保存到 data/downloads 目录
                download_dir = Path("data/downloads")
                download_dir.mkdir(parents=True, exist_ok=True)
                filepath = download_dir / download.suggested_filename
            
            # 保存文件
            await download.save_as(filepath)
            
            logger.info(f"文件下载成功: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"文件下载失败: {e}")
            if self.browser_config.screenshot_on_error:
                await self.screenshot("download_error")
            return None
    
    async def execute_script(self, script: str) -> Any:
        """
        执行JavaScript脚本
        
        Args:
            script: JavaScript代码
            
        Returns:
            脚本执行结果
        """
        if not self.page:
            raise RuntimeError("浏览器未启动")
        
        try:
            result = await self.page.evaluate(script)
            logger.info("JavaScript执行成功")
            return result
            
        except Exception as e:
            logger.error(f"JavaScript执行失败: {e}")
            return None
    
    def set_login_callback(self, callback: Callable) -> None:
        """
        设置登录等待回调函数
        
        Args:
            callback: 回调函数，用于通知Web界面需要人工介入
        """
        self.login_callback = callback
        logger.info("登录回调函数已设置")


# 使用示例
if __name__ == "__main__":
    async def test_browser():
        """测试浏览器控制器"""
        controller = BrowserController()
        
        try:
            # 启动浏览器
            await controller.start()
            
            # 导航到微信支付登录页
            await controller.navigate("https://pay.weixin.qq.com/")
            
            # 等待人工扫码登录
            print("请在浏览器中完成扫码登录...")
            logged_in = await controller.wait_for_login(
                check_selector=".header-user-info",  # 假设的登录成功元素
                timeout=120,
                message="请使用微信扫码登录"
            )
            
            if logged_in:
                print("登录成功!")
                # 继续执行后续操作...
            else:
                print("登录超时")
                
        finally:
            await controller.close()
    
    # 运行测试
    asyncio.run(test_browser())