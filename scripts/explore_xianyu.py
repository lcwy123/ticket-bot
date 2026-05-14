#!/usr/bin/env python3
"""
闲鱼消息页面结构探索脚本
分析消息列表和对话页面的元素结构
"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def explore_message_list():
    """探索消息列表页面结构"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**anti_detect.get_browser_context_args())

        # 加载cookies
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
        await page.wait_for_load_state("networkidle", timeout=30000)
        await asyncio.sleep(5)

        print("=" * 60)
        print("消息列表页面分析")
        print("=" * 60)

        # 1. 获取所有链接和可点击元素
        links = await page.query_selector_all("a[href]")
        print(f"\n找到 {len(links)} 个链接:")
        for i, link in enumerate(links[:20]):
            try:
                href = await link.get_attribute("href")
                text = await link.inner_text()
                if href and ('im' in href or 'user' in href or 'conversation' in href.lower()):
                    print(f"  {i+1}. href={href}, text={text[:50]}")
            except:
                pass

        # 2. 获取消息列表项
        print("\n\n查找消息列表容器...")

        # 尝试各种可能的容器
        selectors = [
            ".conversation-list",
            "[class*='conversation']",
            "[class*='msg-list']",
            "[class*='message-list']",
            ".chat-list",
            "#conversation-list",
            "[class*='inbox']",
            "[class*='chat-history']",
        ]

        for selector in selectors:
            elements = await page.query_selector_all(selector)
            if elements:
                print(f"  {selector}: 找到 {len(elements)} 个")
                # 打印第一个的HTML
                if len(elements) > 0:
                    html = await elements[0].inner_html()
                    print(f"    第一个元素HTML (前500字符):\n    {html[:500]}")

        # 3. 获取带有href的对话项
        print("\n\n查找带有链接的对话项...")
        chat_links = await page.query_selector_all("[class*='conv'] a, [class*='conversation'] a, [class*='msg'] a")
        for i, link in enumerate(chat_links[:10]):
            try:
                href = await link.get_attribute("href")
                text = await link.inner_text()
                print(f"  {i+1}. href={href}, text={text[:50]}")
            except:
                pass

        # 4. 截图
        await page.screenshot(path="/tmp/xianyu_im_list.png", full_page=True)
        print("\n截图已保存到 /tmp/xianyu_im_list.png")

        # 5. 尝试点击第一个对话
        print("\n\n尝试点击第一个对话...")
        clickable = await page.query_selector_all("[class*='conv'], [class*='conversation'], [class*='msg-item']")
        if clickable:
            first = clickable[0]
            html = await first.inner_html()
            print(f"第一个可点击元素HTML:\n{html[:800]}")

            # 尝试提取点击目标
            link_in_item = await first.query_selector("a")
            if link_in_item:
                href = await link_in_item.get_attribute("href")
                print(f"\n点击目标链接: {href}")
            else:
                # 尝试获取data-*属性
                attrs = await first.evaluate("el => JSON.stringify(el.dataset)")
                print(f"元素data属性: {attrs}")

                # 尝试直接点击
                try:
                    await first.click(timeout=2000)
                    await asyncio.sleep(3)
                    print(f"点击后URL: {page.url}")
                    await page.screenshot(path="/tmp/xianyu_after_click.png")
                    print("点击后截图已保存")
                except Exception as e:
                    print(f"点击失败: {e}")

        await browser.close()


async def explore_chat_page():
    """探索对话页面结构"""
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

        # 尝试直接访问一个对话页面
        await page.goto("https://www.goofish.com/im", timeout=60000)
        await asyncio.sleep(3)

        # 查找消息输入框
        print("=" * 60)
        print("对话页面输入框分析")
        print("=" * 60)

        input_selectors = [
            "textarea",
            "input[type='text']",
            "input[placeholder*='发消息']",
            "input[placeholder*='消息']",
            "[contenteditable='true']",
            "[class*='input']",
            "[class*='editor']",
        ]

        for selector in input_selectors:
            elem = await page.query_selector(selector)
            if elem:
                print(f"\n找到输入框: {selector}")
                try:
                    placeholder = await elem.get_attribute("placeholder")
                    print(f"  placeholder: {placeholder}")
                    html = await elem.inner_html()
                    print(f"  HTML: {html[:200]}")
                except:
                    pass

        # 查找发送按钮
        print("\n\n查找发送按钮...")
        send_selectors = [
            "button:has-text('发送')",
            "button:has-text('发消息')",
            "[class*='send']",
            "[class*='submit']",
            "[class*='action']",
        ]

        for selector in send_selectors:
            btns = await page.query_selector_all(selector)
            if btns:
                print(f"\n找到按钮: {selector}, 数量: {len(btns)}")
                for i, btn in enumerate(btns[:5]):
                    try:
                        text = await btn.inner_text()
                        print(f"  {i+1}. text={text}, class={await btn.get_attribute('class')}")
                    except:
                        pass

        await page.screenshot(path="/tmp/xianyu_chat_page.png")
        print("\n截图已保存到 /tmp/xianyu_chat_page.png")

        await browser.close()


async def main():
    print("开始探索闲鱼页面结构...\n")
    await explore_message_list()
    print("\n" + "=" * 60)
    await explore_chat_page()
    print("\n探索完成！")


if __name__ == "__main__":
    asyncio.run(main())
