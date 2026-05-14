#!/usr/bin/env python3
"""
闲鱼消息页面深度探索 - V2
1. 滚动加载消息
2. 使用JS分析DOM结构
3. 找到可点击的对话项
"""
import asyncio
import json
from playwright.async_api import async_playwright
from app.services.browser.anti_detect import AntiDetectBrowser

anti_detect = AntiDetectBrowser()


async def explore_deep():
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
        await asyncio.sleep(2)

        print("页面加载，等待内容...")

        # 滚动页面触发加载
        for i in range(5):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            print(f"滚动 {i+1}/5")

        await asyncio.sleep(3)

        # 使用JS分析页面结构
        analysis = await page.evaluate("""
            () => {
                const result = {
                    bodyChildren: [],
                    allLinks: [],
                    allDivs: [],
                    scrollInfo: {}
                };

                // 获取body的直接子元素
                document.body.querySelectorAll(':scope > *').forEach((el, i) => {
                    result.bodyChildren.push({
                        tag: el.tagName,
                        className: el.className,
                        id: el.id,
                        childCount: el.children.length
                    });
                });

                // 获取所有链接
                document.querySelectorAll('a[href]').forEach((a, i) => {
                    if (a.href.includes('goofish.com') || a.href.includes('alibaba.com')) {
                        result.allLinks.push({
                            href: a.href,
                            text: a.innerText.substring(0, 50),
                            parent: a.parentElement?.className?.substring(0, 50)
                        });
                    }
                });

                // 查找包含"消息"或"对话"相关关键字的元素
                const keywords = ['nick', 'user', 'buyer', 'seller', 'message', 'conv', 'chat', '对话'];
                keywords.forEach(kw => {
                    document.querySelectorAll(`[class*="${kw}"]`).forEach((el, i) => {
                        if (i < 3) {  // 只取前3个
                            result.allDivs.push({
                                keyword: kw,
                                className: el.className.substring(0, 80),
                                tag: el.tagName,
                                text: el.innerText?.substring(0, 30) || '',
                                hasHref: !!el.querySelector('a[href]')
                            });
                        }
                    });
                });

                // scroll info
                result.scrollInfo = {
                    scrollTop: document.documentElement.scrollTop,
                    scrollHeight: document.documentElement.scrollHeight,
                    clientHeight: document.documentElement.clientHeight
                };

                return result;
            }
        """)

        print("\n" + "=" * 60)
        print("页面DOM分析结果")
        print("=" * 60)

        print(f"\nBody子元素数量: {len(analysis['bodyChildren'])}")
        for item in analysis['bodyChildren'][:10]:
            print(f"  {item['tag']}: class={item['className'][:60]}, children={item['childCount']}")

        print(f"\n相关链接数量: {len(analysis['allLinks'])}")
        for link in analysis['allLinks'][:15]:
            print(f"  {link['href']}")
            print(f"    text={link['text']}, parent={link['parent']}")

        print(f"\n关键词匹配元素:")
        for item in analysis['allDivs'][:20]:
            print(f"  [{item['keyword']}] {item['tag']}: class={item['className']}, text={item['text'][:30]}")

        print(f"\n滚动信息: {analysis['scrollInfo']}")

        # 截图
        await page.screenshot(path="/tmp/xianyu_im_explore.png", full_page=True)
        print("\n截图: /tmp/xianyu_im_explore.png")

        # 尝试点击任何可疑的对话项
        print("\n\n尝试查找并点击对话项...")

        # 尝试各种选择器
        selectors_to_try = [
            "[class*='conv-item']",
            "[class*='conversation-item']",
            "[class*='msg-item']",
            "[class*='chat-item']",
            "[class*='dialog-item']",
            "[class*='list-item']",
            "li[class*='item']",
            "[class*='contact']",
        ]

        for sel in selectors_to_try:
            items = await page.query_selector_all(sel)
            if items:
                print(f"\n找到: {sel} - {len(items)}个")
                for i, item in enumerate(items[:3]):
                    html = await item.inner_html()
                    text = await item.inner_text()
                    print(f"  {i+1}. text={text[:50]}")
                    print(f"     html={html[:200]}")

        # 直接获取所有li元素
        print("\n\n所有li元素:")
        lis = await page.query_selector_all("li")
        print(f"总共 {len(lis)} 个li")
        for i, li in enumerate(lis[:10]):
            try:
                text = await li.inner_text()
                cls = await li.get_attribute("class") or ""
                if text.strip():
                    print(f"  {i+1}. class={cls[:60]}, text={text[:50]}")
            except:
                pass

        await browser.close()


async def try_click_conversation():
    """尝试直接点击进入对话"""
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

        # 尝试使用JS模拟点击第一个对话
        result = await page.evaluate("""
            () => {
                // 尝试找到对话列表容器
                const containers = document.querySelectorAll('[class*="conv"], [class*="list"], [class*="chat"]');
                console.log('找到容器:', containers.length);

                // 尝试找到所有可点击项
                const items = document.querySelectorAll('[class*="item"], li, [class*="conv"]');
                console.log('找到items:', items.length);

                // 打印第一个有意义的内容
                for (let el of items) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 5 && text.length < 100) {
                        console.log('元素:', el.className, 'text:', text.substring(0, 50));
                    }
                }

                // 查找消息列表区域
                const msgArea = document.querySelector('.message-area, #message, [class*="message"], [class*="chat"]');
                if (msgArea) {
                    return {
                        found: true,
                        className: msgArea.className,
                        innerHTML: msgArea.innerHTML.substring(0, 500)
                    };
                }

                return { found: false };
            }
        """)

        print("\n" + "=" * 60)
        print("对话区域探索")
        print("=" * 60)
        print(json.dumps(result, indent=2, ensure_ascii=False))

        await browser.close()


async def main():
    print("深度探索闲鱼页面...\n")
    await explore_deep()
    print("\n" + "=" * 60)
    await try_click_conversation()
    print("\n探索完成！")


if __name__ == "__main__":
    asyncio.run(main())
