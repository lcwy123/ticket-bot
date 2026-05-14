#!/usr/bin/env python3
"""检查通知页面URL"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_notify_url():
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

        # 用户提到的通知页面URL
        notify_url = 'https://www.goofish.com/im?spm=a21ybx.home.sidebar.2.4c053da6WOhKfy'

        print(f'1. 访问通知页面: {notify_url}')
        await page.goto(notify_url, timeout=60000)

        # 关闭验证码
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
        except:
            pass

        await asyncio.sleep(8)

        print(f'   当前URL: {page.url}')

        # 截图
        await page.screenshot(path='/tmp/xianyu_notify_url.png', full_page=True)
        print('   截图: /tmp/xianyu_notify_url.png')

        # 检查页面内容
        print('2. 检查页面内容...')
        content = await page.evaluate('document.body.innerText')
        print(f'   页面文本长度: {len(content)}')
        print(f'   文本内容: {content[:1000]}')

        # 检查所有可见元素
        print('3. 检查所有可见文本元素...')
        elements = await page.evaluate('''() => {
            const elements = [];
            document.querySelectorAll('*').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 1 && text.length < 200) {
                        elements.push({
                            tag: el.tagName,
                            class: el.className.substring(0, 50),
                            text: text.substring(0, 60),
                            visible: rect.width > 0 && rect.height > 0
                        });
                    }
                }
            });
            return elements;
        }''')

        seen = set()
        unique = []
        for e in elements:
            if e['text'] not in seen and len(e['text']) > 2:
                seen.add(e['text'])
                unique.append(e)

        print(f'   可见元素: {len(unique)}')
        for e in unique[:30]:
            print(f'   [{e["tag"]}] {e["class"]}: {e["text"]}')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_notify_url())