#!/usr/bin/env python3
"""详细检查所有请求"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_all_requests():
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

        # 记录所有请求和响应
        all_requests = []
        all_responses = []

        def log_request(request):
            all_requests.append({
                'url': request.url,
                'method': request.method
            })

        async def log_response(response):
            all_responses.append({
                'url': response.url[:120],
                'status': response.status
            })

        page.on('request', log_request)
        page.on('response', log_response)

        print('1. 访问消息页面...')
        await page.goto('https://www.goofish.com/im', timeout=60000)

        # 关闭验证码
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
        except:
            pass

        print('2. 等待页面加载...')
        await asyncio.sleep(8)

        # 打印所有API请求
        print(f'3. API请求 ({len(all_requests)} 个):')
        for req in all_requests:
            if 'api' in req['url'].lower() or 'goofish' in req['url'] or 'alicdn' in req['url']:
                print(f'   {req["method"]}: {req["url"][:100]}')

        # 打印非200响应
        print(f'4. 非200响应:')
        for resp in all_responses:
            if resp['status'] != 200:
                print(f'   {resp["status"]}: {resp["url"]}')

        # 检查是否有失败请求
        print(f'5. 失败的请求:')
        for resp in all_responses:
            if resp['status'] >= 400:
                print(f'   {resp["status"]}: {resp["url"]}')

        await page.screenshot(path='/tmp/xianyu_all_requests.png', full_page=True)
        print('   截图: /tmp/xianyu_all_requests.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_all_requests())