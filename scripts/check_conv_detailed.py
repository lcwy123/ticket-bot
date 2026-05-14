#!/usr/bin/env python3
"""检查对话列表详细"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def check_conv():
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

        await asyncio.sleep(3)

        await page.screenshot(path='/tmp/xianyu_conv_check.png', full_page=True)

        # 获取页面所有文本
        print('2. 获取页面所有文本...')
        all_text = await page.evaluate('''() => {
            const texts = [];
            document.querySelectorAll("*").forEach(el => {
                if (el.children.length === 0) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 1 && text.length < 200) {
                        texts.push({
                            tag: el.tagName,
                            class: el.className.substring(0, 60),
                            text: text.substring(0, 80)
                        });
                    }
                }
            });
            return texts;
        }''')

        # 去重
        seen = set()
        unique = []
        for t in all_text:
            key = t['text']
            if key not in seen and len(key) > 2:
                seen.add(key)
                unique.append(t)

        print(f'   唯一文本数量: {len(unique)}')
        for t in unique[:30]:
            print(f'   [{t["tag"]}] {t["text"]}')

        # 查找对话列表
        print('3. 查找对话列表...')
        conv_list = await page.query_selector_all('[class*="conv"]')
        print(f'   conv相关元素: {len(conv_list)}')
        for c in conv_list[:10]:
            try:
                cls = await c.get_attribute('class') or ''
                text = await c.inner_text()
                print(f'   class={cls[:60]}, text={text[:50]}')
            except:
                pass

        # 查找聊天区域
        print('4. 查找聊天区域...')
        chat_areas = await page.query_selector_all('[class*="chat"], [class*="message"], [class*="dialog"]')
        print(f'   聊天相关元素: {len(chat_areas)}')

        # 查找所有li元素
        print('5. 查找所有li元素...')
        lis = await page.query_selector_all('li')
        print(f'   li元素总数: {len(lis)}')
        for li in lis[:10]:
            try:
                text = await li.inner_text()
                cls = await li.get_attribute('class') or ''
                if text.strip():
                    print(f'   li: class={cls[:50]}, text={text[:50]}')
            except:
                pass

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(check_conv())