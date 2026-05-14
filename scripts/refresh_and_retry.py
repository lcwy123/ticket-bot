#!/usr/bin/env python3
"""强制刷新并等待对话列表"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def force_refresh():
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

        print('2. 等待初始加载...')
        await asyncio.sleep(3)

        # 多次刷新等待
        for i in range(3):
            print(f'   第{i+1}次刷新...')
            await page.reload()
            await asyncio.sleep(5)

            # 检查对话列表
            conv_items = await page.query_selector_all('[class*="conv-item"], [class*="conversation-item"], [class*="msg-item"]')
            print(f'   对话项数量: {len(conv_items)}')

            if len(conv_items) > 0:
                print('   找到对话项!')
                break

        # 最终截图
        await page.screenshot(path='/tmp/xianyu_force_refresh.png', full_page=True)
        print('   截图: /tmp/xianyu_force_refresh.png')

        # 分析页面
        print('3. 分析页面结构...')
        result = await page.evaluate('''() => {
            const sider = document.querySelector('.ant-layout-sider');
            return {
                siderExists: !!sider,
                siderHTML: sider ? sider.innerHTML.substring(0, 1000) : null
            };
        }''')
        print(f'   侧边栏: {result}')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(force_refresh())