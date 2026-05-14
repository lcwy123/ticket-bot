#!/usr/bin/env python3
"""监听网络请求检查API"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_network():
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

        # 收集网络请求
        api_requests = []
        page.on('response', lambda response: api_requests.append({
            'url': response.url,
            'status': response.status,
            'type': response.request.resource_type
        }) if 'api' in response.url.lower() or 'message' in response.url.lower() or 'im' in response.url.lower() else None)

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
        await asyncio.sleep(10)

        # 检查API请求
        print(f'3. 检查API请求 (共 {len(api_requests)} 个)...')
        for req in api_requests[:20]:
            print(f'   {req["status"]}: {req["url"][:100]}')

        # 检查WebSocket
        print('4. 检查WebSocket连接...')
        ws_info = await page.evaluate('''() => {
            const ws = [...window.wsMap?.values() || [], ...window.webSockets || []];
            return {
                count: ws.length,
                states: ws.map(w => w.readyState)
            };
        }''')
        print(f'   WebSocket: {json.dumps(ws_info)}')

        # 检查页面是否有错误
        print('5. 检查控制台错误...')
        console_errors = []
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)

        await asyncio.sleep(2)

        if console_errors:
            print(f'   错误: {console_errors[:5]}')
        else:
            print('   无错误')

        await page.screenshot(path='/tmp/xianyu_network.png', full_page=True)
        print('   截图: /tmp/xianyu_network.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_network())