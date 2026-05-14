#!/usr/bin/env python3
"""检查API响应数据"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_api():
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

        print('1. 访问消息页面...')
        await page.goto('https://www.goofish.com/im', timeout=60000)

        # 关闭验证码
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
        except:
            pass

        await asyncio.sleep(5)

        # 获取所有API响应
        print('2. 获取API响应数据...')
        api_responses = []

        async def handle_response(response):
            if 'goofish.com' in response.url or 'alicdn.com' in response.url:
                try:
                    data = await response.json()
                    api_responses.append({
                        'url': response.url[:100],
                        'status': response.status,
                        'data': str(data)[:500]
                    })
                except:
                    pass

        page.on('response', handle_response)

        # 等待更多API调用
        await asyncio.sleep(10)

        print(f'   收集到 {len(api_responses)} 个响应')
        for resp in api_responses[:10]:
            print(f'   [{resp["status"]}] {resp["url"]}')
            print(f'      数据: {resp["data"]}')

        await page.screenshot(path='/tmp/xianyu_api_check.png', full_page=True)
        print('   截图: /tmp/xianyu_api_check.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_api())