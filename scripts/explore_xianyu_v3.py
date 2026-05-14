#!/usr/bin/env python3
"""
闲鱼消息页面探索 - V3
等待动态内容加载，然后查找对话项和发送消息
"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def explore_with_wait():
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
        await asyncio.sleep(3)

        # 等待对话列表加载
        print("2. 等待对话列表加载...")
        try:
            conv_list = await page.wait_for_selector("[class*='conversation-list']", timeout=10000)
            print(f"   对话列表容器已找到: {conv_list}")
        except:
            print("   未找到对话列表容器")

        # 多次滚动触发加载
        print("3. 滚动触发加载...")
        for i in range(10):
            await page.evaluate("document.querySelector('[class*=\"conversation-list\"]')?.scrollTo(0, 99999)")
            await asyncio.sleep(0.5)

        await asyncio.sleep(3)

        # 分析对话列表
        print("4. 分析对话列表...")

        # 获取所有对话项
        conv_items = await page.query_selector_all("[class*='conv-item'], [class*='conversation-item'], [class*='msg-item']")
        print(f"   找到对话项: {len(conv_items)}")

        if not conv_items:
            # 尝试查找对话列表内的所有可点击元素
            print("   尝试其他选择器...")
            all_items = await page.evaluate("""
                () => {
                    const convList = document.querySelector('[class*="conversation-list"]');
                    if (!convList) return { error: 'no conv list' };

                    const items = convList.querySelectorAll('[class*="item"], li, [class*="conv"]');
                    return {
                        count: items.length,
                        classes: [...new Set([...items].map(el => el.className.split(' ')[0]))]
                    };
                }
            """)
            print(f"   JavaScript分析: {json.dumps(all_items, ensure_ascii=False)}")

        # 打印对话列表的完整HTML
        print("\n5. 获取对话列表HTML...")
        conv_html = await page.evaluate("""
            () => {
                const conv = document.querySelector('[class*="conversation-list"]');
                return conv ? conv.innerHTML.substring(0, 3000) : 'not found';
            }
        """)
        print(f"   HTML:\n{conv_html}")

        # 截图
        await page.screenshot(path="/tmp/xianyu_im_detailed.png", full_page=True)
        print("\n截图: /tmp/xianyu_im_detailed.png")

        await browser.close()


async def try_navigate_to_chat():
    """尝试导航到具体对话页面"""
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

        # 尝试直接访问带有用户参数的URL
        print("\n尝试直接访问对话页面...")

        # 先获取消息列表中第一个用户的ID
        await page.goto("https://www.goofish.com/im", timeout=60000)
        await asyncio.sleep(5)

        # 使用JS查找用户
        user_info = await page.evaluate("""
            () => {
                // 查找所有可能的用户ID或会话ID
                const results = {
                    links: [],
                    dataAttrs: [],
                    nicks: []
                };

                // 查找链接中的用户ID
                document.querySelectorAll('a[href*="user"], a[href*="im?"], a[href*="conversation"]').forEach(a => {
                    results.links.push(a.href);
                });

                // 查找data-*属性
                document.querySelectorAll('[data-id], [data-user], [data-conversation], [data-session]').forEach(el => {
                    results.dataAttrs.push({
                        id: el.dataset.id || el.dataset.user || el.dataset.conversation || el.dataset.session,
                        class: el.className.substring(0, 50)
                    });
                });

                // 查找nick
                document.querySelectorAll('[class*="nick"]').forEach(el => {
                    results.nicks.push({
                        class: el.className,
                        text: el.innerText?.substring(0, 30)
                    });
                });

                return results;
            }
        """)

        print(f"用户信息: {json.dumps(user_info, indent=2, ensure_ascii=False)}")

        await browser.close()


async def find_input_and_send():
    """查找输入框并尝试发送"""
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

        # 访问消息页面
        await page.goto("https://www.goofish.com/im", timeout=60000)
        await asyncio.sleep(5)

        print("\n查找输入框...")

        # 尝试各种输入框选择器
        input_selectors = [
            "textarea",
            "input[type='text']",
            "input[placeholder*='输入']",
            "input[placeholder*='发消息']",
            "input[placeholder*='say']",
            "[contenteditable='true']",
            "[class*='input']",
            "[class*='editor']",
            "[class*='text-input']",
        ]

        found_inputs = []
        for selector in input_selectors:
            elems = await page.query_selector_all(selector)
            if elems:
                print(f"\n{selector}: 找到 {len(elems)} 个")
                for i, elem in enumerate(elems[:3]):
                    try:
                        info = {
                            "selector": selector,
                            "index": i,
                            "placeholder": await elem.get_attribute("placeholder") or "",
                            "class": await elem.get_attribute("class") or "",
                            "id": await elem.get_attribute("id") or "",
                            "type": await elem.get_attribute("type") or "",
                            "text": (await elem.inner_text())[:30] if await elem.inner_text() else ""
                        }
                        print(f"  {json.dumps(info, ensure_ascii=False)}")
                        found_inputs.append((selector, elem))
                    except Exception as e:
                        print(f"  Error: {e}")

        # 查找发送按钮
        print("\n\n查找发送按钮...")
        btn_selectors = [
            "button",
            "[class*='send']",
            "[class*='submit']",
            "[class*='action']",
            "[class*='icon']",
        ]

        for selector in btn_selectors:
            btns = await page.query_selector_all(selector)
            if btns:
                print(f"\n{selector}: 找到 {len(btns)} 个")
                for i, btn in enumerate(btns[:10]):
                    try:
                        text = await btn.inner_text()
                        cls = await btn.get_attribute("class") or ""
                        disabled = await btn.get_attribute("disabled")
                        if text.strip() or 'send' in cls.lower() or 'submit' in cls.lower():
                            print(f"  {i+1}. text='{text.strip()}', class='{cls[:60]}', disabled={disabled}")
                    except:
                        pass

        # 截图
        await page.screenshot(path="/tmp/xianyu_input_find.png", full_page=True)
        print("\n截图: /tmp/xianyu_input_find.png")

        await browser.close()


async def main():
    print("闲鱼消息页面深度探索 V3\n")
    await explore_with_wait()
    print("\n" + "=" * 60)
    await try_navigate_to_chat()
    print("\n" + "=" * 60)
    await find_input_and_send()
    print("\n探索完成！")


if __name__ == "__main__":
    asyncio.run(main())
