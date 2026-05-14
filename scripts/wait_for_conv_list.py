#!/usr/bin/env python3
"""等待对话列表加载"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def wait_for_conv():
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

        print('2. 等待对话列表加载...')
        # 等待更长时间让动态内容加载
        await asyncio.sleep(8)

        # 截图
        await page.screenshot(path='/tmp/xianyu_wait_conv.png')

        # 检查侧边栏的完整HTML
        print('3. 分析侧边栏HTML...')
        sider_html = await page.evaluate('''() => {
            const sider = document.querySelector('.ant-layout-sider');
            if (!sider) return 'no sider found';
            return sider.innerHTML;
        }''')
        print(f'   HTML长度: {len(sider_html)}')
        print(f'   HTML片段: {sider_html[:1500]}...')

        # 分析conv-header
        print('4. 分析conv-header...')
        header_info = await page.evaluate('''() => {
            const header = document.querySelector('.conv-header');
            if (!header) return 'no header';
            return {
                innerHTML: header.innerHTML.substring(0, 500),
                children: header.children.length
            };
        }''')
        print(f'   Header: {json.dumps(header_info, ensure_ascii=False)}')

        # 查找conv-list
        print('5. 查找conv-list...')
        conv_list_info = await page.evaluate('''() => {
            const convList = document.querySelector('.conversation-list');
            if (!convList) return 'not found';

            const children = [];
            convList.querySelectorAll('*').forEach(el => {
                children.push({
                    tag: el.tagName,
                    class: el.className.substring(0, 60),
                    text: el.innerText?.substring(0, 30) || ''
                });
            });
            return {
                childCount: children.length,
                children: children.slice(0, 30)
            };
        }''')
        print(f'   ConvList: {json.dumps(conv_list_info, ensure_ascii=False)}')

        # 截图
        await page.screenshot(path='/tmp/xianyu_wait_conv2.png', full_page=True)
        print('   截图: /tmp/xianyu_wait_conv2.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(wait_for_conv())