#!/usr/bin/env python3
"""
闲鱼消息探索 - V4 强制刷新+深度等待
"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def explore_v4():
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

        print("1. 强制刷新消息页面...")
        await page.goto("https://www.goofish.com/im", timeout=60000)
        await page.reload()
        await asyncio.sleep(8)  # 等待更长时间

        # 截图看当前状态
        await page.screenshot(path="/tmp/xianyu_v4_initial.png")
        print("   截图: /tmp/xianyu_v4_initial.png")

        print("\n2. 分析对话列表...")
        # 获取对话列表完整HTML
        conv_html = await page.evaluate("""
            () => {
                const conv = document.querySelector('[class*="conversation-list"]');
                if (!conv) return 'NOT FOUND';

                // 获取所有子元素
                const children = [];
                const walk = (el, depth) => {
                    if (depth > 3) return;
                    children.push({
                        tag: el.tagName,
                        class: el.className.substring(0, 60),
                        childCount: el.children.length,
                        text: el.innerText?.substring(0, 50) || ''
                    });
                    [...el.children].forEach(c => walk(c, depth + 1));
                };
                walk(conv, 0);
                return JSON.stringify(children, null, 2);
            }
        """)

        try:
            data = json.loads(conv_html)
            print(f"   对话列表元素数量: {len(data)}")
            for item in data[:20]:
                print(f"   {item['tag']}: {item['class']} | {item['text'][:40]}")
        except:
            print(f"   HTML: {conv_html[:500]}")

        print("\n3. 查找用户相关元素...")
        # 查找可能的用户ID
        user_data = await page.evaluate("""
            () => {
                const result = {
                    // 查找对话列表中的所有链接
                    convLinks: [],
                    // 查找所有包含用户nick的元素
                    nickElements: [],
                    // 查找消息相关的a标签
                    msgLinks: []
                };

                // 对话列表中的链接
                const conv = document.querySelector('[class*="conversation-list"]');
                if (conv) {
                    conv.querySelectorAll('a[href]').forEach(a => {
                        if (a.href) result.convLinks.push(a.href);
                    });
                }

                // nick元素
                document.querySelectorAll('[class*="nick"]').forEach(el => {
                    result.nickElements.push({
                        class: el.className.substring(0, 60),
                        text: el.innerText?.substring(0, 30),
                        href: el.querySelector('a')?.href || 'no link'
                    });
                });

                // 消息相关的链接
                document.querySelectorAll('a[href*="im"], a[href*="user"], a[href*="chat"]').forEach(a => {
                    result.msgLinks.push(a.href);
                });

                return result;
            }
        """)

        print(f"   对话列表链接: {json.dumps(user_data.get('convLinks', [])[:10], ensure_ascii=False)}")
        print(f"   Nick元素: {json.dumps(user_data.get('nickElements', [])[:10], ensure_ascii=False)}")
        print(f"   消息链接: {json.dumps(user_data.get('msgLinks', [])[:10], ensure_ascii=False)}")

        print("\n4. 截图并尝试点击...")
        await page.screenshot(path="/tmp/xianyu_v4.png", full_page=True)

        # 尝试点击页面上的任意元素进入对话
        click_targets = await page.query_selector_all("[class*='conv-item'], [class*='conversation-item'], [class*='msg-item'], [class*='list-item']")
        if click_targets:
            print(f"   找到可点击目标: {len(click_targets)}")
            for i, target in enumerate(click_targets[:3]):
                html = await target.inner_html()
                print(f"   {i+1}. HTML: {html[:200]}")
                try:
                    await target.click(timeout=2000)
                    await asyncio.sleep(3)
                    print(f"   点击后URL: {page.url}")
                    break
                except Exception as e:
                    print(f"   点击失败: {e}")
        else:
            print("   没有找到可点击的对话项")

        # 最终截图
        await page.screenshot(path="/tmp/xianyu_v4_final.png", full_page=True)
        print(f"   最终截图: /tmp/xianyu_v4_final.png")
        print(f"   最终URL: {page.url}")

        await browser.close()


async def explore_input_area():
    """探索输入区域"""
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

        await page.goto("https://www.goofish.com/im", timeout=60000)
        await asyncio.sleep(5)

        print("\n" + "=" * 60)
        print("探索输入和发送区域")
        print("=" * 60)

        # 查找聊天主区域
        chat_main = await page.evaluate("""
            () => {
                const main = document.querySelector('[class*="chat-main"], [class*="conversation-detail"], [class*="chat-detail"]');
                if (!main) return { found: false };

                return {
                    found: true,
                    className: main.className,
                    innerHTML: main.innerHTML.substring(0, 2000)
                };
            }
        """)
        print(f"\n聊天主区域:\n{json.dumps(chat_main, indent=2, ensure_ascii=False)}")

        await page.screenshot(path="/tmp/xianyu_chat_area.png", full_page=True)
        print("\n截图: /tmp/xianyu_chat_area.png")

        await browser.close()


async def main():
    print("闲鱼消息探索 V4 - 强制刷新+深度等待\n")
    await explore_v4()
    print("\n" + "=" * 60)
    await explore_input_area()
    print("\n探索完成！")


if __name__ == "__main__":
    asyncio.run(main())
