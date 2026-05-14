#!/usr/bin/env python3
"""闲鱼消息页面探索 - 等待动态内容"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def explore():
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

        # 等待网络空闲
        print('2. 等待页面加载...')
        try:
            await page.wait_for_load_state('networkidle', timeout=30000)
        except:
            pass
        await asyncio.sleep(3)

        # 截图
        await page.screenshot(path='/tmp/xianyu_msg_wait.png')

        # 分析页面
        print('3. 分析页面结构...')
        result = await page.evaluate("""
            () => {
                // 查找所有可能包含聊天的区域
                const areas = [];
                document.querySelectorAll('div').forEach(el => {
                    const cls = el.className || '';
                    if (cls.includes('chat') || cls.includes('message') ||
                        cls.includes('conversation') || cls.includes('dialog')) {
                        areas.push({
                            class: cls.substring(0, 80),
                            text: el.innerText?.substring(0, 50) || '',
                            childCount: el.children.length
                        });
                    }
                });
                return areas;
            }
        """)
        print(f'   找到 {len(result)} 个聊天相关区域')
        for r in result[:10]:
            print(f'   {r}')

        # 查找对话列表项
        print('4. 查找对话列表项...')
        conv_result = await page.evaluate("""
            () => {
                // 查找对话列表容器
                const containers = document.querySelectorAll('[class*="conversation"], [class*="list"], [class*="chat-list"]');
                return {
                    containerCount: containers.length,
                    classes: [...containers].map(c => c.className.substring(0, 60))
                };
            }
        """)
        print(f'   对话容器: {json.dumps(conv_result)}')

        # 尝试查找消息输入区域
        print('5. 深入分析...')
        deep = await page.evaluate("""
            () => {
                // 查找所有有id或data-*属性的元素
                const elements = [];
                document.querySelectorAll('[id], [data-conversation], [data-chat], [data-msg]').forEach(el => {
                    elements.push({
                        tag: el.tagName,
                        id: el.id || '',
                        class: el.className.substring(0, 50),
                        data: Object.keys(el.dataset).join(',')
                    });
                });
                return elements;
            }
        """)
        print(f'   找到 {len(deep)} 个有特殊属性的元素')
        for d in deep[:10]:
            print(f'   {d}')

        # 查找iframe
        print('6. 查找iframe...')
        iframes = await page.query_selector_all('iframe')
        print(f'   找到 {len(iframes)} 个iframe')
        for iframe in iframes[:3]:
            try:
                src = await iframe.get_attribute('src')
                print(f'   src={src}')
            except:
                pass

        # 滚动到底部
        print('7. 滚动页面触发加载...')
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await asyncio.sleep(2)

        # 最终截图
        await page.screenshot(path='/tmp/xianyu_msg_final.png', full_page=True)

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(explore())