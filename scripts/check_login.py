#!/usr/bin/env python3
"""检查登录状态"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_login():
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
        await asyncio.sleep(3)

        # 关闭验证码
        try:
            close_btn = page.locator('.baxia-dialog-close')
            if await close_btn.count() > 0:
                await close_btn.click(timeout=3000)
                await asyncio.sleep(2)
        except:
            pass

        # 检查当前cookie
        print('2. 检查当前cookie...')
        page_cookies = await context.cookies()
        print(f'   当前cookie数量: {len(page_cookies)}')
        for c in page_cookies[:5]:
            print(f'   {c["name"]}: {c["value"][:30]}...' if len(c['value']) > 30 else f'   {c["name"]}: {c["value"]}')

        # 检查是否真的登录了
        print('3. 检查登录状态...')
        login_status = await page.evaluate('''() => {
            // 检查是否显示登录用户名
            const nick = document.querySelector("[class*='nick']");
            const header = document.querySelector("#header");
            const content = document.querySelector("#content");

            return {
                hasNick: !!nick,
                nickText: nick ? nick.innerText : null,
                hasHeader: !!header,
                headerHTML: header ? header.innerHTML.substring(0, 200) : null,
                url: window.location.href
            };
        }''')
        print(f'   登录状态: {json.dumps(login_status, ensure_ascii=False, indent=4)}')

        # 访问用户主页测试登录
        print('4. 测试登录状态...')
        await page.goto('https://www.goofish.com/user', timeout=30000)
        await asyncio.sleep(3)
        print(f'   用户页面URL: {page.url}')

        # 截图
        await page.screenshot(path='/tmp/xianyu_user_page.png')
        print('   用户页面截图: /tmp/xianyu_user_page.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_login())