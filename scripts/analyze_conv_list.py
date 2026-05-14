#!/usr/bin/env python3
"""深度分析对话列表"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def analyze_conv():
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
        await page.screenshot(path='/tmp/xianyu_conv_list.png')

        # 分析页面整体结构
        print('2. 分析页面整体结构...')
        structure = await page.evaluate('''() => {
            const layout = document.querySelector('.ant-layout');
            const chatContainer = document.querySelector('.chat-container');
            const convList = document.querySelector('.conversation-list');
            const sider = document.querySelector('.ant-layout-sider');

            return {
                hasLayout: !!layout,
                hasChatContainer: !!chatContainer,
                hasConvList: !!convList,
                hasSider: !!sider,
                siderHTML: sider ? sider.innerHTML.substring(0, 500) : null
            };
        }''')
        print(f'   结构: {json.dumps(structure, ensure_ascii=False)}')

        # 深入分析sider内容
        print('3. 分析侧边栏内容...')
        sider_content = await page.evaluate('''() => {
            const sider = document.querySelector('.ant-layout-sider');
            if (!sider) return 'no sider';

            const allDivs = sider.querySelectorAll('div');
            const allA = sider.querySelectorAll('a');
            const allLi = sider.querySelectorAll('li');

            let html = sider.innerHTML;
            // 查找包含消息的文本
            const texts = [];
            sider.querySelectorAll('*').forEach(el => {
                const t = el.innerText?.trim();
                if (t) texts.push(t.substring(0, 30));
            });

            return {
                divCount: allDivs.length,
                linkCount: allA.length,
                liCount: allLi.length,
                texts: texts.slice(0, 20)
            };
        }''')
        print(f'   侧边栏: {json.dumps(sider_content, ensure_ascii=False)}')

        # 尝试滚动对话列表
        print('4. 滚动对话列表...')
        await page.evaluate('''() => {
            const sider = document.querySelector('.ant-layout-sider');
            if (sider) {
                sider.scrollTop = 99999;
            }
        }''')
        await asyncio.sleep(2)

        # 再次分析
        print('5. 滚动后再次分析...')
        sider_after = await page.evaluate('''() => {
            const sider = document.querySelector('.ant-layout-sider');
            const texts = [];
            sider.querySelectorAll('*').forEach(el => {
                const t = el.innerText?.trim();
                if (t && t.length > 1) texts.push(t.substring(0, 30));
            });
            return texts.slice(0, 20);
        }''')
        print(f'   滚动后文本: {json.dumps(sider_after, ensure_ascii=False)}')

        # 最终截图
        await page.screenshot(path='/tmp/xianyu_conv_final.png', full_page=True)
        print('   最终截图: /tmp/xianyu_conv_final.png')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(analyze_conv())