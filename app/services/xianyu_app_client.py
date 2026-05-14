"""
闲鱼APP客户端 - 通过纯ADB命令控制Android真机
不依赖uiautomator2服务端，仅使用adb shell命令
"""
import os
import time
import subprocess
import tempfile
from typing import List, Optional, Dict, Tuple
from loguru import logger

settings = None


def _get_settings():
    global settings
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    return settings


class ADBDevice:
    """ADB设备封装"""

    def __init__(self, serial: str):
        self.serial = serial
        self._screen_size: Optional[Tuple[int, int]] = None

    def _run(self, cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """执行ADB命令"""
        full_cmd = ["adb", "-s", self.serial] + cmd
        return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)

    def _run_async(self, cmd: List[str], timeout: int = 30):
        """异步执行ADB命令"""
        full_cmd = ["adb", "-s", self.serial] + cmd
        return subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @property
    def screen_size(self) -> Tuple[int, int]:
        """获取屏幕分辨率"""
        if self._screen_size is None:
            result = self._run(["shell", "wm", "size"])
            if result.returncode == 0:
                # 输出格式: "Physical size: 1080x2400"
                output = result.stdout.strip()
                if "x" in output:
                    parts = output.split(":")[-1].strip().split("x")
                    self._screen_size = (int(parts[0]), int(parts[1]))
                else:
                    self._screen_size = (1080, 2400)
            else:
                self._screen_size = (1080, 2400)
        return self._screen_size

    def screenshot(self) -> bytes:
        """截图"""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            remote_path = "/sdcard/screen.png"
            local_path = f.name

        try:
            # 截图到手机
            self._run(["shell", "screencap", "-p", remote_path], timeout=10)
            # 拉取到本地
            self._run(["pull", remote_path, local_path], timeout=10)
            # 读取图片数据
            with open(local_path, "rb") as f:
                return f.read()
        finally:
            # 清理临时文件
            if os.path.exists(local_path):
                os.remove(local_path)
            self._run(["shell", "rm", "-f", remote_path])

    def click(self, x: int, y: int) -> bool:
        """点击坐标"""
        result = self._run(["shell", "input", "tap", str(x), str(y)], timeout=10)
        if result.returncode == 0:
            logger.debug(f"Clicked ({x}, {y})")
            return True
        logger.error(f"Click failed: {result.stderr}")
        return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        """滑动"""
        duration = duration_ms // 10  # adb input swipe 参数单位是毫秒，但有些版本要求不同
        result = self._run(
            ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            timeout=10
        )
        if result.returncode == 0:
            logger.debug(f"Swiped ({x1},{y1}) -> ({x2},{y2})")
            return True
        logger.error(f"Swipe failed: {result.stderr}")
        return False

    def input_text(self, text: str) -> bool:
        """输入文本"""
        # 文本中的特殊字符需要转义
        text = text.replace(" ", "%s").replace("'", "\\'").replace("\n", "\\n")
        result = self._run(["shell", "input", "text", text], timeout=10)
        if result.returncode == 0:
            logger.debug(f"Input text: {text[:20]}...")
            return True
        logger.error(f"Input failed: {result.stderr}")
        return False

    def press_key(self, keycode: str) -> bool:
        """按键（back, home, enter等）"""
        result = self._run(["shell", "input", "keyevent", keycode], timeout=10)
        return result.returncode == 0

    def wake_screen(self) -> bool:
        """唤醒屏幕"""
        result = self._run(["shell", "input", "wake"], timeout=10)
        return result.returncode == 0

    def unlock(self) -> bool:
        """解锁屏幕（滑动解锁）"""
        w, h = self.screen_size
        # 从屏幕底部向上滑动
        self.swipe(w // 2, h * 7 // 8, w // 2, h // 3)
        return True

    def start_app(self, package: str, activity: str = None) -> bool:
        """启动APP"""
        if activity:
            component = f"{package}/{activity}"
        else:
            # 尝试获取启动activity
            result = self._run(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)
            return result.returncode == 0

        result = self._run(["shell", "am", "start", "-n", component], timeout=30)
        if result.returncode == 0:
            logger.info(f"Started {component}")
            return True
        logger.error(f"Start app failed: {result.stderr}")
        return False

    def get_focused_app(self) -> str:
        """获取当前前台APP包名"""
        result = self._run(["shell", "dumpsys", "window", "mCurrentFocus"], timeout=10)
        if result.returncode == 0:
            # 格式: mCurrentFocus=Window{xxx type=xxx u0 com.package.name/activity}
            output = result.stdout
            if "/" in output:
                parts = output.split("/")[0].split(" ")[-1]
                return parts
        return ""

    def dump_ui_xml(self) -> str:
        """获取当前UI层次结构（XML格式）"""
        remote_path = "/sdcard/ui_dump.xml"
        result = self._run(["shell", "uiautomator", "dump", remote_path], timeout=15)
        if result.returncode != 0:
            logger.warning(f"UI dump failed (uiautomator may not be available): {result.stderr}")
            return ""

        local_path = tempfile.mktemp(suffix=".xml")
        try:
            self._run(["pull", remote_path, local_path], timeout=10)
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)
            self._run(["shell", "rm", "-f", remote_path])

    def get_device_info(self) -> Dict:
        """获取设备信息"""
        info = {}
        result = self._run(["shell", "getprop", "ro.product.model"])
        if result.returncode == 0:
            info["model"] = result.stdout.strip()

        result = self._run(["shell", "getprop", "ro.build.version.release"])
        if result.returncode == 0:
            info["version"] = result.stdout.strip()

        info["screen_size"] = self.screen_size
        return info


class XianyuAppClient:
    """通过纯ADB命令控制闲鱼APP（真机）"""

    def __init__(self, device_addr: str = None):
        """
        Args:
            device_addr: 设备地址，格式如 "192.168.31.101:5555"
                       如果为None，则自动发现已连接的设备
        """
        self.device_addr = device_addr
        self.device: Optional[ADBDevice] = None
        self.app_package = "com.taobao.idlefish"
        self.last_conv_name: Optional[str] = None
        self._xianyu_activity = f"{self.app_package}/.maincontainer.activity.MainActivity"

    def _discover_device(self) -> str:
        """自动发现已连接的设备"""
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")[1:]
            for line in lines:
                parts = line.split()
                if len(parts) >= 2 and "device" in parts[1] and "offline" not in parts[1]:
                    device_id = parts[0]
                    logger.info(f"Found device: {device_id}")
                    return device_id
        except Exception as e:
            logger.error(f"Failed to discover device: {e}")

        raise RuntimeError("No Android device found. Please connect a device or configure device_addr")

    def connect(self) -> "XianyuAppClient":
        """连接到真机"""
        if self.device_addr is None:
            device_id = self._discover_device()
        else:
            # 清理地址中的 http:// 前缀
            device_id = self.device_addr.replace("http://", "").replace("tcp:", "").split(":")[0]
            # 处理端口
            if ":" in self.device_addr:
                port = self.device_addr.split(":")[-1]
                device_id = f"{device_id}:{port}"

        logger.info(f"Connecting to device: {device_id}...")
        self.device = ADBDevice(device_id)

        # 确保设备可用
        info = self.device.get_device_info()
        logger.info(f"Connected to device: {info.get('model', 'Unknown')} (Android {info.get('version', '?')})")
        logger.info(f"Screen size: {info.get('screen_size')}")

        return self

    def ensure_app_installed(self) -> bool:
        """确保闲鱼APP已安装"""
        result = self.device._run(["shell", "pm", "path", self.app_package])
        if result.returncode == 0 and result.stdout.strip():
            return True
        logger.warning(f"Xianyu APP not installed on device")
        return False

    def ensure_app_running(self):
        """确保闲鱼APP在运行"""
        current = self.device.get_focused_app()
        if self.app_package in current:
            logger.debug("Xianyu is already running")
            return

        logger.info("Starting Xianyu APP...")
        self.device.start_app(self.app_package)
        time.sleep(3)

    def screenshot(self, path: str = None) -> bytes:
        """截图"""
        if self.device:
            return self.device.screenshot()
        return b""

    def click(self, x: int, y: int) -> bool:
        """点击坐标"""
        if self.device:
            return self.device.click(x, y)
        return False

    def swipe(self, direction: str) -> bool:
        """滑动屏幕"""
        if not self.device:
            return False

        w, h = self.device.screen_size
        cx, cy = w // 2, h // 2

        if direction == "up":
            return self.device.swipe(cx, h * 3 // 4, cx, h // 4)
        elif direction == "down":
            return self.device.swipe(cx, h // 4, cx, h * 3 // 4)
        elif direction == "left":
            return self.device.swipe(w * 3 // 4, cy, w // 4, cy)
        elif direction == "right":
            return self.device.swipe(w // 4, cy, w * 3 // 4, cy)
        return False

    def input_text(self, text: str) -> bool:
        """输入文本"""
        if self.device:
            return self.device.input_text(text)
        return False

    def press_back(self) -> bool:
        """按返回键"""
        if self.device:
            return self.device.press_key("KEYCODE_BACK")
        return False

    def press_home(self) -> bool:
        """按Home键"""
        if self.device:
            return self.device.press_key("KEYCODE_HOME")
        return False

    def keep_alive(self):
        """保活：确保设备屏幕打开、APP在前台"""
        try:
            self.device.wake_screen()
            self.device.unlock()
            self.ensure_app_running()
        except Exception as e:
            logger.warning(f"Keep alive failed: {e}")

    def get_device_info(self) -> Dict:
        """获取设备信息"""
        if self.device:
            return self.device.get_device_info()
        return {}

    def get_conversations(self) -> List[Dict]:
        """获取消息会话列表"""
        # 使用 XML dump 方式获取 UI 层次结构
        # 这种方式不需要 uiautomator2 服务端，系统自带 uiutil
        self.ensure_app_running()

        # 如果不在消息列表，先进入
        # 尝试点击消息 tab
        w, h = self.device.screen_size

        # 闲鱼底部导航：首页|消息|发布|我的
        # 消息 tab 大概在 1/4 屏幕宽度，高度在底部 100 位置
        # 先尝试点击消息入口
        self.device.click(w // 4, h - 100)
        time.sleep(2)

        conversations = []
        seen = set()

        # 获取 UI 层次
        xml_content = self.device.dump_ui_xml()
        if not xml_content:
            logger.warning("Could not dump UI, trying scroll-based approach")
            return self._get_conversations_scroll()

        # 解析 XML 查找会话项
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_content)

            # 查找所有可能的消息项
            # 通常在 RecyclerView 或 ListView 中
            namespaces = {'android': 'http://schemas.android.com/apk/res/android'}

            # 查找包含文本内容的节点
            for node in root.iter():
                text = node.get('text', '')
                if text and len(text) > 1 and len(text) < 30:
                    # 过滤导航项
                    skip_words = ["消息", "首页", "发布", "我的", "发现", "搜索", "通讯录", "订单", "购物车", "收藏"]
                    if any(sw in text for sw in skip_words):
                        continue
                    if text not in seen:
                        seen.add(text)
                        conversations.append({
                            "name": text,
                            "raw_text": text
                        })
        except Exception as e:
            logger.error(f"XML parse error: {e}")

        logger.info(f"Found {len(conversations)} conversations")
        return conversations

    def _get_conversations_scroll(self) -> List[Dict]:
        """通过滚动方式获取会话列表"""
        conversations = []
        seen = set()

        for _ in range(10):
            xml_content = self.device.dump_ui_xml()
            if xml_content:
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(xml_content)
                    for node in root.iter():
                        text = node.get('text', '')
                        if text and 1 < len(text) < 30:
                            skip_words = ["消息", "首页", "发布", "我的", "发现", "搜索", "通讯录"]
                            if any(sw in text for sw in skip_words):
                                continue
                            if text not in seen:
                                seen.add(text)
                                conversations.append({"name": text, "raw_text": text})
                except:
                    pass

            # 向上滚动
            self.swipe("up")
            time.sleep(1)

        # 去重
        unique = {}
        for c in conversations:
            unique[c["name"]] = c
        conversations = list(unique.values())

        logger.info(f"Found {len(conversations)} conversations (scroll mode)")
        return conversations

    def read_messages(self, conv_name: str) -> List[Dict]:
        """读取某会话的消息"""
        # 点击进入该会话
        self._open_conversation(conv_name)
        time.sleep(2)

        messages = []
        xml_content = self.device.dump_ui_xml()

        if not xml_content:
            logger.warning("Could not dump UI for messages")
            return messages

        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_content)
            w, _ = self.device.screen_size

            for node in root.iter():
                text = node.get('text', '')
                if text and len(text) > 0:
                    bounds_str = node.get('bounds', '')
                    if bounds_str:
                        # bounds 格式: "[left,top][right,bottom]"
                        try:
                            coords = bounds_str.replace("[", "").replace("]", ",").split(",")
                            left = int(coords[0])
                            # 根据位置判断是发送还是接收
                            is_mine = left > w // 2
                            direction = "sent" if is_mine else "received"
                            messages.append({
                                "content": text,
                                "direction": direction
                            })
                        except:
                            pass
        except Exception as e:
            logger.error(f"Parse messages error: {e}")

        self.last_conv_name = conv_name
        logger.info(f"Read {len(messages)} messages from {conv_name}")
        return messages

    def _open_conversation(self, conv_name: str):
        """打开指定会话"""
        # 确保在消息列表
        self.ensure_app_running()

        w, h = self.device.screen_size
        # 点击消息 tab
        self.device.click(w // 4, h - 100)
        time.sleep(2)

        # 在 UI 中查找并点击会话
        for _ in range(5):
            xml_content = self.device.dump_ui_xml()
            if xml_content:
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(xml_content)

                    # 查找匹配文本的节点
                    for node in root.iter():
                        text = node.get('text', '')
                        if conv_name in text or text in conv_name:
                            bounds_str = node.get('bounds', '')
                            if bounds_str:
                                coords = bounds_str.replace("[", "").replace("]", ",").split(",")
                                cx = (int(coords[0]) + int(coords[2])) // 2
                                cy = (int(coords[1]) + int(coords[3])) // 2
                                self.device.click(cx, cy)
                                logger.info(f"Opened conversation: {conv_name}")
                                time.sleep(1)
                                self.last_conv_name = conv_name
                                return
                except Exception as e:
                    logger.debug(f"Search conversation error: {e}")

            # 向上滚动继续查找
            self.swipe("up")
            time.sleep(1)

        logger.warning(f"Conversation not found: {conv_name}")

    def send_message(self, conv_name: str, text: str) -> bool:
        """发送消息"""
        # 确保在正确的会话中
        if self.last_conv_name != conv_name:
            self._open_conversation(conv_name)
            time.sleep(1)

        try:
            # 输入文本
            self.device.input_text(text)
            time.sleep(0.5)

            # 点击发送按钮（通常在输入框右侧）
            w, h = self.device.screen_size
            # 发送按钮通常在右下角
            self.device.click(w * 9 // 10, h - 200)
            time.sleep(0.5)

            logger.info(f"Message sent to {conv_name}: {text[:20]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False