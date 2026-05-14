#!/usr/bin/env python3
"""探索通知页面 - 查找输入框"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def explore_notify():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**anti_detect.get_browser_context_args())

        with open('/opt/ticket-bot/xianyu_cookies.json', 'r') as f:
            cookies = json.load(f)
        for cookie in cookies:
            cookie.pop('sameSite', None)
            try:
                await context.add_cookies([cookie])
            except:
                pass

        page = await context.new_page()

        print('1. 访问通知页面...')
        notify_url = 'https://www.goofish.com/im?spm=a21ybx.home.sidebar.2.4c053da6WOhKfy'
        await page.goto(notify_url, timeout=60000)
        await asyncio.sleep(5)

        # 关闭验证码
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
                await asyncio.sleep(2)
        except:
            pass

        await page.screenshot(path='/tmp/xianyu_notify_page.png', full_page=True)
        print(f'   URL: {page.url}')
        print('   截图: /tmp/xianyu_notify_page.png')

        # 获取页面文本
        print('2. 获取页面文本...')
        all_text = await page.evaluate('''() => {
            const texts = [];
            document.querySelectorAll("*").forEach(el => {
                if (el.children.length === 0) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 1 && text.length < 200) {
                        texts.push({
                            tag: el.tagName,
                            class: el.className.substring(0, 60),
                            text: text.substring(0, 80)
                        });
                    }
                }
            });
            return texts;
        }''')

        seen = set()
        unique = []
        for t in all_text:
            key = t['text']
            if key not in seen and len(key) > 2:
                seen.add(key)
                unique.append(t)

        print(f'   唯一文本数量: {len(unique)}')
        for t in unique[:40]:
            print(f'   [{t["tag"]}] {t["class"]}: {t["text"]}')

        # 查找输入框
        print('3. 查找输入框...')
        inputs = await page.query_selector_all('input, textarea, [contenteditable]')
        print(f'   找到 {len(inputs)} 个输入元素')
        for inp in inputs[:10]:
            try:
                cls = await inp.get_attribute('class') or ''
                ph = await inp.get_attribute('placeholder') or ''
                id = await inp.get_attribute('id') or ''
                print(f'   class={cls[:60]}, placeholder={ph[:40]}, id={id[:30]}')
            except:
                pass

        # 查找按钮
        print('4. 查找按钮...')
        btns = await page.query_selector_all('button')
        print(f'   找到 {len(btns)} 个按钮')
        for btn in btns[:15]:
            try:
                text = await btn.inner_text()
                cls = await btn.get_attribute('class') or ''
                disabled = await btn.get_attribute('disabled')
                if text.strip() or 'send' in cls.lower() or 'submit' in cls.lower():
                    print(f'   "{text.strip()[:30]}" class={cls[:60]}, disabled={disabled}')
            except:
                pass

        # 查找包含输入相关的区域
        print('5. 查找聊天相关区域...')
        chat_areas = await page.evaluate('''() => {
            const areas = [];
            document.querySelectorAll('*').forEach(el => {
                const cls = el.className || '';
                const text = el.innerText || '';
                if (cls.includes('input') || cls.includes('editor') || cls.includes('compose') ||
                    cls.includes('send') || cls.includes('submit')) {
                    areas.push({
                        tag: el.tagName,
                        class: cls.substring(0, 80),
                        text: text.substring(0, 50)
                    });
                }
            });
            return areas;
        }''')
        print(f'   聊天区域: {len(chat_areas)}')
        for a in chat_areas[:10]:
            print(f'   {a}')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(explore_notify())