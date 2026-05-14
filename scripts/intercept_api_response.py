#!/usr/bin/env python3
"""拦截API响应"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def intercept_api():
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

        # 拦截API响应
        api_data = []

        async def handle_response(response):
            url = response.url
            if 'mtop' in url or 'gaia' in url:
                try:
                    data = await response.json()
                    api_data.append({
                        'url': url[:150],
                        'status': response.status,
                        'data': json.dumps(data, ensure_ascii=False)[:1000]
                    })
                except:
                    pass

        page.on('response', handle_response)

        print('1. 访问消息页面...')
        await page.goto('https://www.goofish.com/im', timeout=60000)

        # 关闭验证码
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
        except:
            pass

        print('2. 等待API调用...')
        await asyncio.sleep(10)

        print(f'3. API响应 ({len(api_data)} 个):')
        for item in api_data:
            print(f'   [{item["status"]}] {item["url"]}')
            print(f'      数据: {item["data"]}')
            print()

        await page.screenshot(path='/tmp/xianyu_intercept.png', full_page=True)
        print('   截图: /tmp/xianyu_intercept.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(intercept_api())