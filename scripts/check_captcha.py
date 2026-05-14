#!/usr/bin/env python3
"""检查验证码对话框"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_captcha():
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

        print(f'   当前URL: {page.url}')

        # 截图
        await page.screenshot(path='/tmp/xianyu_captcha.png')
        print('   截图: /tmp/xianyu_captcha.png')

        # 检查对话框
        print('2. 检查验证码对话框...')
        dialog_count = await page.evaluate('''() => { return document.querySelectorAll(".baxia-dialog").length; }''')
        print(f'   baxia-dialog数量: {dialog_count}')

        mask_count = await page.evaluate('''() => { return document.querySelectorAll(".baxia-dialog-mask").length; }''')
        print(f'   baxia-dialog-mask数量: {mask_count}')

        # 检查iframe
        print('3. 检查iframe...')
        iframe_count = await page.evaluate('''() => { return document.querySelectorAll("iframe").length; }''')
        print(f'   iframe数量: {iframe_count}')

        # 尝试关闭验证码
        print('4. 尝试关闭验证码...')
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                print('   找到关闭按钮，点击...')
                await close_btn.click(timeout=3000)
                await asyncio.sleep(2)
                await page.screenshot(path='/tmp/xianyu_after_close.png')
                print('   已关闭并截图')
        except Exception as e:
            print(f'   关闭失败: {e}')

        # 检查页面最终状态
        print('5. 检查页面最终状态...')
        url = page.url
        print(f'   最终URL: {url}')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_captcha())