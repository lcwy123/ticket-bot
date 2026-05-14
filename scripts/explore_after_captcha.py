#!/usr/bin/env python3
"""关闭验证码后分析页面"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def analyze_after_close():
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

        # 截图
        await page.screenshot(path='/tmp/xianyu_no_captcha.png')
        print('   截图: /tmp/xianyu_no_captcha.png')

        # 获取页面文本
        print('2. 获取页面文本...')
        texts = await page.evaluate('''() => {
            const texts = [];
            document.querySelectorAll("*").forEach(el => {
                const text = el.innerText?.trim();
                if (text && text.length > 1 && text.length < 100 && el.children.length === 0) {
                    texts.push(text.substring(0, 60));
                }
            });
            return texts;
        }''')

        seen = set()
        unique = []
        for t in texts:
            if t not in seen and len(t) > 2:
                seen.add(t)
                unique.append(t)

        print(f'   找到 {len(unique)} 个唯一文本')
        for t in unique[:25]:
            print(f'   {t}')

        # 查找输入框
        print('3. 查找输入框...')
        inputs = await page.query_selector_all('input, textarea, [contenteditable]')
        print(f'   找到 {len(inputs)} 个输入元素')
        for inp in inputs[:5]:
            try:
                cls = await inp.get_attribute('class') or ''
                ph = await inp.get_attribute('placeholder') or ''
                print(f'   class={cls[:60]}, placeholder={ph[:30]}')
            except:
                pass

        # 查找按钮
        print('4. 查找按钮...')
        btns = await page.query_selector_all('button')
        print(f'   找到 {len(btns)} 个按钮')
        for btn in btns[:10]:
            try:
                text = await btn.inner_text()
                cls = await btn.get_attribute('class') or ''
                if text.strip():
                    print(f'   "{text.strip()[:30]}" class={cls[:60]}')
            except:
                pass

        # 查找对话列表
        print('5. 查找对话列表...')
        conv_list = await page.query_selector_all('[class*="conversation"]')
        print(f'   对话容器: {len(conv_list)}')

        conv_items = await page.query_selector_all('[class*="conv-item"], [class*="conversation-item"]')
        print(f'   对话项: {len(conv_items)}')

        # 查找所有div内容
        print('6. 查找所有class包含chat/message/msg的div...')
        result = await page.evaluate('''() => {
            const classes = [];
            document.querySelectorAll("div").forEach(el => {
                const cls = el.className || "";
                if (cls.includes("chat") || cls.includes("message") || cls.includes("msg") || cls.includes("dialog")) {
                    classes.push(cls.substring(0, 80));
                }
            });
            return classes;
        }''')
        print(f'   {result}')

        await browser.close()
        print('完成')


if __name__ == "__main__":
    asyncio.run(analyze_after_close())