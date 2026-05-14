#!/usr/bin/env python3
"""
闲鱼消息探索 - 搜索用户并进入对话
"""
import asyncio
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def explore_search_and_chat():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**anti_detect.get_browser_context_args())

        import json
        with open('/opt/ticket-bot/xianyu_cookies.json', 'r') as f:
            cookies = json.load(f)
        for cookie in cookies:
            cookie.pop('sameSite', None)
            try:
                await context.add_cookies([cookie])
            except:
                pass

        page = await context.new_page()

        # 1. 访问消息页面
        print("1. 访问消息页面...")
        await page.goto("https://www.goofish.com/im", timeout=60000)
        await asyncio.sleep(3)

        # 2. 查找页面上的所有按钮和链接
        print("\n2. 页面导航元素:")
        elements = await page.query_selector_all("a, button, [class*='tab'], [class*='menu']")
        for el in elements[:20]:
            try:
                text = await el.inner_text()
                cls = await el.get_attribute("class") or ""
                href = await el.get_attribute("href") or ""
                if text.strip():
                    print(f"  {cls[:40]}: {text.strip()[:30]} href={href[:50]}")
            except:
                pass

        # 3. 尝试查找新建消息按钮
        print("\n3. 查找新建消息入口...")
        new_msg_selectors = [
            "[class*='new-msg']",
            "[class*='compose']",
            "[class*='create']",
            "[class*='add']",
            "button:has-text('新消息')",
            "button:has-text('发起聊天')",
            "button:has-text('+')",
            "[class*='icon-plus']",
        ]
        for sel in new_msg_selectors:
            elems = await page.query_selector_all(sel)
            if elems:
                print(f"  {sel}: 找到 {len(elems)} 个")
                for el in elems[:3]:
                    text = await el.inner_text()
                    print(f"    text='{text}', class='{(await el.get_attribute('class') or '')[:50]}'")

        # 4. 尝试直接访问一个假设的对话URL
        print("\n4. 尝试直接访问对话URL...")
        test_urls = [
            "https://www.goofish.com/im?receiver=test",
            "https://www.goofish.com/im?user=test",
            "https://www.goofish.com/chat/test",
            "https://www.goofish.com/message/test",
        ]
        for url in test_urls:
            try:
                await page.goto(url, timeout=10000)
                await asyncio.sleep(1)
                print(f"  {url}: {page.url}")
            except:
                print(f"  {url}: failed")

        # 5. 截图
        await page.screenshot(path="/tmp/xianyu_im_full.png", full_page=True)
        print("\n截图: /tmp/xianyu_im_full.png")

        # 6. 尝试点击新建消息
        print("\n5. 尝试点击新建消息...")
        add_btns = await page.query_selector_all("[class*='add'], [class*='plus'], [class*='create']")
        if add_btns:
            for btn in add_btns[:3]:
                try:
                    await btn.click(timeout=1000)
                    await asyncio.sleep(2)
                    print(f"  点击成功, URL: {page.url}")
                    await page.screenshot(path="/tmp/xianyu_after_add.png")
                    break
                except Exception as e:
                    print(f"  点击失败: {e}")

        await browser.close()


async def explore_network_requests():
    """探索发送消息的网络请求"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**anti_detect.get_browser_context_args())

        import json
        with open('/opt/ticket-bot/xianyu_cookies.json', 'r') as f:
            cookies = json.load(f)
        for cookie in cookies:
            cookie.pop('sameSite', None)
            try:
                await context.add_cookies([cookie])
            except:
                pass

        page = await context.new_page()

        # 监听网络请求
        print("\n监听发送消息的API请求...")

        # 尝试查找所有API端点
        await page.goto("https://www.goofish.com/im", timeout=60000)
        await asyncio.sleep(3)

        # 使用JS查找可能的API配置
        api_info = await page.evaluate("""
            () => {
                // 查找window对象中的API配置
                const info = {
                    apiBase: window.API_BASE || window.API_URL || window.BASE_URL || 'not found',
                    chatApi: window.CHAT_API || window.MSG_API || 'not found',
                    endpoints: []
                };

                // 查找script标签中的API配置
                document.querySelectorAll('script').forEach(script => {
                    const content = script.innerHTML;
                    if (content.includes('api') || content.includes('message') || content.includes('chat')) {
                        // 提取可能的API路径
                        const matches = content.match(/["']([^"']*(?:api|msg|chat)[^"']*)["']/gi);
                        if (matches) {
                            info.endpoints.push(...matches.slice(0, 5));
                        }
                    }
                });

                return info;
            }
        """)

        print(f"API信息: {json.dumps(api_info, ensure_ascii=False)}")

        await browser.close()


async def main():
    print("闲鱼搜索和对话探索\n")
    await explore_search_and_chat()
    print("\n" + "=" * 60)
    await explore_network_requests()
    print("\n探索完成！")


if __name__ == "__main__":
    asyncio.run(main())
