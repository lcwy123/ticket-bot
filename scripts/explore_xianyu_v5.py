#!/usr/bin/env python3
"""
闲鱼消息探索 - V5 检查页面所有文本
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

        print("1. 访问消息页面...")
        await page.goto("https://www.goofish.com/im", timeout=60000)
        await asyncio.sleep(8)

        # 截图
        await page.screenshot(path="/tmp/xianyu_msg_check.png", full_page=True)

        # JS深度分析
        result = await page.evaluate("""
            () => {
                const result = {
                    texts: [],
                    unreadBadges: [],
                    allLinks: []
                };

                // 收集所有有意义的文本
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    null
                );

                let node;
                while(node = walker.nextNode()) {
                    const text = node.textContent?.trim();
                    if (text && text.length > 1 && text.length < 200) {
                        result.texts.push(text.substring(0, 80));
                    }
                }

                // 查找未读标记
                document.querySelectorAll('[class*="badge"], [class*="unread"], [class*="count"]').forEach(el => {
                    const text = el.innerText?.trim();
                    if (text) result.unreadBadges.push(text);
                });

                // 查找所有链接
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.href;
                    if (href && (href.includes('goofish') || href.includes('alibaba'))) {
                        result.allLinks.push(href);
                    }
                });

                return result;
            }
        """)

        print(f"\n2. 收集到的文本内容 ({len(result['texts'])} 条):")
        for text in result['texts'][:40]:
            print(f"   {text}")

        print(f"\n3. 未读标记: {result['unreadBadges']}")
        print(f"\n4. 相关链接: {result['allLinks'][:10]}")

        print("\n截图: /tmp/xianyu_msg_check.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(explore())
