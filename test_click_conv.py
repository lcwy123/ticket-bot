#!/usr/bin/env python3
"""测试点击会话查看聊天记录"""
import asyncio
import sys
sys.path.insert(0, '/home/gzh0328/.openclaw/workspace-projector/ticket-bot')

from app.services.xianyu_browser import XianyuBrowser

async def test_click():
    browser = XianyuBrowser()
    await browser.init(headless=False)
    await browser.load_cookies()

    print("Going to IM page...")
    await browser.page.goto("https://www.goofish.com/im", timeout=60000)
    await browser.page.wait_for_load_state("networkidle", timeout=60000)
    await asyncio.sleep(5)

    await browser.page.screenshot(path='/tmp/click_test1.png')
    print(f"Screenshot 1 saved, URL: {browser.page.url}")

    # 查找会话项
    conv_items = await browser.page.query_selector_all("[class*='item--']")
    print(f"Found {len(conv_items)} conversation items")

    for i, item in enumerate(conv_items[:5]):
        try:
            text = await item.inner_text()
            print(f"  Item {i}: {text[:80]!r}")
        except:
            print(f"  Item {i}: (error reading)")

    # 找到"小巩票务"并点击
    for i, item in enumerate(conv_items):
        try:
            text = await item.inner_text()
            if '小巩票务' in text:
                print(f"\nFound '小巩票务' at index {i}, clicking...")

                # 使用JavaScript点击
                result = await browser.page.evaluate('''
                    (element) => {
                        element.click();
                        return "clicked";
                    }
                ''', item)
                print(f"JS click result: {result}")

                await asyncio.sleep(3)

                await browser.page.screenshot(path='/tmp/click_test2.png')
                print(f"Screenshot 2 saved, URL: {browser.page.url}")

                # 检查右侧聊天区域
                body_text = await browser.page.inner_text("body")
                print(f"Page text after click: {body_text[:500]!r}")

                break
        except Exception as e:
            print(f"Error: {e}")
            continue

    await asyncio.sleep(5)
    await browser.close()
    print("\nDone")

if __name__ == "__main__":
    asyncio.run(test_click())