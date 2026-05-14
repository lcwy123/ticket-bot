#!/usr/bin/env python3
"""安装Playwright浏览器"""

import subprocess
import sys


def main():
    print("Installing Playwright browsers...")

    try:
        # 安装浏览器
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("Chromium installed successfully")

        # 安装依赖
        subprocess.run([sys.executable, "-m", "playwright", "install-deps"], check=True)
        print("Browser dependencies installed successfully")

    except subprocess.CalledProcessError as e:
        print(f"Error installing Playwright: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
