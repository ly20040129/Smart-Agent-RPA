# -*- coding: utf-8 -*-
"""
滑块验证码工具类

用 ddddocr 识别拼图缺口位置 + Playwright 模拟真人拖动轨迹。
对应影刀的「滑块拼图验证免费版(web)」逻辑。

用法：
    from sdk.slider_captcha import SliderCaptcha

    # 在 workflow 中，关键操作后检测验证码
    page = await agent._get_page()
    captcha = SliderCaptcha(page)
    handled = await captcha.handle_if_present()
    if handled:
        logger.info("验证码已处理")

    # 自定义选择器（天猫默认选择器已内置，一般不需要改）
    captcha = SliderCaptcha(
        page,
        captcha_selector="div.slider-captcha",
        bg_selector="img.captcha-bg",
        slider_img_selector="img.captcha-slider",
        drag_selector="div.slider-btn",
        close_selector="span.captcha-close",
    )

依赖：
    pip install ddddocr
"""
import asyncio
import os
import tempfile
from typing import Optional

from loguru import logger

try:
    import ddddocr
    _HAS_DDDDOCR = True
except ImportError:
    _HAS_DDDDOCR = False

# ==================== 天猫默认选择器 ====================
# 这些是天猫阿里云盾（X5SEC）滑块验证码的常见选择器
# 实际可能需要根据页面调整，用 F12 手动触发验证码后确认
_TMALL_SELECTORS = {
    "captcha": "div#nc_1_wrapper, div.nc-container, div#smartCaptcha",
    "bg": "img#nc_bg, img.nc-bg, canvas",
    "slider_img": "img#nc_slider, img.nc-slider",
    "drag": "span#nc_1_n1z, span.btn_slide, div.nc-lang-cnt",
    "close": "a#nc_1_close, span.nc-close, div.close-btn",
}


class SliderCaptcha:
    """滑块验证码工具类"""

    def __init__(self, page, captcha_selector: str = "", bg_selector: str = "",
                 slider_img_selector: str = "", drag_selector: str = "",
                 close_selector: str = "", retry_count: int = 5,
                 offset: int = 0, move_speed: str = "fast"):
        """
        Args:
            page: Playwright Page 或 FrameLocator
            captcha_selector: 验证码弹窗选择器
            bg_selector: 背景图选择器（含缺口的图）
            slider_img_selector: 滑块拼图图片选择器
            drag_selector: 拖动按钮选择器
            close_selector: 验证码关闭按钮选择器
            retry_count: 最大重试次数
            offset: 缺口位置偏移补偿（像素），正数向右偏
            move_speed: "fast" 快速拖动 / "slow" 慢速带加速度
        """
        self.page = page
        self.captcha_selector = captcha_selector or _TMALL_SELECTORS["captcha"]
        self.bg_selector = bg_selector or _TMALL_SELECTORS["bg"]
        self.slider_img_selector = slider_img_selector or _TMALL_SELECTORS["slider_img"]
        self.drag_selector = drag_selector or _TMALL_SELECTORS["drag"]
        self.close_selector = close_selector or _TMALL_SELECTORS["close"]
        self.retry_count = retry_count
        self.offset = offset
        self.move_speed = move_speed

    # ==================== 主入口 ====================

    async def handle_if_present(self) -> bool:
        """检测验证码是否出现，出现则处理，否则关闭弹窗。

        对应影刀逻辑：
          if 验证码可见 → 滑块拼图验证
          else → 点击验证码关闭

        Returns:
            True = 处理了验证码 / False = 没有验证码或已关闭
        """
        if not _HAS_DDDDOCR:
            logger.warning("[Captcha] ddddocr 未安装，无法自动处理验证码。pip install ddddocr")
            return False

        # 检测验证码弹窗是否可见
        captcha_el = await self.page.query_selector(self.captcha_selector)
        if not captcha_el or not await captcha_el.is_visible():
            logger.debug("[Captcha] 未检测到验证码弹窗")
            # 尝试关闭可能残留的弹窗
            await self._try_close()
            return False

        logger.info("[Captcha] 检测到验证码弹窗，开始处理")
        return await self._solve_slider()

    # ==================== 滑块识别 + 拖动 ====================

    async def _solve_slider(self) -> bool:
        """识别缺口并拖动滑块，失败重试"""
        for attempt in range(1, self.retry_count + 1):
            logger.info(f"[Captcha] 第 {attempt}/{self.retry_count} 次尝试")

            try:
                # 1. 截取背景图和滑块图
                bg_bytes = await self._element_screenshot(self.bg_selector)
                slider_bytes = await self._element_screenshot(self.slider_img_selector)

                if not bg_bytes or not slider_bytes:
                    logger.warning("[Captcha] 截图失败，跳过本次")
                    continue

                # 2. 用 ddddocr 识别缺口位置
                ocr = ddddocr.DdddOcr(show_ad=False)
                result = ocr.slide_match(slider_bytes, bg_bytes, simple_target=True)
                target_x = result.get("target", [0, 0])[0]
                distance = target_x + self.offset
                logger.info(f"[Captcha] 缺口位置: x={target_x}, 偏移={self.offset}, 拖动距离={distance}")

                # 3. 拖动滑块
                await self._drag_slider(distance)

                # 4. 等待验证结果
                await asyncio.sleep(2)

                # 5. 检查验证码是否消失
                captcha_el = await self.page.query_selector(self.captcha_selector)
                if not captcha_el or not await captcha_el.is_visible():
                    logger.info("[Captcha] ✅ 验证码已通过")
                    return True

                logger.warning("[Captcha] 验证码仍在，可能拖动位置不准，重试")

            except Exception as e:
                logger.warning(f"[Captcha] 第 {attempt} 次处理异常: {e}")

            # 重试前等待一下
            if attempt < self.retry_count:
                await asyncio.sleep(1)

        logger.error(f"[Captcha] ❌ {self.retry_count} 次尝试均失败")
        await self._try_close()
        return False

    # ==================== 拖动轨迹模拟 ====================

    async def _drag_slider(self, distance: int):
        """模拟真人拖动滑块

        Args:
            distance: 拖动距离（像素）
        """
        drag_el = await self.page.query_selector(self.drag_selector)
        if not drag_el:
            logger.warning(f"[Captcha] 拖动按钮未找到: {self.drag_selector}")
            return

        box = await drag_el.bounding_box()
        if not box:
            logger.warning("[Captcha] 拖动按钮无 bounding_box")
            return

        # 滑块中心位置
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2

        # 移到滑块上 → 按下
        await self.page.mouse.move(start_x, start_y)
        await asyncio.sleep(0.2)
        await self.page.mouse.down()
        await asyncio.sleep(0.1)

        if self.move_speed == "fast":
            # 快速拖动：3-5 步
            steps = 5
            for i in range(1, steps + 1):
                progress = i / steps
                # 加一点随机抖动
                jitter = (i % 2 * 2 - 1)  # -1 或 1
                move_x = start_x + distance * progress + jitter
                move_y = start_y + (i % 3 - 1)  # 微小 Y 抖动
                await self.page.mouse.move(move_x, move_y)
                await asyncio.sleep(0.05)
        else:
            # 慢速拖动：带加速度变化（先慢后快再慢）
            steps = 10
            for i in range(1, steps + 1):
                # ease-in-out 缓动函数
                t = i / steps
                if t < 0.5:
                    ease = 2 * t * t
                else:
                    ease = 1 - (-2 * t + 2) ** 2 / 2
                move_x = start_x + distance * ease
                move_y = start_y + (i % 3 - 1) * 0.5
                await self.page.mouse.move(move_x, move_y)
                await asyncio.sleep(0.1)

        # 释放
        await asyncio.sleep(0.1)
        await self.page.mouse.up()

    # ==================== 辅助方法 ====================

    async def _element_screenshot(self, selector: str) -> Optional[bytes]:
        """截取指定元素的截图，返回 PNG bytes"""
        el = await self.page.query_selector(selector)
        if not el:
            logger.debug(f"[Captcha] 元素未找到: {selector}")
            return None
        return await el.screenshot()

    async def _try_close(self):
        """尝试点击验证码关闭按钮"""
        close_el = await self.page.query_selector(self.close_selector)
        if close_el and await close_el.is_visible():
            await close_el.click()
            logger.info("[Captcha] 已关闭验证码弹窗")
            await asyncio.sleep(1)
