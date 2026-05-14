#!/usr/bin/env python3
"""检查对话列表空状态"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_empty():
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

        # 检查完整HTML
        print('2. 检查完整HTML...')
        full_html = await page.evaluate('document.documentElement.outerHTML')
        print(f'   HTML长度: {len(full_html)}')

        # 查找可能的空状态文本
        print('3. 查找空状态...')
        empty_states = await page.evaluate('''() => {
            const states = [];
            document.querySelectorAll('*').forEach(el => {
                const text = el.innerText?.trim();
                if (text && (
                    text.includes('暂无') ||
                    text.includes('没有') ||
                    text.includes('空') ||
                    text.includes('消息') ||
                    text.includes('会话')
                )) {
                    states.push({
                        tag: el.tagName,
                        class: el.className.substring(0, 50),
                        text: text.substring(0, 50)
                    });
                }
            });
            return states;
        }''')
        print(f'   空状态元素: {len(empty_states)}')
        for s in empty_states[:10]:
            print(f'   {s}')

        # 查找包含"小巩票务"对话的相关链接
        print('4. 查找用户相关链接...')
        user_links = await page.evaluate('''() => {
            const links = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href;
                if (href.includes('goofish') && (
                    href.includes('user') ||
                    href.includes('im') ||
                    href.includes('chat')
                )) {
                    links.push(href);
                }
            });
            return links;
        }''')
        print(f'   用户相关链接: {json.dumps(user_links[:10], ensure_ascii=False)}')

        # 尝试查找数据加载区域
        print('5. 查找数据加载区域...')
        data_areas = await page.evaluate('''() => {
            const areas = [];
            // 查找所有有data-*属性的元素
            document.querySelectorAll('[data-conversation], [data-msg], [data-chat], [data-session]').forEach(el => {
                areas.push({
                    tag: el.tagName,
                    class: el.className.substring(0, 50),
                    data: Object.entries(el.dataset).join(',')
                });
            });
            // 查找所有有id的元素
            document.querySelectorAll('#conversation, #messages, #chat, #im').forEach(el => {
                areas.push({
                    tag: el.tagName,
                    id: el.id,
                    class: el.className.substring(0, 50)
                });
            });
            return areas;
        }''')
        print(f'   数据区域: {json.dumps(data_areas, ensure_ascii=False)}')

        await page.screenshot(path='/tmp/xianyu_empty_check.png', full_page=True)
        print('   截图: /tmp/xianyu_empty_check.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_empty())