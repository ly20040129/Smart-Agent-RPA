# -*- coding: utf-8 -*-
"""
智能浏览器模块 - LLM驱动的浏览器操作

核心区别：
  传统RPA:  browser.click("#btn-download")        ← 写死选择器，页面一改就废
  智能体:   browser.smart_click("下载业务明细账单")  ← LLM看页面元素，自己找到按钮

LLM的参与方式：
  1. 提取页面所有可交互元素（按钮、链接、输入框）的文本和属性
  2. 把元素列表 + 用户意图 发给LLM
  3. LLM返回应该操作哪个元素
  4. 执行操作

这样即使页面改版、元素ID变化，只要文字还在，就能正常工作。
"""
import json
import time
import asyncio
from typing import Optional, Dict, Any, List
from loguru import logger

from src.core.llm_client import LocalLLMClient
from src.tools.browser_controller import BrowserController


class SmartBrowser:
    """
    智能浏览器 - LLM是大脑，Playwright是手脚

    用法对比：
        # 传统方式（写死，脆弱）
        await browser.click("a.menu-item-trade")
        await browser.click("text=资金账单")

        # 智能方式（LLM理解，健壮）
        await smart_browser.smart_click("进入交易中心")
        await smart_browser.smart_click("点击资金账单")
    """

    def __init__(
        self,
        browser: Optional[BrowserController] = None,
        llm: Optional[LocalLLMClient] = None
    ):
        self.browser = browser or BrowserController()
        self.llm = llm or LocalLLMClient()

    async def start(self, headless: bool = False):
        """启动浏览器"""
        await self.browser.start(headless=headless)

    async def close(self):
        """关闭浏览器"""
        await self.browser.close()

    async def navigate(self, url: str):
        """导航到URL"""
        await self.browser.navigate(url)
        await self._wait_page_stable()

    async def _switch_to_latest_page_if_needed(self) -> None:
        """
        检测是否有新tab打开，如果有则切换到最新的tab

        解决问题实例：
        京东等网站点击"实销实结明细"等链接时会打开新tab，
        但代码还在操作旧tab，导致找不到新页面里的查询按钮、表格等元素
        """
        try:
            if not self.browser.context:
                return
            pages = self.browser.context.pages
            if len(pages) <= 1:
                return  # 只有一个tab，不需要切换

            # 找到最新的page（不是当前page）
            current_page = self.browser.page
            latest_page = pages[-1]  # 最后一个通常是最新的
            if latest_page != current_page:
                logger.info(f"检测到新tab，切换到最新页面: {latest_page.url}")
                self.browser.page = latest_page
                # 等待新页面加载
                await self._wait_page_stable(timeout=8000)
        except Exception as e:
            logger.debug(f"切换tab检查失败: {e}")

    async def _wait_page_stable(self, timeout: int = 5000) -> None:
        """
        等待页面达到稳定状态

        解决核心问题：
          页面导航/跳转时执行 page.evaluate() 会报
          "Execution context was destroyed, most likely because of a navigation"

        策略：
          1. 先等 domcontentloaded（DOM解析完成）
          2. 再短暂等 networkidle（网络请求平息），但不强制（有些页面持续轮询：比如pdd视频自动上传页面）
          3. 全部用try/except包裹，超时就忽略（不能让等待阻塞整个流程）
        """
        page = self.browser.page
        if not page:
            return

        # 等DOM加载完成（最基础，必须等！）
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=timeout)
        except Exception:
            pass

        # 等网络空闲（更彻底，但有些spa页面永远不空闲，所以宽容处理）
        try:
            await page.wait_for_load_state('networkidle', timeout=2000)
        except Exception:
            pass  # networkidle超时是正常的，不阻塞

    async def get_page_elements(self) -> List[Dict[str, Any]]:
        """
        提取当前页面所有可交互元素

        这是LLM"看"页面的方式：
        提取按钮、链接、输入框的文本、属性、位置
        然后把这些信息给LLM，让它决定操作哪个

        Returns:
            元素列表，每个元素包含:
            - type: 元素类型 (button/link/input/a)后续可以添加配置
            - text: 显示文本
            - selector: CSS选择器（用于后续点击）
            - attributes: 关键属性
        """
        if not self.browser.page:
            raise RuntimeError("浏览器未启动")

        # 等待页面稳定，避免在导航中执行evaluate导致context被销毁
        await self._wait_page_stable()

        # JavaScript提取页面可交互元素
        script = r"""
        () => {
            const elements = [];
            
            // 提取按钮
            document.querySelectorAll('button, [role="button"], .btn, input[type="button"], input[type="submit"]').forEach(el => {
                const text = (el.innerText || el.textContent || el.value || '').replace(/\s+/g, ' ').trim();
                if (text) {
                    elements.push({
                        type: 'button',
                        text: text.substring(0, 100),
                        normalized_text: text.replace(/\s/g, ''),
                        selector: el.id ? '#' + el.id : '',
                        classes: el.className || '',
                        visible: el.offsetParent !== null
                    });
                }
            });
            
            // 提取链接
            document.querySelectorAll('a[href]').forEach(el => {
                const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                if (text && text.length < 100) {
                    elements.push({
                        type: 'link',
                        text: text,
                        normalized_text: text.replace(/\s/g, ''),
                        href: el.href,
                        selector: el.id ? '#' + el.id : '',
                        classes: el.className || '',
                        visible: el.offsetParent !== null
                    });
                }
            });
            
            // 提取可点击的菜单项、标签页（扩大选择器范围）
            document.querySelectorAll(
                '.menu-item, .nav-item, .tab, li[role="tab"], .ant-menu-item, .el-menu-item, '
                + '[role="menuitem"], [role="menu"], '
                + 'li, span, div, a'
            ).forEach(el => {
                // 只取有文字且可点击的
                const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                if (text && text.length > 0 && text.length < 50) {
                    // 去重：如果文字已经被button/link抓过就跳过
                    const exists = elements.some(e => e.text === text);
                    if (!exists) {
                        // 检查是否可点击或可交互
                        const hasClick = el.onclick || el.getAttribute('role') === 'menuitem' 
                            || el.classList.toString().includes('menu') 
                            || el.classList.toString().includes('nav')
                            || el.classList.toString().includes('item')
                            || el.tagName === 'LI';
                        if (hasClick || el.offsetParent !== null) {
                            elements.push({
                                type: 'menu',
                                text: text,
                                normalized_text: text.replace(/\s/g, ''),
                                selector: el.id ? '#' + el.id : '',
                                classes: el.className || '',
                                visible: el.offsetParent !== null
                            });
                        }
                    }
                }
            });

            // 只返回可见元素
            return elements.filter(e => e.visible);
        }
        """

        # 遍历主页+所有iframe，收集所有可交互元素
        # 京东等后台页面的查询按钮、表格、分页常在iframe里，只搜主页面会全部漏掉
        #该死的iframe

        all_elements = []

        # 等待iframe加载（如：京东页面点击后iframe需要时间加载）
        await asyncio.sleep(1.5)

        frames = self.browser.page.frames  # 包含main_frame
        logger.debug(f"当前页面有 {len(frames)} 个frame（主页+iframe）")
        for frame_idx, frame in enumerate(frames):
            try:
                frame_url = frame.url
                # 跳过about:blank的空frame
                if frame_url == 'about:blank':
                    logger.debug(f"  frame#{frame_idx}: about:blank，跳过")
                    continue

                frame_elements = None
                for attempt in range(3):  # 增加重试次数到3
                    try:
                        frame_elements = await frame.evaluate(script)
                        break
                    except Exception as e:
                        if "destroyed" in str(e) or "Target closed" in str(e) or "navigation" in str(e).lower():
                            await asyncio.sleep(1.5)
                            await self._wait_page_stable()
                        else:
                            # 非导航错误，可能是跨域frame，跳过
                            logger.debug(f"  frame#{frame_idx} evaluate失败: {e}")
                            break
                if frame_elements:
                    for el in frame_elements:
                        el['frame_idx'] = frame_idx  # 记录元素所在frame，点击时要用
                    all_elements.extend(frame_elements)
                    logger.debug(f"  frame#{frame_idx} ({frame_url[:50]}): 提取到 {len(frame_elements)} 个元素")
                else:
                    logger.debug(f"  frame#{frame_idx} ({frame_url[:50]}): 无元素")
            except Exception as e:
                logger.debug(f"frame#{frame_idx} 提取元素失败: {e}")

        # 如果只提取到主页元素（没有iframe元素），可能是iframe还在加载
        # 再等2秒重试一次
        if len(frames) <= 1 or all(len(e.get('text','')) > 0 and e.get('frame_idx',0)==0 for e in all_elements[:50]):
            logger.debug("可能iframe还在加载，等待2秒后重试...")
            await asyncio.sleep(2)
            frames = self.browser.page.frames
            if len(frames) > 1:
                for frame_idx, frame in enumerate(frames):
                    if frame_idx == 0:
                        continue  # 跳过主页，已经提取过了
                    try:
                        if frame.url == 'about:blank':
                            continue
                        frame_elements = await frame.evaluate(script)
                        if frame_elements:
                            for el in frame_elements:
                                el['frame_idx'] = frame_idx
                            all_elements.extend(frame_elements)
                            logger.debug(f"  重试 frame#{frame_idx}: 提取到 {len(frame_elements)} 个元素")
                    except Exception:
                        continue

        # 为每个元素生成多种备选选择器（优先文本/属性，最可靠）
        for i, el in enumerate(all_elements):
            selectors = self._build_selectors(el, i)
            el['selectors'] = selectors  # 多种备选，按优先级排
            el['selector'] = selectors[0] if selectors else f'text={el.get("text","")}'

        logger.info(f"提取到 {len(all_elements)} 个可交互元素（含iframe）")
        return all_elements

    def _build_selectors(self, element: Dict, index: int) -> List[str]:
        """
        为元素生成多种备选选择器（按优先级从高到低）
        1. ID选择器       → 最可靠
        2. text=文本匹配   → 改版也能命中（Playwright自带）
        3. [text=xxx] nth  → 文本+序号兜底
        4. href选择器       → 链接场景
        """
        selectors = []
        text = (element.get('text') or '').strip()
        href = element.get('href') or ''
        elem_id = element.get('selector') or ''  # 有ID时这个是非空

        if elem_id.startswith('#'):
            selectors.append(elem_id)

        if text and len(text) <= 30:
            # 转义特殊字符
            safe_text = text.replace("'", "\'")
            selectors.append(f"text='{safe_text}'")
            # 模糊匹配，兼容空格差异
            selectors.append(f":has-text('{safe_text}')")

        if element.get('type') == 'link' and href and not href.startswith('javascript:'):
            # 精确href匹配或href包含
            selectors.append(f"a[href='{href}']")
            if len(href) > 20:
                selectors.append(f"a[href*='{href[-20:]}']")

        # 最后兜底: 按类型+索引
        tag_map = {'button': 'button', 'link': 'a', 'menu': 'li'}
        tag = tag_map.get(element.get('type', ''), 'a')
        selectors.append(f"{tag}:has-text('{(text[:10] or '').replace(chr(39), chr(34))}')")

        # 去重保留顺序
        seen = set()
        unique = []
        for s in selectors:
            if s and s not in seen:
                seen.add(s)
                unique.append(s)
        return unique or [f'text={text or "empty"}']

    async def smart_click(
        self,
        intent: str,
        timeout: int = 10000
    ) -> bool:
        """
        智能点击 - 两段式选择（一定程度上提高速率）
          第一段：本地关键词匹配（快速可靠，无LLM调用）
          第二段：命中不确定时才调用LLM
        点击时：遍历多种备选选择器，直到成功

        Args:
            intent: 操作意图，如 "点击资金账单"
            timeout: 总超时时间

        Returns:
            是否成功点击
        """
        logger.info(f"智能点击: {intent}")

        # 1. 提取页面元素
        elements = await self.get_page_elements()
        if not elements:
            logger.warning("页面无可用元素")
            return False

        # 2. 打印前15个元素（调试用，方便排查）
        logger.debug("页面元素概览:")
        for i, el in enumerate(elements[:15]):
            logger.debug(f"  [{i}] [{el['type']}] {el.get('text','')[:30]}")

        # 3. 第一段：本地关键词匹配
        target_idx = self._rule_based_match(intent, elements)
        used_method = "rule"

        if target_idx is None:
            # 4. 第二段：LLM选择
            target_idx = await self._llm_select_index(intent, elements)
            used_method = "llm"

        if target_idx is None or target_idx < 0:
            logger.warning(f"未找到匹配元素: {intent}")
            logger.warning("  所有元素（前40条）:")
            for i, el in enumerate(elements[:40]):
                logger.warning(f"    [{i}] [frame={el.get('frame_idx',0)}] {el.get('text','')[:40]}")
            return False

        target = elements[target_idx]
        logger.info(f"匹配元素[{used_method}]: index={target_idx}, text={target.get('text','')}, selectors={target.get('selectors', [])}")

        # 5. 多策略点击：按优先级尝试所有备选选择器
        # 根据元素所在frame选择点击上下文（iframe里的元素要用frame点击）
        selectors = target.get('selectors', [target.get('selector', '')])
        frame_idx = target.get('frame_idx', 0)
        frames = self.browser.page.frames
        click_ctx = frames[frame_idx] if frame_idx < len(frames) else self.browser.page
        for i, sel in enumerate(selectors):
            logger.info(f"  尝试点击 #{i+1}: {sel}" + (f" (frame#{frame_idx})" if frame_idx else ""))
            try:
                success = await self._click_with_smart_fallback(sel, timeout=int(timeout/len(selectors)), ctx=click_ctx)
                if success:
                    # 点击后等待页面稳定（防止下一步evaluate时context被销毁）
                    await self._wait_page_stable()

                    # 检测是否有新tab打开（京东等网站点击链接常会新开tab）
                    await self._switch_to_latest_page_if_needed()

                    logger.info(f"✅ 智能点击成功: {intent} (selector#{i+1})")
                    return True
            except Exception as e:
                logger.debug(f"  点击 #{i+1} 失败: {e}")

        logger.error(f"❌ 智能点击失败: {intent}（所有备选选择器均失败）")
        await self.browser.screenshot("click_failed")
        return False

    def _rule_based_match(self, intent: str, elements: List[Dict]) -> Optional[int]:
        """
        本地关键词匹配 - 纯规则，快速可靠，不调用LLM

        匹配思路：
          - 计算意图关键词与元素文本的重合度
          - 排除"退出/注销/帮助/设置"等危险元素
          - 只有当最高分显著时才返回，否则交给LLM
        """
        import re
        # 把意图拆成关键词（中文按2-gram，数字和英文词保留）
        intent_clean = re.sub(r'[点击查看进入打开导航去]+', '', intent)
        intent_clean = intent_clean.strip()
        intent_normalized = re.sub(r'\s+', '', intent_clean)  # 去掉所有空格用于匹配

        # 危险词：命中了直接排除（一定要人工跑一次，提取危险因素，不然出问题了我可没办法）
        danger_words = ['退出', '注销', 'log out', 'logout', 'quit', '关闭', 'delete', '删除', '取消订单']

        scores = []
        for i, el in enumerate(elements):
            text = (el.get('text') or '').lower()
            text_norm = (el.get('normalized_text') or text).lower()
            score = 0

            # 危险排除
            if any(d in text for d in danger_words):
                scores.append(-1000)
                continue

            # 包含完整意图（用归一化文本匹配，忽略空格差异）
            if intent_clean and intent_clean in text:
                score += 100
            if intent_normalized and intent_normalized in text_norm:
                score += 200

            # 字符重合度（用归一化文本）
            overlap = len(set(intent_normalized) & set(text_norm))
            score += overlap * 2

            # 长度惩罚（避免太长的文本被误选）
            if len(text) > 60:
                score -= 10

            scores.append(score)

        if not scores:
            return None

        max_score = max(scores)
        if max_score < 10:
            return None  # 分数太低，交给LLM

        max_idx = scores.index(max_score)

        # 检查第二名差距，防止歧义
        sorted_scores = sorted(scores, reverse=True)
        if len(sorted_scores) >= 2 and sorted_scores[0] - sorted_scores[1] < 5:
            return None  # 第一名和第二名差距不大，交给LLM

        # 再次排除点击后会退出的元素
        target_text = (elements[max_idx].get('text') or '').lower()
        if any(d in target_text for d in ['退出', '注销', 'quit', 'logout']):
            return None

        return max_idx

    async def _click_with_smart_fallback(self, selector: str, timeout: int = 5000, ctx=None) -> bool:
        """单选择器点击，多策略（普通点击/force点击/JS点击）
        ctx: 点击上下文，可以是page或frame（iframe里的元素要传frame）
        """
        if ctx is None:
            ctx = self.browser.page
        if not ctx:
            return False

        # 策略1：普通点击
        try:
            await ctx.click(selector, timeout=timeout)
            return True
        except Exception:
            pass

        # 策略2：滚动到可见后force点击
        try:
            locator = ctx.locator(selector).first
            await locator.scroll_into_view_if_needed(timeout=2000)
            await locator.click(timeout=timeout, force=True)
            return True
        except Exception:
            pass

        # 策略3：JavaScript dispatchEvent（最暴力，有些不可见的直接就请求了）
        try:
            await ctx.evaluate(f"""(sel) => {{
                const el = document.querySelector(sel);
                if (el) {{ el.click(); return true; }}
                return false;
            }}""", selector)
            return True
        except Exception:
            return False

    async def _llm_select_index(
        self,
        intent: str,
        elements: List[Dict]
    ) -> Optional[int]:
        """
        LLM选择元素的索引（交给上层去执行多策略点击）

        特别强调：禁止选"退出登录/注销/关闭/删除"等破坏性操作
        """
        # 策略：先过滤出和intent相关的元素，再给LLM选
        # 解决问题1：主页面有200+元素，iframe里的查询按钮排到200+之后，LLM只看前80条看不到
        # 解决问题2：去除"父容器型"元素（如包含"结算管理 结算应付账 实销实结明细"的menu），保留精确的短文本link/button
        import re as _re_filter
        intent_clean = _re_filter.sub(r'[点击查看进入打开导航去：,。、的按钮链接种类]+', '', intent)
        intent_clean = _re_filter.sub(r'\s+', '', intent_clean)
        intent_chars = set(intent_clean) - set('点击查看进入打开导航去按钮链接')

        pre_candidates = []  # (orig_idx, element, match_score, type_priority)
        for i, el in enumerate(elements):
            text = el.get('text', '') or ''
            text_norm = el.get('normalized_text', '') or _re_filter.sub(r'\s+', '', text)
            common = set(text_norm) & intent_chars
            # 类型优先级：button(0) > link(1) > menu(2)
            type_priority = 0 if el.get('type') == 'button' else 1 if el.get('type') == 'link' else 2
            if common:
                # 计算更精确的匹配分：
                # - 完全包含（intent是text的子集）加20分
                # - 重合字符数加5分
                # - 类型优先级：link/button减5分
                score = len(common) * 5 + type_priority * (-5 if type_priority <= 1 else 0)
                if intent_clean and intent_clean in text_norm:
                    score += 20
                # 短文本加分（更精确，不是父容器）
                if len(text_norm) <= 12:
                    score += 10
                pre_candidates.append((i, el, score, type_priority))
            elif el.get('type') == 'button' and len(text) < 20:
                pre_candidates.append((i, el, 1, 0))

        # 按匹配分从高到低排序
        pre_candidates.sort(key=lambda x: -x[2])

        # 去重：如果一个短文本元素（A）的normalized_text，被另一个长文本元素（B）完全包含，则去掉B
        # 例如A="实销实结明细"，B="结算管理 结算应付账 实销实结明细"，则去掉B
        filtered = []
        for i, el, score, tp in pre_candidates:
            el_text_norm = el.get('normalized_text', '') or _re_filter.sub(r'\s+', '', el.get('text', '') or '')
            # 检查是否已存在更精确（更短）的元素包含了目标内容
            dominated = False
            for j, (existing_idx, existing_el, _, _) in enumerate(filtered):
                existing_norm = existing_el.get('normalized_text', '') or _re_filter.sub(r'\s+', '', existing_el.get('text', '') or '')
                # 如果已存在的元素text更短，且被当前元素包含，则当前元素是父容器，跳过
                if len(existing_norm) < len(el_text_norm) and existing_norm and existing_norm in el_text_norm:
                    dominated = True
                    break
                # 如果已存在的元素text更长，且包含当前元素，则替换（当前元素更精确）
                if len(el_text_norm) < len(existing_norm) and el_text_norm and el_text_norm in existing_norm:
                    filtered.pop(j)
                    break
            if not dominated:
                filtered.append((i, el, score, tp))

        candidates = [(i, el) for i, el, _, _ in filtered[:25]]

        # 构建简化列表（index是原始索引，LLM返回后直接用）
        simplified = []
        for orig_idx, el in candidates:
            simplified.append({
                "index": orig_idx,  # 用原始索引，LLM返回后直接定位
                "type": el.get("type", ""),
                "text": el.get("text", "")[:60],
                "href": el.get("href", "")[:80] if el.get("href") else ""
            })

        if not simplified:
            # 没有相关元素，退回到前80条
            for i, el in enumerate(elements[:80]):
                simplified.append({
                    "index": i,
                    "type": el.get("type", ""),
                    "text": el.get("text", "")[:60],
                    "href": el.get("href", "")[:80] if el.get("href") else ""
                })

        system_prompt = """你是一个网页操作助手。从元素列表中选择和用户意图最匹配的一项。

【重要规则 - 必须严格遵守】
1. 绝对不能选"退出登录/注销/关闭/删除/取消订单/重置"等破坏性操作，即便它们文本上有相似词
2. 【优先选择精确匹配】：选"文本最短、最直接对应用户意图"的元素。绝对不要选包含多个菜单项的"父容器"元素！
   - 例：用户要点击"实销实结明细"，元素1是"实销实结明细"（短），元素2是"结算管理 结算应付账 实销实结明细"（长，父容器）→ 必须选元素1
3. 优先选择 type=button 或 type=link 的元素，menu类型通常是父容器不是可点击目标
4. 只返回一个JSON：{"index": 数字, "reason": "理由"}
5. 如果实在找不到匹配元素，返回 {"index": -1}

示例：
用户意图: 点击资金账单
元素: [{"index":0,"text":"交易中心"},{"index":1,"text":"资金账单"},{"index":2,"text":"退出登录"},{"index":3,"text":"个人设置"},{"index":4,"text":"交易中心 资金账单 个人设置"}]
返回: {"index":1,"reason":"'资金账单'精确匹配用户意图，且是最短的独立元素，不要选父容器和破坏性操作"}
"""

        user_message = f"""用户意图: {intent}

元素列表（已过滤出与意图相关的元素）:
{json.dumps(simplified, ensure_ascii=False)}

请返回最匹配的元素索引。注意一定不要选择退出/注销/删除之类的破坏性操作。如果列表中没有和意图相关的元素，返回 {{"index": -1}}"""

        try:
            response = self.llm.chat(message=user_message, system_prompt=system_prompt)

            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start == -1:
                return None

            result = json.loads(response[json_start:json_end])
            idx = result.get("index", -1)
            reason = result.get("reason", "")

            if 0 <= idx < len(elements):
                text = elements[idx].get('text', '')
                el_type = elements[idx].get('type', '')
                # 最后一道防线：防止LLM选破坏性操作
                if any(w in text for w in ['退出', '注销', 'logout', 'quit', '删除', 'delete', '关闭']):
                    logger.warning(f"⚠️ LLM 倾向选择破坏性操作: {text}，已拒绝。理由={reason}")
                    return None

                # 相关性验证：LLM选中的元素text必须和intent有字符重合
                import re as _re_v
                intent_clean = _re_v.sub(r'[点击查看进入打开导航去：,。、的按钮链接种类]+', '', intent)
                intent_clean = _re_v.sub(r'\s+', '', intent_clean)
                text_norm = (elements[idx].get('normalized_text', '') or
                             _re_v.sub(r'\s+', '', text))
                common_chars = set(intent_clean) & set(text_norm) - set('点击查看进入打开导航去按钮链接')
                if not common_chars and intent_clean:
                    logger.warning(f"⚠️ LLM 选择与意图无关: intent='{intent}' selected='{text}'，已拒绝。理由={reason}")
                    return None

                # 父容器检测：如果选中的是menu类型，且text包含多个空格分隔的独立词组（>=3个词），
                # 且候选列表中存在更短的（<=12字）link/button包含目标词，则拒绝当前选择
                text_spaces = text.count(' ') + text.count('　') + text.count('\n')
                if el_type == 'menu' and text_spaces >= 2 and len(text_norm) > 12:
                    # 在候选中找更精确的元素（link/button且text更短，且包含目标关键词）
                    for j, el2 in enumerate(elements):
                        t2 = el2.get('text', '') or ''
                        tn2 = el2.get('normalized_text', '') or _re_v.sub(r'\s+', '', t2)
                        tp2 = el2.get('type', '')
                        if j != idx and tp2 in ('link', 'button') and len(tn2) <= 12 and tn2 and tn2 in text_norm:
                            # 找到更精确的link/button替代方案，拒绝当前选择
                            logger.warning(f"⚠️ LLM 选择了父容器menu: '{text}'，存在更精确的{tp2}: '{t2}'，已拒绝。理由={reason}")
                            return None

                logger.info(f"  LLM 选择 index={idx}: [{el_type}] {text}, 理由={reason}")
                return idx

            return None

        except Exception as e:
            logger.error(f"LLM 选择失败: {e}")
            return None

    async def smart_wait(
        self,
        condition: str,
        timeout: int = 60
    ) -> bool:
        """
        智能等待 - LLM判断页面是否达到预期状态

        传统方式: await page.wait_for_selector(".bill-table")
        智能方式: await smart_browser.smart_wait("账单表格已加载")

        Args:
            condition: 等待条件的自然语言描述
            timeout: 超时时间（秒）

        Returns:
            是否满足条件
        """
        logger.info(f"智能等待: {condition}")

        start_time = time.time()

        while time.time() - start_time < timeout:
            # DOM快速检查：检测常见弹窗、表格等元素（避免每次都调LLM）
            if await self._dom_fast_check(condition):
                logger.info(f"✅ 条件满足(DOM快速检查): {condition}")
                return True

            # 提取页面文本内容
            page_text = await self._get_page_text()

            # 让LLM判断是否满足条件
            if await self._llm_check_condition(condition, page_text):
                logger.info(f"✅ 条件满足: {condition}")
                return True

            await asyncio.sleep(2)

        logger.warning(f"等待超时: {condition}")
        return False

    async def _dom_fast_check(self, condition: str) -> bool:
        """
        DOM快速检查 - 通过CSS选择器快速判断条件是否满足，避免每次都调LLM

        检测常见弹窗、表格、加载完成等元素，比LLM快100倍。
        只处理明确的关键词模式，不确定的交给LLM。
        """
        if not self.browser.page:
            return False

        # 根据condition中的关键词选择检测策略
        cond_lower = condition.lower()

        try:
            # 1. 检测弹窗出现（关键词：弹窗、对话框、modal、dialog）
            if any(kw in condition for kw in ['弹窗', '对话框', 'modal', 'dialog']) or \
               any(kw in cond_lower for kw in ['modal', 'dialog', 'popup']):
                modal_selectors = [
                    '.ant-modal', '.ant-modal-wrap',
                    '.el-dialog', '.el-dialog__wrapper',
                    '.new-capital-down-dialog',
                    '.weui-dialog', '.weui-mask',
                    '.modal', '.dialog',
                    '.ant-drawer-content',
                    '[role="dialog"]',
                ]
                for sel in modal_selectors:
                    try:
                        el = await self.browser.page.query_selector(sel)
                        if el:
                            visible = await el.is_visible()
                            if visible:
                                return True
                    except Exception:
                        continue

            # 2. 检测表格加载完成（关键词：表格、数据、列表）
            if any(kw in condition for kw in ['表格', '数据', '列表', '账单']):
                table_selectors = [
                    '.ant-table-tbody tr',
                    '.el-table__body tr',
                    'table tbody tr',
                    '.bill-table',
                    '.data-table',
                ]
                for sel in table_selectors:
                    try:
                        el = await self.browser.page.query_selector(sel)
                        if el:
                            visible = await el.is_visible()
                            if visible:
                                return True
                    except Exception:
                        continue

            # 3. 检测下载完成（关键词：下载完成）
            if '下载完成' in condition or '下载完毕' in condition:
                # 检测下载完成提示
                done_selectors = [
                    '.download-success',
                    '.ant-message-success',
                    '.el-message--success',
                ]
                for sel in done_selectors:
                    try:
                        el = await self.browser.page.query_selector(sel)
                        if el:
                            return True
                    except Exception:
                        continue

        except Exception as e:
            logger.debug(f"DOM快速检查异常: {e}")

        return False

    async def _get_page_text(self) -> str:
        """获取页面可见文本内容（合并主页+所有iframe，让smart_wait能检测iframe里的内容）"""
        if not self.browser.page:
            return ""

        script = """
        () => {
            return document.body ? document.body.innerText.substring(0, 3000) : '';
        }
        """
        texts = []
        for frame in self.browser.page.frames:
            try:
                t = await frame.evaluate(script)
                if t and t.strip():
                    texts.append(t.strip())
            except Exception:
                continue
        return "\n".join(texts)[:6000]

    async def _llm_check_condition(
        self,
        condition: str,
        page_text: str
    ) -> bool:
        """LLM判断页面是否满足条件"""
        system_prompt = """你是一个网页状态检测助手。
判断当前页面是否满足用户描述的条件。
只返回JSON: {"satisfied": true/false, "reason": "理由"}"""

        user_message = f"""等待条件: {condition}

当前页面文本（前1000字）:
{page_text[:1000]}

请判断页面是否满足条件。"""

        try:
            response = self.llm.chat(
                message=user_message,
                system_prompt=system_prompt
            )

            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start != -1 and json_end != -1:
                result = json.loads(response[json_start:json_end])
                return result.get("satisfied", False)

        except:
            pass

        return False

    async def smart_login(
        self,
        login_url: str,
        success_hint: str = "已登录",
        timeout: int = 300
    ) -> bool:
        """
        智能登录检测 - LLM判断是否登录成功

        传统方式: 轮询某个固定元素是否存在
        智能方式: LLM看页面内容，判断是否已登录

        Args:
            login_url: 登录页面URL
            success_hint: 登录成功的特征描述，如"页面右上角显示用户名"
            timeout: 超时时间（秒）

        Returns:
            是否登录成功
        """
        logger.info(f"智能登录检测: {success_hint}")

        await self.navigate(login_url)
        logger.info(f"⏳ 请完成登录操作...")

        start_time = time.time()

        while time.time() - start_time < timeout:
            page_text = await self._get_page_text()

            # LLM判断是否已登录
            system_prompt = """你是一个登录状态检测助手。
根据页面内容判断用户是否已经登录成功。

判断依据：
1. 是否还有二维码、登录按钮
2. 是否出现了用户信息、账号管理等登录后才有的内容

返回JSON: {"logged_in": true/false, "reason": "判断理由"}"""

            user_message = f"""登录成功特征: {success_hint}

当前页面文本:
{page_text[:1500]}

请判断用户是否已登录。"""

            try:
                response = self.llm.chat(
                    message=user_message,
                    system_prompt=system_prompt
                )

                json_start = response.find("{")
                json_end = response.rfind("}") + 1

                if json_start != -1 and json_end != -1:
                    result = json.loads(response[json_start:json_end])
                    if result.get("logged_in"):
                        logger.info(f"✅ 登录成功: {result.get('reason', '')}")
                        return True

            except:
                pass

            elapsed = int(time.time() - start_time)
            if elapsed % 10 == 0 and elapsed > 0:
                logger.info(f"⏳ 等待登录... 已等待{elapsed}秒")

            await asyncio.sleep(3)

        logger.error("登录超时")
        return False

    async def smart_download(
        self,
        intent: str,
        timeout: int = 60000
    ) -> Optional[str]:
        """
        智能下载 - 两段式选择下载按钮并触发下载
          和 smart_click 一样：先规则匹配，再LLM，多选择器回退
        """
        logger.info(f"智能下载: {intent}")

        # 1. 提取页面元素
        elements = await self.get_page_elements()
        if not elements:
            logger.warning("页面无可用元素")
            return None

        # 2. 打印前15个元素
        logger.debug("页面元素概览:")
        for i, el in enumerate(elements[:15]):
            logger.debug(f"  [{i}] [{el['type']}] {el.get('text','')[:30]}")

        # 3. 第一段：本地关键词匹配
        target_idx = self._rule_based_match(intent, elements)
        used_method = "rule"

        if target_idx is None:
            # 4. 第二段：LLM选择
            target_idx = await self._llm_select_index(intent, elements)
            used_method = "llm"

        if target_idx is None or target_idx < 0:
            logger.warning(f"未找到匹配'{intent}'的下载按钮")
            for i, el in enumerate(elements[:20]):
                logger.warning(f"    [{i}] {el.get('text','')}")
            return None

        target = elements[target_idx]
        logger.info(f"匹配元素[{used_method}]: index={target_idx}, text={target.get('text','')}")

        # 5. 多策略尝试下载
        selectors = target.get('selectors', [target.get('selector', '')])
        for i, sel in enumerate(selectors):
            logger.info(f"  尝试下载 #{i+1}: {sel}")
            try:
                file_path = await self.browser.download_file(
                    download_selector=sel,
                    timeout=timeout
                )
                if file_path:
                    await self._wait_page_stable()
                    logger.info(f"✅ 下载成功: {file_path} (selector#{i+1})")
                    return file_path
            except Exception as e:
                logger.debug(f"  下载 #{i+1} 失败: {e}")

        # 6. 最后兜底：尝试用JS点击触发下载
        logger.info("  尝试JS点击触发下载...")
        try:
            page = self.browser.page
            await page.evaluate(f"""(sel) => {{
                const el = document.querySelector(sel);
                if (el) {{ el.click(); return true; }}
                return false;
            }}""", selectors[0] if selectors else "")
            # 等待下载
            import asyncio
            await asyncio.sleep(2)
            file_path = await self.browser.download_file(
                download_selector=None,
                timeout=timeout
            )
            if file_path:
                logger.info(f"✅ JS触发下载成功: {file_path}")
                return file_path
        except Exception as e:
            logger.debug(f"  JS点击下载失败: {e}")

        logger.error(f"❌ 智能下载失败: {intent}")
        await self.browser.screenshot("download_failed")
        return None

    async def smart_fill(
        self,
        intent: str,
        value: str,
        timeout: int = 10000
    ) -> bool:
        """
        智能填充 - LLM找到输入框并填入内容

        Args:
            intent: 填充意图描述，如"在日期输入框填入开始日期"
            value: 要填入的值
            timeout: 超时时间

        Returns:
            是否成功填充
        """
        logger.info(f"智能填充: {intent} = {value}")

        # 获取页面所有输入框
        script = """
        () => {
            const inputs = [];
            document.querySelectorAll('input, textarea').forEach((el, i) => {
                inputs.push({
                    index: i,
                    type: el.type || 'text',
                    placeholder: el.placeholder || '',
                    label: '',
                    selector: el.id ? '#' + el.id : el.name ? '[name="' + el.name + '"]' : 'input:nth-of-type(' + (i+1) + ')',
                    visible: el.offsetParent !== null
                });
            });
            return inputs.filter(i => i.visible);
        }
        """
        inputs = await self.browser.page.evaluate(script)

        if not inputs:
            logger.warning("页面无输入框")
            return False

        # LLM选择输入框
        system_prompt = """你是一个表单填写助手。
根据用户意图，找到应该填写的输入框。
返回JSON: {"index": 输入框索引, "reason": "理由"}
找不到返回 {"index": -1}"""

        user_message = f"""用户意图: {intent}
要填入的值: {value}

输入框列表:
{json.dumps(inputs[:15], ensure_ascii=False)}

请选择目标输入框。"""

        response = self.llm.chat(message=user_message, system_prompt=system_prompt)

        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            result = json.loads(response[json_start:json_end])
            idx = result.get("index", -1)

            if idx >= 0 and idx < len(inputs):
                selector = inputs[idx]["selector"]
                logger.info(f"  LLM选择输入框: {selector}")
                return await self.browser.fill_text(selector, value, timeout=timeout)

        except:
            pass

        return False


    async def scroll_to_bottom(self, times=3, wait=1.5):
        """滚动到页面底部，times=滚动几次，防止懒加载没滚完"""
        if not self.browser.page:
            return
        import asyncio
        scroll_script = """
        () => {
            // 1. 滚动整个页面
            window.scrollTo(0, document.body.scrollHeight);
            // 2. 滚动所有有滚动条的元素
            document.querySelectorAll('*').forEach(el => {
                const style = window.getComputedStyle(el);
                const overflow = style.overflow + style.overflowY;
                if ((overflow.includes('auto') || overflow.includes('scroll')) 
                    && el.scrollHeight > el.clientHeight + 30) {
                    el.scrollTop = el.scrollHeight;
                }
            });
            // 3. 特殊处理：ant-design表格的滚动容器
            document.querySelectorAll('.ant-table-body, .ant-table-content, .ant-table-fixed').forEach(el => {
                if (el.scrollHeight > el.clientHeight + 30) {
                    el.scrollTop = el.scrollHeight;
                }
            });
            // 4. 处理有max-height限制的div
            document.querySelectorAll('div[style*="max-height"], div[style*="overflow"]').forEach(el => {
                if (el.scrollHeight > el.clientHeight + 30) {
                    el.scrollTop = el.scrollHeight;
                }
            });
        }
        """
        for i in range(times):
            # 滚动主页+所有iframe
            for frame in self.browser.page.frames:
                try:
                    await frame.evaluate(scroll_script)
                except Exception:
                    continue
            await asyncio.sleep(wait)
        logger.info(f"已滚动到底部（尝试 {times} 次，含iframe）")

    async def extract_table(self, start_col_name=None):
        """
        从页面提取表格数据（模拟用户复制粘贴方式）
        
        原理：用JavaScript的Range+Selection API选中表格内容，
        获取toString()文本（和用户手动Ctrl+C复制的结果一致），
        然后解析TSV格式文本（制表符分隔）转为list[dict]
        
        优势：绕过ant-design复杂DOM结构，直接获取渲染后的文本
        """
        if not self.browser.page:
            return []
        
        # JavaScript：用Selection API模拟复制表格
        script = r"""
        () => {
            // 候选的表格容器选择器（按优先级）
            const selectors = [
                '.ant-table-body',
                '.ant-table-content', 
                '.ant-table-tbody',
                'table tbody',
                '.ant-table-wrapper',
                'table',
            ];
            
            let bestText = '';
            let bestRows = 0;
            
            for (const sel of selectors) {
                const containers = document.querySelectorAll(sel);
                for (const container of containers) {
                    try {
                        // 跳过行数太少的容器（可能是日历等非数据表格）
                        const trs = container.querySelectorAll('tr');
                        if (trs.length > 0 && trs.length < 3) continue;
                        
                        // 用Range选中容器内所有内容
                        const range = document.createRange();
                        range.selectNodeContents(container);
                        const selection = window.getSelection();
                        selection.removeAllRanges();
                        selection.addRange(range);
                        const text = selection.toString();
                        selection.removeAllRanges();
                        
                        // 统计有效行数
                        const rows = text.split('\n').filter(r => r.trim());
                        if (rows.length > bestRows) {
                            bestRows = rows.length;
                            bestText = text;
                        }
                    } catch(e) { continue; }
                }
                if (bestRows >= 3) break;  // 找到足够多行的就不再继续
            }
            
            return bestText;
        }
        """
        
        # 遍历所有frame，用Selection API获取表格文本
        best_text = ""
        for frame in self.browser.page.frames:
            try:
                text = await frame.evaluate(script)
                if text and text.count('\n') > best_text.count('\n'):
                    best_text = text
            except Exception:
                continue
        
        if not best_text or not best_text.strip():
            logger.warning("复制粘贴方式未获取到表格文本")
            return []
        
        # 解析TSV文本（制表符分隔，换行符分行）
        raw_lines = best_text.strip().split('\n')
        # 过滤空行
        lines = [l for l in raw_lines if l.strip()]
        
        if len(lines) < 2:
            logger.warning(f"表格文本行数不足: {len(lines)}")
            return []
        
        # 第一行是表头
        headers = [h.strip() for h in lines[0].split('\t')]
        
        # 找到起始列
        start_idx = 0
        if start_col_name:
            target = start_col_name.replace(' ', '').replace(' ', '')
            for i, h in enumerate(headers):
                if target in h.replace(' ', ''):
                    start_idx = i
                    break
        
        headers = headers[start_idx:]
        
        # 解析数据行
        result = []
        for line in lines[1:]:
            cells = line.split('\t')
            # 跳过行数不一致的异常行
            if len(cells) < start_idx + 1:
                continue
            cells = cells[start_idx:]
            
            row_obj = {}
            has_data = False
            for j, header in enumerate(headers):
                if j < len(cells):
                    val = cells[j].strip()
                    row_obj[header] = val
                    if val:
                        has_data = True
            if has_data:
                result.append(row_obj)
        
        logger.info(f"✅ 复制粘贴方式提取到表格: {len(result)}行 x {len(headers)}列")
        if result:
            logger.info(f"   表头: {list(result[0].keys())}")
        return result


    async def set_page_size(self, size=1000):
        """设置分页条数，遍历主页+所有iframe
        ant-select组件操作：先展开下拉菜单，再点击目标选项
        """
        if not self.browser.page:
            return False
        import re as _re

        # 目标选项的文本格式（京东用"1000 条/页"这种带空格的格式）
        target_texts = [
            f'{size} 条/页', f'{size}条/页', f'{size}/页',
            f'{size} 条', f'{size}条'
        ]

        for frame in self.browser.page.frames:
            # 方法1：ant-design的 ant-select 组件（京东常用）
            # 正确流程：找到分页选择器→点击展开下拉→在下拉中点击目标选项
            selectors_to_try = [
                '.ant-pagination-options-size-changer .ant-select-selector',
                '.ant-pagination-options-size-changer .ant-select-selection',
                '.ant-pagination-options .ant-select-selector',
                '.ant-pagination-options .ant-select-selection',
                '.ant-select-selection-item[title*="条/页"]',
                '.ant-select-selection-item[title*="条"]',
            ]
            for sel_selector in selectors_to_try:
                try:
                    triggers = await frame.query_selector_all(sel_selector)
                    for trig in triggers:
                        try:
                            trig_text = await trig.inner_text()
                        except Exception:
                            trig_text = ''
                        # 必须包含"条/页"或"条"才认为是分页选择器
                        if '条/页' not in trig_text and '条' not in trig_text:
                            continue
                        
                        # 第1步：点击展开下拉菜单
                        await trig.click()
                        await asyncio.sleep(1)
                        
                        # 第2步：在所有frame+主页面中查找目标选项
                        # ant-select下拉菜单可能渲染到body层面，不在原frame内
                        found = False
                        for search_frame in self.browser.page.frames:
                            for txt in target_texts:
                                try:
                                    # 精确匹配，避免误点击其他包含数字的元素
                                    opt = search_frame.get_by_text(txt, exact=True).first
                                    await opt.wait_for(state='visible', timeout=2000)
                                    await opt.click()
                                    logger.info(f"✅ 设置分页大小: {size}（ant-select下拉 '{txt}'）")
                                    return True
                                except Exception:
                                    continue
                        
                        # 如果精确匹配失败，尝试用模糊匹配但限定在下拉选项内
                        for search_frame in self.browser.page.frames:
                            try:
                                # ant-select的下拉选项有特定class
                                options = await search_frame.query_selector_all('.ant-select-item-option')
                                for opt in options:
                                    opt_text = await opt.inner_text()
                                    if str(size) in opt_text and '条' in opt_text:
                                        await opt.click()
                                        logger.info(f"✅ 设置分页大小: {size}（ant-select option '{opt_text.strip()}'）")
                                        return True
                            except Exception:
                                continue
                        
                        # 没找到选项，关闭下拉菜单
                        try:
                            await trig.click()
                            await asyncio.sleep(0.3)
                        except Exception:
                            pass
                except Exception:
                    continue

            # 方法2：select下拉选option（原生select组件）
            try:
                selects = await frame.query_selector_all('select')
                for sel in selects:
                    options = await sel.query_selector_all('option')
                    option_texts = [await op.inner_text() for op in options]
                    has_size = any(any(str(x) in t for x in [10,20,50,100,500,1000]) for t in option_texts)
                    if not has_size:
                        continue
                    best = None
                    for op in options:
                        tv = await op.inner_text()
                        nums = _re.findall(r'\d+', tv)
                        if nums and int(nums[0]) == size:
                            best = op
                            break
                    if best:
                        val = await best.get_attribute('value')
                        label = (await best.inner_text()).strip()
                        if val:
                            await sel.select_option(value=val)
                        else:
                            await sel.select_option(label=label)
                        logger.info(f"✅ 设置分页大小: {size}（select option='{label}'）")
                        return True
            except Exception:
                pass

        logger.warning(f"未找到分页大小选择器，无法设置 {size}/页")
        return False
