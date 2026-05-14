import random
from typing import Dict, Any


class AntiDetectBrowser:
    """浏览器反检测工具"""

    # 常见User-Agent列表
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]

    # 屏幕分辨率
    SCREEN_SIZES = [
        {"width": 1920, "height": 1080},
        {"width": 1440, "height": 900},
        {"width": 2560, "height": 1440},
        {"width": 1536, "height": 864},
    ]

    # 时区
    TIMEZONES = [
        "Asia/Shanghai",
        "Asia/Hong_Kong",
        "Asia/Singapore",
    ]

    def get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        return random.choice(self.USER_AGENTS)

    def get_browser_context_args(self) -> Dict[str, Any]:
        """获取浏览器上下文参数"""
        screen = random.choice(self.SCREEN_SIZES)
        timezone = random.choice(self.TIMEZONES)

        return {
            "user_agent": self.get_random_user_agent(),
            "viewport": {
                "width": screen["width"],
                "height": screen["height"]
            },
            "locale": "zh-CN",
            "timezone_id": timezone,
            "geolocation": {"longitude": 116.4, "latitude": 39.9},  # 北京
            "permissions": ["geolocation"],
        }

    def get_stealth_js(self) -> str:
        """获取stealth模式JavaScript代码"""
        return """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {
                    description: 'PDF Viewer',
                    filename: 'internal-pdf-viewer',
                    length: 1,
                    name: 'Chrome PDF Plugin'
                }
            ]
        });

        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en']
        });

        window.chrome = {
            runtime: {}
        };

        Object.defineProperty(screen, 'colorDepth', {
            get: () => 24
        });

        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });

        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });
        """
