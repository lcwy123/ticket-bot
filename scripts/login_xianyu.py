#!/usr/bin/env python3
"""
闲鱼登录脚本 - 使用账号密码登录并保持session
"""
import asyncio
from app.services.xianyu_browser import XianyuBrowser

async def main():
    browser = XianyuBrowser(user_data_dir="/tmp/xianyu_browser_data")
    await browser.init()

    print("请在浏览器中完成登录验证...")
    result = await browser.login_with_password()

    if result == "needs_verification":
        print("需要验证，请手动完成验证...")
        # 等待用户手动验证
        success = await browser.wait_for_verification(timeout=120)
        if success:
            print("登录成功！Session已保存。")
        else:
            print("验证超时，请重试。")
    elif result == True:
        print("登录成功！")
    else:
        print(f"登录失败: {result}")

    await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
