import json
import asyncio
from typing import Optional, List, Dict
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from loguru import logger

from app.config import get_settings
from app.services.browser.anti_detect import AntiDetectBrowser

settings = get_settings()


class XianyuBrowser:
    """闲鱼无头浏览器操作"""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.anti_detect = AntiDetectBrowser()
        self.sms_code_event: Optional[asyncio.Event] = None
        self.sms_code: Optional[str] = None

    async def init(self, headless: bool = False):
        """初始化浏览器

        Args:
            headless: 是否使用无头模式，默认为False（显示浏览器窗口）
        """
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=headless,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        self.context = await self.browser.new_context(
            **self.anti_detect.get_browser_context_args()
        )
        self.page = await self.context.new_page()
        logger.info(f"Xianyu browser initialized (headless={headless})")
        return self

    async def load_cookies(self, cookies_file: str = "/opt/ticket-bot/xianyu_cookies.json") -> bool:
        """加载cookies"""
        try:
            with open(cookies_file, 'r') as f:
                cookies = json.load(f)

            for cookie in cookies:
                cookie.pop('sameSite', None)
                try:
                    await self.context.add_cookies([cookie])
                except Exception as e:
                    logger.debug(f"Could not add cookie {cookie.get('name')}: {e}")

            logger.info("Cookies loaded")
            return True
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")
            return False

    async def ensure_logged_in(self) -> bool:
        """确保已登录 - 通过页面内容检测"""
        if not self.page:
            await self.init()
            await self.load_cookies()

        try:
            await self.page.goto("https://www.goofish.com", timeout=30000)
            await self.page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(3)

            # 检查URL - 如果包含login说明在登录页
            current_url = self.page.url
            if 'login' in current_url.lower():
                logger.warning(f"Not logged in, redirected to: {current_url}")
                return False

            # 检查页面是否包含用户标识元素（如"我的"、"消息"、用户头像等）
            content = await self.page.content()

            # 登录后的特征元素
            logged_in_indicators = [
                '我的', '消息', '消息中心', 'goofish.com/im',
                'xy450165272350',  # 可能的用户ID
            ]

            # 未登录的特征（登录表单）
            not_logged_in_indicators = [
                'fm-login-id', 'fm-login-password', 'login-phone',
                'login-password', 'login-btn', 'sms-login',
            ]

            # 如果出现登录表单元素，说明未登录
            for indicator in not_logged_in_indicators:
                if indicator in content:
                    logger.warning(f"Not logged in, found indicator: {indicator}")
                    return False

            # 如果出现登录后特征，说明已登录
            for indicator in logged_in_indicators:
                if indicator in content:
                    logger.info(f"Logged in, found indicator: {indicator}")
                    return True

            # 如果都不满足，尝试检查是否有明显登录元素
            user_elements = await self.page.query_selector_all(
                "[class*='user-info'], [class*='avatar'], [class*='profile'], [class*='mine'], [class*='my-']"
            )
            if user_elements:
                logger.info("Logged in (user elements found)")
                return True

            logger.warning("Could not determine login status")
            return False

        except Exception as e:
            logger.error(f"Check login failed: {e}")
            return False

    async def login_with_password(self) -> bool:
        """使用账号密码登录"""
        if not self.page:
            await self.init()

        try:
            await self.page.goto("https://www.goofish.com", timeout=60000)
            await self.page.wait_for_load_state("load", timeout=60000)
            await asyncio.sleep(2)

            await self.page.fill("#fm-login-id", settings.xianyu_phone)
            await self.page.fill("#fm-login-password", settings.xianyu_password)
            await self.page.click(".fm-btn")
            await asyncio.sleep(5)

            if await self.ensure_logged_in():
                return True

            return "needs_verification"

        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    async def wait_for_verification(self, timeout: int = 120) -> bool:
        """等待用户完成验证"""
        logger.info(f"Waiting for verification (timeout: {timeout}s)...")

        for i in range(timeout):
            await asyncio.sleep(1)
            if await self.ensure_logged_in():
                # 保存cookies
                cookies = await self.context.cookies()
                with open('/opt/ticket-bot/xianyu_cookies.json', 'w') as f:
                    json.dump(cookies, f, indent=2)
                logger.info("Cookies saved after verification")
                return True

            if i % 10 == 0:
                logger.info(f"Still waiting... ({i}s)")

        return False

    async def login_with_sms(self) -> bool:
        """
        使用短信验证码登录
        调用此方法后，需要调用 set_sms_code() 输入验证码才能完成登录
        """
        if not self.page:
            await self.init()

        try:
            await self.page.goto("https://www.goofish.com", timeout=60000)
            await self.page.wait_for_load_state("load", timeout=60000)
            await asyncio.sleep(2)

            # 点击"短信验证码登录"链接
            # 闲鱼登录页可能有多种选择器
            sms_link_selectors = [
                "[class*='sms-login']",
                "[class*='phone-login']",
                "[class*='tab-sms']",
                ".sms-login-link",
                "a[href*='sms']",
                "[class*='login-tab']:has-text('短信')",
            ]

            sms_clicked = False
            for selector in sms_link_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        await elem.click()
                        sms_clicked = True
                        logger.info(f"Clicked SMS login link with selector: {selector}")
                        break
                except Exception:
                    continue

            if not sms_clicked:
                # 尝试直接访问短信登录URL
                await self.page.goto("https://www.goofish.com/login?sms=1", timeout=30000)
                await asyncio.sleep(2)

            await asyncio.sleep(1)

            # 输入手机号
            phone_input_selectors = [
                "input[name='phone']",
                "input[type='tel']",
                "input[placeholder*='手机']",
                "input[placeholder*='phone']",
                "#fm-phone",
            ]

            phone_filled = False
            for selector in phone_input_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        await elem.fill(settings.xianyu_phone)
                        phone_filled = True
                        logger.info(f"Filled phone with selector: {selector}")
                        break
                except Exception:
                    continue

            if not phone_filled:
                # 尝试更通用的选择器
                inputs = await self.page.query_selector_all("input[type='text'], input[type='tel']")
                for inp in inputs:
                    try:
                        await inp.fill(settings.xianyu_phone)
                        phone_filled = True
                        logger.info("Filled phone with generic input")
                        break
                    except Exception:
                        continue

            if not phone_filled:
                logger.error("Could not find phone input field")
                return False

            # 点击发送验证码
            send_btn_selectors = [
                "[class*='send-code']",
                "[class*='get-code']",
                "[class*='sms-btn']",
                "button:has-text('发送')",
                "button:has-text('获取')",
                ".send-sms-btn",
            ]

            for selector in send_btn_selectors:
                try:
                    btn = await self.page.query_selector(selector)
                    if btn:
                        await btn.click()
                        logger.info(f"Clicked send code button with selector: {selector}")
                        break
                except Exception:
                    continue

            await asyncio.sleep(1)

            # 创建异步事件用于等待验证码输入
            self.sms_code_event = asyncio.Event()
            self.sms_code = None

            logger.info("SMS code sent. Waiting for code input...")
            logger.info("Please call set_sms_code(code) to provide the verification code")

            # 等待验证码输入（最多等待120秒）
            try:
                await asyncio.wait_for(self.sms_code_event.wait(), timeout=120)
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for SMS code")
                return False

            if not self.sms_code:
                logger.error("No SMS code received")
                return False

            # 输入验证码
            code_input_selectors = [
                "input[name='code']",
                "input[name='smsCode']",
                "input[placeholder*='验证码']",
                "input[placeholder*='code']",
                "#fm-sms-code",
            ]

            code_filled = False
            for selector in code_input_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        await elem.fill(self.sms_code)
                        code_filled = True
                        logger.info(f"Filled SMS code with selector: {selector}")
                        break
                except Exception:
                    continue

            if not code_filled:
                # 尝试更通用的选择器
                inputs = await self.page.query_selector_all("input")
                for inp in inputs:
                    try:
                        await inp.fill(self.sms_code)
                        code_filled = True
                        logger.info("Filled SMS code with generic input")
                        break
                    except Exception:
                        continue

            if not code_filled:
                logger.error("Could not find SMS code input field")
                return False

            await asyncio.sleep(0.5)

            # 点击登录按钮
            login_btn_selectors = [
                "[class*='login-btn']",
                "[class*='submit-btn']",
                "button:has-text('登录')",
                "button:has-text('登入')",
                ".fm-btn",
            ]

            for selector in login_btn_selectors:
                try:
                    btn = await self.page.query_selector(selector)
                    if btn:
                        await btn.click()
                        logger.info(f"Clicked login button with selector: {selector}")
                        break
                except Exception:
                    continue

            await asyncio.sleep(5)

            # 检查是否登录成功
            if await self.ensure_logged_in():
                # 保存cookies
                cookies = await self.context.cookies()
                with open('/opt/ticket-bot/xianyu_cookies.json', 'w') as f:
                    json.dump(cookies, f, indent=2)
                logger.info("SMS login successful, cookies saved")
                return True

            logger.warning("SMS login may have failed")
            return False

        except Exception as e:
            logger.error(f"SMS login failed: {e}")
            return False

    def set_sms_code(self, code: str):
        """
        设置短信验证码（供外部调用）
        与 login_with_sms() 配合使用
        """
        if self.sms_code_event and not self.sms_code_event.is_set():
            self.sms_code = code
            self.sms_code_event.set()
            logger.info("SMS code received")
        else:
            logger.warning("SMS code event not waiting or already set")

    async def wait_for_sms_code(self, timeout: int = 120) -> Optional[str]:
        """
        等待短信验证码（异步等待）
        返回输入的验证码
        """
        if not self.sms_code_event:
            self.sms_code_event = asyncio.Event()

        try:
            await asyncio.wait_for(self.sms_code_event.wait(), timeout=timeout)
            return self.sms_code
        except asyncio.TimeoutError:
            return None

    async def get_messages(self) -> List[Dict]:
        """获取闲鱼消息"""
        if not await self.ensure_logged_in():
            return []

        try:
            await self.page.goto("https://www.goofish.com/im", timeout=30000)
            await self.page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(5)

            messages = []
            items = await self.page.query_selector_all(
                "[class*='conversation'], [class*='conv'], [class*='msg-item'], [class*='dialog']"
            )

            for item in items[:20]:
                try:
                    text = await item.inner_text()
                    if text.strip():
                        messages.append({"raw": text.strip()})
                except:
                    continue

            logger.info(f"Found {len(messages)} messages")
            return messages

        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            return []

    async def send_message(self, to_user: str, message: str) -> bool:
        """发送消息"""
        if not await self.ensure_logged_in():
            return False

        try:
            await self.page.goto(f"https://www.goofish.com/im?receiver={to_user}", timeout=30000)
            await asyncio.sleep(2)

            input_box = await self.page.query_selector("textarea, [contenteditable='true']")
            if input_box:
                await input_box.fill(message)
                await asyncio.sleep(0.5)
                send_btn = await self.page.query_selector("[class*='send'] button, .submit-btn")
                if send_btn:
                    # 使用JavaScript点击避免超时
                    await self.page.evaluate('''
                        (btn) => btn.click()
                    ''', send_btn)
                    return True

            return False

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def login(self, prefer_sms: bool = True) -> bool:
        """
        统一登录入口

        Args:
            prefer_sms: 是否优先使用短信登录，默认True

        Returns:
            True if login successful

        Usage:
            # 短信登录（需要手动输入验证码）
            browser = XianyuBrowser()
            await browser.login(prefer_sms=True)
            # 在另一个线程/协程中输入验证码
            browser.set_sms_code("123456")
        """
        # 先尝试加载cookies
        await self.load_cookies()

        # 检查是否已登录
        if await self.ensure_logged_in():
            logger.info("Already logged in via cookies")
            return True

        # 未登录，尝试登录
        if prefer_sms:
            # 优先尝试短信登录
            logger.info("Attempting SMS login...")
            result = await self.login_with_sms()
            if result:
                return True

            # 短信登录失败，尝试密码登录
            logger.warning("SMS login failed, falling back to password login...")
            return await self.login_with_password()
        else:
            # 直接使用密码登录
            return await self.login_with_password()

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            logger.info("Xianyu browser closed")

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
