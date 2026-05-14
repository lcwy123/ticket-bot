#!/usr/bin/env python3
"""
闲鱼通知页面探索
"""
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

        print("1. 访问通知页面...")
        url = "https://www.goofish.com/im?spm=a21ybx.home.sidebar.2.4c053da6WOhKfy"
        await page.goto(url, timeout=60000)
        await asyncio.sleep(8)

        print(f"   URL: {page.url}")
        await page.screenshot(path="/tmp/xianyu_notification.png", full_page=True)
        print("   截图: /tmp/xianyu_notification.png")

        print("\n2. 分析页面内容...")

        # 获取所有文本
        result = await page.evaluate("""
            () => {
                const texts = [];
                document.querySelectorAll('*').forEach(el => {
                    const text = el.innerText?.trim();
                    if (text && text.length > 1 && text.length < 200) {
                        texts.push({tag: el.tagName, class: el.className.substring(0,50), text: text.substring(0,60)});
                    }
                });
                return texts;
            }
        """)

        print(f"   找到 {len(result)} 个元素")

        # 打印有意义的文本
        print("\n   文本内容:")
        seen = set()
        for item in result:
            text = item['text']
            if text not in seen and len(text) > 2:
                seen.add(text)
                # 过滤显示有意义的内容
                print(f"   - [{item['tag']}] {item['class'][:50]}: {text}")

        print("\n3. 查找通知列表...")
        selectors = [
            "[class*='notify']",
            "[class*='notification']",
            "[class*='notice']",
            "[class*='msg']",
            "[class*='message']",
            "li"
        ]

        for sel in selectors:
            items = await page.query_selector_all(sel)
            if items:
                print(f"   {sel}: 找到 {len(items)} 个")

        print("\n4. 尝试查找输入框...")
        inputs = await page.query_selector_all("textarea, input[type='text'], [contenteditable='true']")
        print(f"   输入框数量: {len(inputs)}")
        for inp in inputs[:5]:
            try:
                cls = await inp.get_attribute("class") or ""
                ph = await inp.get_attribute("placeholder") or ""
                print(f"   - class={cls[:50]}, placeholder={ph[:30]}")
            except:
                pass

        print("\n5. 查找按钮...")
        btns = await page.query_selector_all("button")
        print(f"   按钮数量: {len(btns)}")
        for btn in btns[:15]:
            try:
                text = await btn.inner_text()
                cls = await btn.get_attribute("class") or ""
                if text.strip():
                    print(f"   - '{text.strip()[:30]}': class={cls[:50]}")
            except:
                pass

        await browser.close()
        print("\n探索完成!")


if __name__ == "__main__":
    asyncio.run(explore())
