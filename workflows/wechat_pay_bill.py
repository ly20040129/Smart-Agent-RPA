# -*- coding: utf-8 -*-
"""
公众号资金账单自动化任务（浏览器方案）
- 登录微信支付商户平台
- 进入交易中心 → 资金账单
- 选择日期范围（影刀式逐字符输入）
- 点击业务明细账单
- 等待弹窗，点击"确 认"按钮（中间有空格）
- 下载Excel

运行: python workflows/wechat_pay_bill.py
"""
import os, sys, asyncio
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sdk import Browser, LocalConfig
from sdk.platforms import init_platforms, get_platform

# 初始化平台工具类
init_platforms()
wechat_pay = get_platform("wechat_pay")

TASK_NAME = "公众号资金账单"
COOKIE_KEY = "wechat_pay"
LOGIN_URL = "https://pay.weixin.qq.com/index.php/core/home"

CURRENT_USER = os.environ.get("SMART_AGENT_USER", "admin")


async def run(date_from=None, date_to=None, output_dir=None, progress_callback=None, **kwargs):
    """
    task_executor调用的入口函数

    Args:
        date_from: 开始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        output_dir: 输出目录路径
        progress_callback: 进度回调 callback(step, message)

    Returns:
        (data_list, out_file) 或 单个文件路径
    """
    if not date_from:
        date_from = kwargs.get('date_from', '')
    if not date_to:
        date_to = kwargs.get('date_to', '')
    if not date_from or not date_to:
        raise RuntimeError("请提供 date_from 和 date_to 参数")

    def log(step, msg):
        print(f"[{step}] {msg}")
        if progress_callback:
            progress_callback(step, msg)

    log(1, f"开始执行：{TASK_NAME}，日期范围 {date_from} ~ {date_to}")

    # cookie预检查（平台工具类）
    if not wechat_pay.is_cookie_valid(COOKIE_KEY):
        log(1, f"Cookie不存在或已过期（{COOKIE_KEY}），浏览器打开后可能需要手动登录")

    downloaded_file = None

    async with Browser(cookie_key=COOKIE_KEY, headless=False) as b:
        await b.open(LOGIN_URL)
        await asyncio.sleep(3)

        # 登录检测：不用"页面上有没有交易中心文字"判断（缓存旧数据会误判），
        # 改为检查交易中心链接是否真正可交互 + 检测"登录重复"提示
        page = b._sb.browser.page
        try:
            login_state = await page.evaluate("""() => {
                var url = location.href.toLowerCase();
                // 1. 被重定向到登录页
                if (url.indexOf('login') >= 0 || url.indexOf('passport') >= 0) return 'need_login';
                // 2. 有可见的二维码
                var qr = document.querySelector('#qrcode, .qrcode, [class*=qr-code]');
                if (qr && qr.offsetParent !== null) return 'need_login';
                // 3. 有"登录重复"提示
                var bodyText = document.body ? (document.body.innerText || '').substring(0, 5000) : '';
                if (bodyText.indexOf('登录重复') >= 0 || bodyText.indexOf('重复登录') >= 0) return 'need_login';
                // 4. 检查"交易中心"是否是真正可交互的链接（不只是文字存在，而是元素可点击）
                var links = document.querySelectorAll('a, [role="menuitem"], [role="link"], .nav-item, .menu-item');
                for (var l of links) {
                    var text = (l.innerText || '').trim();
                    if (text.indexOf('交易中心') >= 0) {
                        var rect = l.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0 && l.offsetParent !== null) {
                            var href = l.getAttribute('href') || '';
                            // 有有效href且不是#的才是真正可交互的后台链接
                            if (href && href !== '#' && href !== 'javascript:void(0)' && href !== 'javascript:;') {
                                return 'logged_in';
                            }
                        }
                    }
                }
                // 5. 不确定（可能是缓存页面、登录态失效但有残留数据）
                return 'unknown';
            }""")
        except Exception:
            login_state = 'unknown'

        if login_state == 'need_login':
            log(1, "未登录或Cookie已过期，请扫码登录")
            await b.wait_login("请扫码登录微信支付，完成后按回车自动保存cookies")
            await asyncio.sleep(3)
        elif login_state == 'logged_in':
            log(1, "登录状态正常")
        else:
            # 不确定时让用户确认，避免误判
            log(1, "登录状态不确定，请查看浏览器页面")
            log(1, "如需扫码请先扫码，已登录则直接按回车继续")
            await b.wait_login("如需扫码请先扫码，已登录则直接按回车继续")
            await asyncio.sleep(2)

        # 步骤2: 进入交易中心
        log(2, "进入交易中心 → 资金账单")
        try:
            await b.click("点击交易中心菜单")
        except Exception:
            pass
        await asyncio.sleep(1)
        try:
            await b.click("点击资金账单")
        except Exception:
            pass
        await b.wait("账单数据或表格已显示在页面上")
        await asyncio.sleep(2)

        # 步骤3: 填写日期范围（影刀式逐字符输入）
        log(3, f"填写日期范围: {date_from} ~ {date_to}")
        try:
            page = b._sb.browser.page
            # 先尝试用 ant-design 的 RangePicker / date picker input
            js_focus_input = """(idx) => {
                // 微信支付可能用的日期选择器
                var inputs = document.querySelectorAll('.ant-picker-input input, .ant-picker input, input[type=date], .date-picker input, [class*=date] input');
                // 去除隐藏的
                inputs = Array.from(inputs).filter(i => i.offsetParent !== null);
                if (inputs.length > idx) {
                    inputs[idx].focus();
                    try { inputs[idx].select(); } catch(e){}
                    return 'ok: ' + inputs.length + ' inputs, idx=' + idx;
                }
                return 'fail: found ' + inputs.length + ' inputs';
            }"""

            # 填开始日期
            log(3, "填入开始日期: " + date_from)
            r1 = await page.evaluate(js_focus_input, 0)
            log(3, "  focus结果: " + str(r1))
            await asyncio.sleep(0.3)
            await page.keyboard.type(date_from, delay=50)
            await asyncio.sleep(0.5)
            await page.keyboard.press('Enter')
            await asyncio.sleep(1)

            # 填结束日期
            log(3, "填入结束日期: " + date_to)
            r2 = await page.evaluate(js_focus_input, 1)
            log(3, "  focus结果: " + str(r2))
            await asyncio.sleep(0.3)
            await page.keyboard.type(date_to, delay=50)
            await asyncio.sleep(0.5)
            await page.keyboard.press('Enter')
            await asyncio.sleep(1)

            log(3, "日期填写完成")
        except Exception as e:
            log(3, f"自动填日期失败({e})，请手动在页面上选择日期范围")
            input("请在页面上选好日期后按回车继续...")

        # 步骤4: 如果有查询按钮就点一下
        try:
            log(4, "点击查询按钮（如果有）")
            await b.click("点击查询按钮", timeout=5000)
            await asyncio.sleep(2)
        except Exception:
            pass

        # 步骤5: 点击业务明细账单
        log(5, "点击业务明细账单触发下载")
        await b.click("点击业务明细账单")
        await asyncio.sleep(1)

        # ====== 步骤6~7: 等待弹窗 + 点击确认并捕获下载（强定位+手动点击双保险）======
        # 经验 ID 1171017: 必须【限定在最上层、可见的弹窗作用域】内找 button，避免取到隐藏/其他层级的同文本按钮
        # 经验 ID 554206: 触发下载的点击必须被 expect_download 包裹；若手动点击则要提前开启监听
        page = b._sb.browser.page
        log(6, "等待确认下载弹窗出现并点击确 认/确定按钮下载")

        # 6.1 先等弹窗出现（DOM快速检查优先）
        try:
            await b.wait("页面出现确认下载的弹窗，包含确 认或确定按钮", timeout=30)
        except Exception:
            log(6, "弹窗等待超时，继续尝试（可能已出现或无显式弹窗）")

        import time as _time
        _download_start = _time.time()
        downloaded_file = None
        clicked_ok = False

        # ====== 6.2 核心：找最上层弹窗里的确认/确定按钮，并暴力点击（解决你说的"按钮点不动"）======
        # 用一段 JS 在页面上直接定位并返回"按钮的 DOM 唯一 CSS 路径"，避免 Playwright locator.first() 拿到隐藏按钮
        JS_FIND_CONFIRM_BTN = r"""() => {
            // A. 找最顶层可见的 modal/dialog 容器（取 z-index 最大）
            const modalSels = ['.ant-modal','.ant-modal-wrap','.el-dialog','.el-dialog__wrapper','.modal','.dialog','.weui-dialog','[role="dialog"]','.new-capital-down-dialog'];
            let modals = [];
            for (const s of modalSels) {
                for (const el of document.querySelectorAll(s)) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 20 || rect.height < 20) continue;
                    if (el.offsetParent === null && getComputedStyle(el).display === 'none') continue;
                    const zi = parseInt(getComputedStyle(el).zIndex || '0',10) || 0;
                    modals.push({el, zi});
                }
            }
            let root = document;
            if (modals.length > 0) {
                modals.sort((a,b)=>b.zi-a.zi);
                root = modals[0].el;
                console.log('[find-confirm] using top modal zIndex=', modals[0].zi, 'class=', modals[0].el.className);
            } else {
                console.log('[find-confirm] no modal found, use document');
            }
            // B. 在 root 内找可点击元素：文本精确匹配优先级（用户实际 HTML：<button><span>确 定</span></button>）
            //    prec: 0 = 原始文本精确(确 定 / 确 认 / 确定 / 确认)，1 = 去空格后精确，2 = 包含匹配
            const candidates = [];
            // 不仅看 root 下的 button/a，也递归看它们内部 span（文本常在 span 里）
            const nodes = root.querySelectorAll('button, a, [role="button"], div[onclick], span[onclick], .el-button, .ant-btn, .btn');
            for (const n of nodes) {
                const raw_all = (n.innerText || n.textContent || '').trim();
                // 原始文本（保留空格，如 "确 定"、"确 认"
                const raw = raw_all.replace(/\n|\t/g,'').replace(/\s{2,}/g,' ');
                // 完全去空格
                const txt = raw.replace(/\s+/g,'');
                const rect = n.getBoundingClientRect();
                if (rect.width < 10 || rect.height < 10) continue;
                const style = getComputedStyle(n);
                if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') < 0.2) continue;
                let prec = 9;
                // 0 级：原始文本精确匹配用户实际看到的 "确 定" 或 "确 认"
                if (raw === '确 定' || raw === '确 认' || raw === '确定' || raw === '确认') prec = 0;
                // 1 级：去空格后精确
                else if (txt === '确定' || txt === '确认') prec = 1;
                // 2 级：包含匹配（防止按钮上还有其他文案）
                else if (txt.includes('确定') || txt.includes('确认') || raw.includes('确 定') || raw.includes('确 认')) prec = 2;
                if (prec < 9) candidates.push({n, raw, txt, prec});
            }
            if (!candidates.length) return null;
            candidates.sort((a,b)=>a.prec-b.prec);
            const btn = candidates[0].n;
            // 返回唯一 CSS 路径
            function cssPath(el){
                if (!el || !(el instanceof Element)) return '';
                const parts = [];
                let cur = el;
                while (cur && cur.nodeType === Node.ELEMENT_NODE && parts.length < 12) {
                    let sel = cur.nodeName.toLowerCase();
                    if (cur.id) { sel += '#' + CSS.escape(cur.id); parts.unshift(sel); break; }
                    let same = 1;
                    let sib = cur.previousElementSibling;
                    while (sib){ if (sib.nodeName===cur.nodeName) same++; sib = sib.previousElementSibling; }
                    sel += `:nth-of-type(${same})`;
                    parts.unshift(sel);
                    cur = cur.parentElement;
                }
                return parts.join(' > ');
            }
            console.log('[find-confirm] pick:', candidates[0].raw, 'selector=', cssPath(btn));
            return {text: candidates[0].raw, selector: cssPath(btn)};
        }"""

        # 辅助：点击元素，用"Playwright locator.click + force:true" + "JS click" + "dispatchEvent MouseEvent" 三板斧
        async def _click_hard(selector, timeout_ms=5000):
            """尽全力点一个按钮"""
            try:
                loc = page.locator(selector).first
                await loc.scroll_into_view_if_needed(timeout=3000)
                try:
                    await loc.click(timeout=timeout_ms, force=True, no_wait_after=False)
                    return True
                except Exception as e1:
                    log(6, f"    locator.click 失败: {e1}，尝试 JS click")
            except Exception:
                pass
            # JS 1: el.click()
            try:
                await page.evaluate("""(s)=>{const e=document.querySelector(s); if(e){e.scrollIntoView({block:'center'}); e.click(); return 'click';} return 'no-el';}""", selector)
                return True
            except Exception:
                pass
            # JS 2: dispatchEvent
            try:
                await page.evaluate("""(s)=>{
                    const e=document.querySelector(s); if(!e) return 'no-el';
                    e.scrollIntoView({block:'center'});
                    ['mousedown','mouseup','click'].forEach(t=>{
                        e.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}));
                    });
                    return 'dispatch';
                }""", selector)
                return True
            except Exception as ex:
                log(6, f"    所有点击方式均失败: {ex}")
                return False

        # 辅助：执行点击并捕获下载
        save_download_dir = Path(_PROJECT_ROOT) / "data" / "downloads"
        save_download_dir.mkdir(parents=True, exist_ok=True)
        async def _save_dw(dw):
            fn = dw.suggested_filename or f"wechat_bill_{int(_time.time())}.xlsx"
            sp = save_download_dir / fn
            try:
                await dw.save_as(str(sp))
            except Exception:
                # save_as 可能失败（非同源blob等），用create_read_stream兜底
                try:
                    buf = await dw.read()
                    sp.write_bytes(buf)
                except Exception as ex2:
                    log(7, f"    save/download都失败: {ex2}")
                    return None
            return str(sp)

        async def _try_click_and_capture(click_fn, timeout_sec=150):
            """先开 expect_download 再点击；若超时则直接尝试轮询下载目录"""
            nonlocal downloaded_file, clicked_ok
            ok = False
            try:
                async with page.expect_download(timeout=timeout_sec * 1000) as di:
                    ok = await click_fn()
                dw = await di.value
                sp = await _save_dw(dw)
                if sp and os.path.exists(sp):
                    downloaded_file = sp
                    clicked_ok = clicked_ok or ok
                    return True
            except Exception as e:
                log(6, f"  expect_download 未直接捕获: {e}，继续兜底")
                # 即使超时也先点
                if not ok:
                    try:
                        ok = await click_fn()
                        clicked_ok = clicked_ok or ok
                    except Exception:
                        pass
            return False

        # 用 Playwright 原生 API 直接定位"确定"按钮，不依赖 smart_browser 生成的垃圾选择器
        async def _try_click_with_playwright(locator, desc="按钮", timeout_sec=150):
            nonlocal downloaded_file, clicked_ok
            try:
                async with page.expect_download(timeout=timeout_sec * 1000) as di:
                    await locator.click(timeout=5000, force=True)
                    clicked_ok = True
                dw = await di.value
                sp = await _save_dw(dw)
                if sp and os.path.exists(sp):
                    downloaded_file = sp
                    log(7, f"  ✅ 通过{desc}成功下载: {sp}")
                    return True
            except Exception as e:
                log(6, f"  {desc}点击失败: {e}")
            return False

        # ===== 尝试A1: 用 JS 定位 + Playwright click =====
        try:
            confirm_btn_info = await page.evaluate(JS_FIND_CONFIRM_BTN)
            if confirm_btn_info and confirm_btn_info.get("selector"):
                sel_a = confirm_btn_info["selector"]
                log(6, f"  JS定位按钮: {confirm_btn_info.get(chr(34)+chr(34))}  selector={sel_a}")
                if await _try_click_with_playwright(page.locator(sel_a).first, "JS定位选择器"):
                    pass
        except Exception as e:
            log(6, f"  JS找按钮异常: {e}")

        # ===== 尝试A2: 用 Playwright get_by_text 原生 API =====
        if not downloaded_file:
            log(6, "  尝试 get_by_text")
            for btn_text in ["确 定", "确 认", "确定", "确认"]:
                if downloaded_file: break
                try:
                    loc = page.get_by_text(btn_text, exact=True)
                    await loc.wait_for(state="visible", timeout=3000)
                    log(6, f"    找到文本按钮: {btn_text}")
                    if await _try_click_with_playwright(loc, f"get_by_text({btn_text})"):
                        break
                except Exception:
                    continue

        # ===== 尝试A3: 用角色选择器 =====
        if not downloaded_file:
            log(6, "  尝试 get_by_role")
            for btn_name in ["确 定", "确 认", "确定", "确认"]:
                if downloaded_file: break
                try:
                    loc = page.get_by_role("button", name=btn_name)
                    await loc.wait_for(state="visible", timeout=3000)
                    log(6, f"    找到role=button: {btn_name}")
                    if await _try_click_with_playwright(loc, f"get_by_role({btn_name})"):
                        break
                except Exception:
                    continue

        # ===== 尝试A4: 用 CSS 选择器 =====
        if not downloaded_file:
            log(6, "  尝试 CSS 选择器定位")
            css_selectors = [
                ".el-dialog__footer .el-button--primary",
                ".el-dialog .el-button--primary",
                ".weui-dialog .el-button--primary",
                "[role=dialog] .el-button--primary",
                ".ant-modal .el-button--primary",
                ".el-button--primary",
                "button.el-button--primary",
            ]
            for css_sel in css_selectors:
                if downloaded_file: break
                try:
                    loc = page.locator(css_sel).first
                    await loc.wait_for(state="visible", timeout=2000)
                    log(6, f"    CSS选择器: {css_sel}")
                    if await _try_click_with_playwright(loc, f"CSS选择器({css_sel})"):
                        break
                except Exception:
                    continue

        # ===== 尝试A5: 模拟键盘操作 =====
        if not downloaded_file:
            log(6, "  尝试键盘 Tab + Enter")
            try:
                async with page.expect_download(timeout=30000) as di:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Tab")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Tab")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Tab")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Enter")
                    clicked_ok = True
                dw = await di.value
                sp = await _save_dw(dw)
                if sp and os.path.exists(sp):
                    downloaded_file = sp
                    log(7, f"  ✅ 通过键盘操作成功下载: {sp}")
            except Exception as e:
                log(6, f"  键盘操作失败: {e}")

        # ===== 兜底：让用户手动点击 =====
        if not downloaded_file:
            log(6, "⚠️ 自动点击未成功，请手动点击弹窗中的确定按钮下载账单")
            log(6, "   点击后回来按回车继续")
            try:
                input("（手动点击确定按钮后，按回车继续...）")
            except Exception:
                pass
        # 辅助函数：扫描最新下载文件
        def _scan_latest():
            _cutoff = _time.time() - 300
            _home = Path(os.path.expanduser("~"))
            _search_dirs = [save_download_dir, _home / "Downloads", _home / "下载"]
            _exts = {".xlsx", ".xls", ".csv", ".zip"}
            _best = None
            _best_mtime = 0
            for _sd in _search_dirs:
                if not _sd or not _sd.exists(): continue
                try:
                    for _p in _sd.iterdir():
                        if not _p.is_file(): continue
                        if _p.suffix.lower() not in _exts: continue
                        _mt = _p.stat().st_mtime
                        if _mt > _cutoff and _mt > _best_mtime:
                            _best = str(_p)
                            _best_mtime = _mt
                except Exception: pass
            return _best

        # ===== 6.3 终极兜底：扫描下载目录找最近 10 分钟新生成的 xls/xlsx/csv/zip =====
        if not downloaded_file or not os.path.exists(downloaded_file):
            log(7, "终极兜底：多目录扫描最新下载文件...")
            candidates = []
            home = Path(os.path.expanduser("~"))
            import tempfile
            search_dirs = [
                save_download_dir,
                home / "Downloads",
                home / "下载",
                Path(tempfile.gettempdir()),
            ]
            now = _time.time()
            for sd in search_dirs:
                if not sd or not sd.exists(): continue
                try:
                    for p in sd.iterdir():
                        if not p.is_file(): continue
                        suffix = p.suffix.lower()
                        if suffix not in ('.xls', '.xlsx', '.csv', '.zip'): continue
                        try: mt = p.stat().st_mtime
                        except Exception: continue
                        age = now - mt
                        if age < 1200:  # 20 分钟内的
                            candidates.append((mt, p))
                except Exception:
                    pass
            if candidates:
                candidates.sort(reverse=True)
                downloaded_file = str(candidates[0][1])
                log(7, f"  兜底识别: {downloaded_file} age={now-candidates[0][0]:.0f}s size={candidates[0][1].stat().st_size} bytes")

    # 如果没拿到文件，抛错
    if not downloaded_file or not os.path.exists(downloaded_file):
        raise RuntimeError("未获取到下载文件，请检查日志")

    # 如果用户指定了 output_dir，则把文件移动过去
    out_dir = Path(output_dir) if output_dir else (Path(_PROJECT_ROOT) / "data" / "downloads")
    out_dir.mkdir(exist_ok=True, parents=True)

    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(downloaded_file).suffix or ".xlsx"
    out_file = out_dir / f"{TASK_NAME}_{today}{ext}"

    import shutil
    if str(Path(downloaded_file).resolve()) != str(out_file.resolve()):
        shutil.copy2(downloaded_file, str(out_file))

    log(8, f"✅ 完成！账单已保存到: {out_file}")
    return str(out_file)


async def main():
    print(f"程序开始：{TASK_NAME}")
    date_from = input("请输入开始日期(YYYY-MM-DD): ").strip() or "2026-07-01"
    date_to = input("请输入结束日期(YYYY-MM-DD): ").strip() or "2026-07-31"
    print(f"查询日期范围: {date_from} ~ {date_to}")

    try:
        out_file = await run(date_from=date_from, date_to=date_to)
        print("\n✅ 执行完成: " + str(out_file))
    except Exception as e:
        print("❌ 执行失败: " + str(e))


if __name__ == "__main__":
    asyncio.run(main())
