#!/usr/bin/env python3
"""尝试重连"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def try_reconnect():
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
        await asyncio.sleep(5)

        # 关闭验证码
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
                await asyncio.sleep(2)
        except:
            pass

        # 截图
        await page.screenshot(path='/tmp/xianyu_before_reconnect.png')

        # 查找并点击重连按钮
        print('2. 查找重连按钮...')
        reconnect_btn = page.get_by_text('重连')
        if await reconnect_btn.count() > 0:
            print('   找到重连按钮，点击...')
            await reconnect_btn.click()
            await asyncio.sleep(5)
            await page.screenshot(path='/tmp/xianyu_after_reconnect.png')
            print('   已重连')
        else:
            print('   未找到重连按钮')

        # 检查连接状态
        print('3. 检查页面状态...')
        status = await page.evaluate('''() => {
            const bodyText = document.body.innerText;
            return {
                hasDisconnect: bodyText.includes('连接中断'),
                hasReconnect: bodyText.includes('重连'),
                texts: bodyText.split('\\n').filter(t => t.trim()).slice(0, 20)
            };
        }''')
        print(f'   状态: {json.dumps(status, ensure_ascii=False)}')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(try_reconnect())