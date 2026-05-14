"""
闲鱼消息监听服务 - 增强版
1. 消息聚合 - 合并用户短时间内发送的多条消息
2. 上下文压缩 - 携带历史记录生成回复
3. 主动推荐 - 用户长时间不回复时主动推荐产品
4. 支持两种模式: 浏览器模式 和 APP模式
"""
import asyncio
import signal
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from loguru import logger

from app.config import get_settings
from app.services.xianyu_browser import XianyuBrowser
from app.modules.customer_service.service import CustomerService

import os
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
os.makedirs(log_dir, exist_ok=True)
logger.add(os.path.join(log_dir, "xianyu_listener.log"), rotation="10 MB", retention="7 days")

settings = get_settings()


class MessageAggregator:
    """消息聚合器 - 合并用户短时间内发送的多条消息"""

    def __init__(self, window_seconds: int = 30):
        self.window_seconds = window_seconds
        self.pending_messages = defaultdict(list)  # user_id -> [(timestamp, content), ...]
        self.last_processed = {}  # user_id -> last_processed_time

    def add_message(self, user_id: str, content: str) -> tuple[bool, str]:
        """
        添加消息，返回是否应该处理，以及聚合后的内容
        返回 (should_process, aggregated_content)
        """
        now = datetime.now().timestamp()
        key = f"{user_id}"

        # 添加到待处理队列
        self.pending_messages[key].append((now, content))

        # 清理超时的旧消息
        self.pending_messages[key] = [
            (ts, msg) for ts, msg in self.pending_messages[key]
            if now - ts < self.window_seconds
        ]

        # 如果是新消息（刚添加的第一条），需要处理
        if len(self.pending_messages[key]) == 1:
            return True, content

        # 如果有多条消息，合并后返回
        if len(self.pending_messages[key]) > 1:
            aggregated = self._aggregate(key)
            return True, aggregated

        return False, ""

    def _aggregate(self, user_id: str) -> str:
        """将多条消息合并成一条"""
        messages = self.pending_messages[user_id]
        if not messages:
            return ""

        # 按时间排序
        messages.sort(key=lambda x: x[0])

        # 合并消息内容
        contents = [msg for _, msg in messages]
        if len(contents) == 1:
            return contents[0]

        # 如果是连续消息，用换行合并
        return "\n".join(contents)

    def mark_processed(self, user_id: str):
        """标记已处理，清空该用户的消息队列"""
        key = f"{user_id}"
        self.pending_messages[key] = []
        self.last_processed[key] = datetime.now().timestamp()


class ContextManager:
    """上下文管理器 - 管理用户历史对话"""

    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.redis = None
        # 内存缓存作为备用
        self.memory_cache = defaultdict(list)

    def _get_redis(self):
        """延迟初始化redis连接"""
        if self.redis is None:
            try:
                from app.config import get_settings
                import redis
                settings = get_settings()
                self.redis = redis.from_url(settings.redis_url, decode_responses=True)
            except Exception as e:
                logger.warning(f"Redis not available: {e}")
                self.redis = None
        return self.redis

    async def get_context(self, user_id: str, session_id: str = None) -> dict:
        """
        获取用户上下文
        返回 {'history': [...], 'summary': '...'}
        """
        redis = self._get_redis()
        if session_id is None:
            session_id = f"xianyu_{user_id}"

        context = {"history": [], "summary": ""}

        if redis:
            try:
                conv_key = f"xianyu:chat:conversation:{session_id}"
                history = redis.lrange(conv_key, 0, self.max_history * 2 - 1)

                if history:
                    import json
                    parsed_history = [json.loads(h) for h in history]
                    context["history"] = parsed_history[-self.max_history:]
                    context["summary"] = self._generate_summary(context["history"])
            except Exception as e:
                logger.debug(f"Redis error: {e}")

        # 如果redis没有，使用内存缓存
        if not context["history"]:
            context["history"] = self.memory_cache.get(user_id, [])[-self.max_history:]

        return context

    def _generate_summary(self, history: list) -> str:
        """生成对话摘要"""
        if not history:
            return ""

        # 取最近3轮对话生成摘要
        recent = history[-6:]
        user_msgs = [h.get("content", "") for h in recent if h.get("role") == "user"]
        assistant_msgs = [h.get("content", "") for h in recent if h.get("role") == "assistant"]

        summary_parts = []
        if user_msgs:
            summary_parts.append(f"用户问了: {'; '.join(user_msgs[:2])}")
        if assistant_msgs:
            summary_parts.append(f"AI回复了: {'; '.join(assistant_msgs[:2])}")

        return " | ".join(summary_parts)

    async def add_to_context(self, user_id: str, role: str, content: str, session_id: str = None):
        """添加消息到上下文"""
        if session_id is None:
            session_id = f"xianyu_{user_id}"

        redis = self._get_redis()
        if redis:
            try:
                import json
                conv_key = f"xianyu:chat:conversation:{session_id}"
                redis.lpush(conv_key, json.dumps({"role": role, "content": content}))
                redis.expire(conv_key, 86400)
            except Exception as e:
                logger.debug(f"Redis error: {e}")

        # 同时存内存缓存
        self.memory_cache[user_id].append({"role": role, "content": content})
        if len(self.memory_cache[user_id]) > self.max_history * 2:
            self.memory_cache[user_id] = self.memory_cache[user_id][-self.max_history * 2:]


class ProactiveRecommender:
    """主动推荐器 - 用户长时间不回复时主动推荐产品"""

    # 推荐间隔：每个用户至少相隔多久推荐一次（秒）
    RECOMMEND_INTERVAL = 3600 * 4  # 4小时

    # 活跃阈值：超过多久没回复认为是"沉睡用户"（秒）
    ACTIVE_THRESHOLD = 1800  # 30分钟

    def __init__(self):
        self.last_recommended = {}  # user_id -> last_recommended_time

    def should_recommend(self, user_id: str, last_message_time: float) -> bool:
        """
        判断是否应该向用户推荐
        """
        now = datetime.now().timestamp()

        # 检查是否在冷却期
        if user_id in self.last_recommended:
            if now - self.last_recommended[user_id] < self.RECOMMEND_INTERVAL:
                return False

        # 检查用户是否沉寂（超过活跃阈值没回复）
        if now - last_message_time < self.ACTIVE_THRESHOLD:
            return False

        return True

    def mark_recommended(self, user_id: str):
        """标记已推荐"""
        self.last_recommended[user_id] = datetime.now().timestamp()

    def generate_recommendation(self, context: dict) -> str:
        """
        根据上下文生成推荐话术
        """
        # 基于历史对话生成个性化推荐
        history = context.get("history", [])
        user_msgs = [h.get("content", "") for h in history if h.get("role") == "user"]

        # 根据用户历史询问生成推荐
        if not user_msgs:
            # 新用户或没有历史，发送通用推荐
            return self._general_recommendation()
        else:
            # 根据用户最近询问推断兴趣
            last_topic = user_msgs[-1] if user_msgs else ""
            return self._topic_recommendation(last_topic)

    def _general_recommendation(self) -> str:
        """通用推荐话术"""
        import random
        options = [
            "您好！看到您最近比较活跃，有什么电影想看的吗？我可以帮您查查优惠票哦～",
            "hi~ 最近有几部新片上映，票价比市面便宜不少，需要帮你看看吗？",
            "您好！我是您的专属票务助手，有什么观影需求随时告诉我，我可以帮您代购电影票~",
        ]
        return random.choice(options)

    def _topic_recommendation(self, last_topic: str) -> str:
        """根据话题推荐"""
        if any(k in last_topic for k in ["优惠", "便宜", "折扣"]):
            return "最近有几部新片在做活动，票价很优惠，要我帮你查查吗？"
        elif any(k in last_topic for k in ["电影", "看什么", "推荐"]):
            return "最近《哪吒2》和《唐探1900》都很火，需要帮你查查哪家影院便宜吗？"
        elif any(k in last_topic for k in ["票", "买票", "订票"]):
            return "需要我帮你查查最新的电影票价格吗？各大平台都能帮你比较~"
        else:
            return "有什么观影需求可以告诉我哦，我可以帮您代买电影票，价格优惠～"


class XianyuMessageListener:
    """闲鱼消息监听器 - 增强版"""

    def __init__(
        self,
        poll_interval: int = 30,
        aggregation_window: int = 30,
        proactive_enabled: bool = True,
        use_app_mode: bool = None
    ):
        self.poll_interval = poll_interval
        self.browser = None
        self.app_client = None
        self.customer_service = CustomerService()
        self.running = False

        # 组件初始化
        self.aggregator = MessageAggregator(window_seconds=aggregation_window)
        self.context_manager = ContextManager()
        self.proactive_recommender = ProactiveRecommender()
        self.proactive_enabled = proactive_enabled

        # 追踪用户最后消息时间
        self.user_last_message = {}  # user_id -> last_message_timestamp

        # 模式选择：APP模式 vs 浏览器模式
        if use_app_mode is None:
            self.use_app_mode = settings.use_app_mode
        else:
            self.use_app_mode = use_app_mode

        # 已处理的消息ID集合（用于APP模式去重）
        self.processed_msg_ids = set()

    async def start(self):
        """启动监听服务"""
        mode = "APP" if self.use_app_mode else "Browser"
        logger.info(f"Starting Xianyu message listener in {mode} mode...")
        self.running = True

        if self.use_app_mode:
            # APP模式
            await self._start_app_mode()
        else:
            # 浏览器模式
            await self._start_browser_mode()

        logger.info("Listener started successfully")

        while self.running:
            try:
                await self._check_messages()
                # 主动推荐检查
                if self.proactive_enabled:
                    await self._proactive_recommend()
            except Exception as e:
                logger.error(f"Error in main loop: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _start_browser_mode(self):
        """启动浏览器模式"""
        self.browser = XianyuBrowser()
        await self.browser.init()
        await self.browser.load_cookies()

        if not await self.browser.ensure_logged_in():
            logger.warning("Not logged in, will attempt SMS login...")

            login_success = await self.browser.login(prefer_sms=True)
            if not login_success:
                logger.error("Browser login failed. Please ensure cookies are valid or call /api/customer-service/xianyu/login to trigger login")

    async def _start_app_mode(self):
        """启动APP模式"""
        try:
            from app.services.xianyu_app_client import XianyuAppClient

            self.app_client = XianyuAppClient(
                device_addr=settings.xianyu_device_addr or None
            )
            self.app_client.connect()
            logger.info("APP mode connected successfully")
        except Exception as e:
            logger.error(f"Failed to start APP mode: {e}")
            logger.warning("Falling back to browser mode...")
            self.use_app_mode = False
            await self._start_browser_mode()

    async def _check_messages(self):
        """检查新消息（根据模式分派）"""
        if self.use_app_mode:
            await self._check_messages_app()
        else:
            await self._check_messages_browser()

    async def _check_messages_app(self):
        """APP模式：检查新消息"""
        try:
            if not self.app_client:
                logger.error("APP client not initialized")
                return

            # 确保APP在前台
            self.app_client.keep_alive()

            # 获取会话列表
            conversations = self.app_client.get_conversations()

            for conv in conversations:
                conv_name = conv.get("name")
                if not conv_name:
                    continue

                # 跳过系统项
                skip_items = ["订单", "消息", "发闲置", "APP", "反馈", "客服", "回顶部", "小秘书"]
                if any(s in conv_name for s in skip_items):
                    continue

                # 读取该会话的消息
                messages = self.app_client.read_messages(conv_name)

                for msg in messages:
                    content = msg.get("content", "")
                    if not content or len(content) < 2:
                        continue

                    # 生成消息唯一ID用于去重
                    msg_id = f"{conv_name}:{content}:{msg.get('direction')}"
                    if msg_id in self.processed_msg_ids:
                        continue
                    self.processed_msg_ids.add(msg_id)

                    msg_info = {
                        "user": conv_name,
                        "content": content,
                        "direction": msg.get("direction", "received"),
                        "source": "xianyu_app"
                    }
                    await self._process_message(msg_info)

                # 限制已处理消息集合大小
                if len(self.processed_msg_ids) > 1000:
                    self.processed_msg_ids = set(list(self.processed_msg_ids)[-500:])

        except Exception as e:
            logger.error(f"Failed to check messages (APP mode): {e}")

    async def _check_messages_browser(self):
        """浏览器模式：检查新消息"""
        try:
            if not await self.browser.ensure_logged_in():
                logger.warning("Session issue, will retry...")
                return

            await self.browser.page.goto("https://www.goofish.com/im", timeout=30000)
            await self.browser.page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(3)

            # 查找左侧会话列表中的所有对话项
            conv_items = await self.browser.page.query_selector_all(
                "[class*='item--']"
            )

            logger.debug(f"Found {len(conv_items)} conversation items in sidebar")

            for i, item in enumerate(conv_items):
                try:
                    # 提取会话名称
                    user_name = None
                    for selector in ["[class*='nick']", "[class*='name']"]:
                        try:
                            elem = await item.query_selector(selector)
                            if elem:
                                text = await elem.inner_text()
                                if text and len(text.strip()) > 0 and len(text.strip()) < 20:
                                    user_name = text.strip()
                                    break
                        except:
                            pass

                    if not user_name:
                        continue

                    if user_name in ["订单", "消息", "发闲置", "APP", "反馈", "客服", "回顶部"]:
                        continue

                    logger.debug(f"Clicking conversation: {user_name}")

                    click_result = await self.browser.page.evaluate('''
                        (element) => {
                            element.click();
                            return "clicked";
                        }
                    ''', item)
                    logger.debug(f"JS click result: {click_result}")
                    await asyncio.sleep(2)

                    chat_messages = await self._extract_chat_messages(user_name)

                    if chat_messages:
                        for msg_info in chat_messages:
                            await self._process_message(msg_info)

                    await self.browser.page.goto("https://www.goofish.com/im", timeout=30000)
                    await asyncio.sleep(2)

                except Exception as e:
                    logger.debug(f"Error processing item {i}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to check messages (Browser mode): {e}")

    async def _extract_chat_messages(self, user_name: str) -> list:
        """从右侧聊天区域提取消息内容"""
        messages = []
        try:
            # 查找聊天消息容器
            # 根据调试，消息可能在各种class中
            msg_selectors = [
                "[class*='message']",
                "[class*='msg']",
                "[class*='chat']",
                "[class*='bubble']",
                "[class*='content']",
                ".conversation-view",
                "[class*='conversation-view']",
            ]

            msg_container = None
            for selector in msg_selectors:
                container = await self.browser.page.query_selector(selector)
                if container:
                    msg_container = container
                    logger.debug(f"Found msg container with selector: {selector}")
                    break

            if not msg_container:
                return messages

            # 查找所有消息项
            msg_items = await msg_container.query_selector_all(
                "div, li, [class*='item'], [class*='msg']"
            )

            logger.debug(f"Found {len(msg_items)} message items for {user_name}")

            for item in msg_items:
                try:
                    text = await item.inner_text()
                    if text and len(text.strip()) > 1:
                        # 判断消息方向（发送/接收）
                        # 检查是否有特定的class标识
                        item_class = await item.get_attribute('class') or ""
                        is_sent = "sent" in item_class.lower() or "my" in item_class.lower() or "right" in item_class.lower()

                        messages.append({
                            "user": user_name,
                            "content": text.strip(),
                            "direction": "sent" if is_sent else "received",
                            "source": "xianyu"
                        })
                except:
                    continue

        except Exception as e:
            logger.debug(f"Error extracting chat messages: {e}")

        return messages

    async def _extract_message(self, item) -> dict:
        """提取消息"""
        try:
            # 提取用户名
            name = None
            for selector in ["[class*='nick']", "[class*='name']:not([class*=' Goods'])", "[class*='user-name']"]:
                try:
                    elem = await item.query_selector(selector)
                    if elem:
                        text = await elem.inner_text()
                        if text and len(text) < 20:  # 用户名通常较短
                            name = text.strip()
                            break
                except:
                    pass

            # 提取消息内容
            content = None
            for selector in ["[class*='msg-content']", "[class*='last-msg']", "[class*='msg-text']", "[class*='content']"]:
                try:
                    elem = await item.query_selector(selector)
                    if elem:
                        text = await elem.inner_text()
                        if text and len(text) > 1:
                            content = text.strip()
                            break
                except:
                    pass

            # 提取时间
            time_str = None
            for selector in ["[class*='time']", "[class*='date']", ".time"]:
                try:
                    elem = await item.query_selector(selector)
                    if elem:
                        time_str = await elem.inner_text()
                        break
                except:
                    pass

            if name and content:
                return {
                    "user": name,
                    "content": content,
                    "time": time_str or ""
                }

        except Exception as e:
            logger.debug(f"Extract error: {e}")

        return None

    async def _process_message(self, msg_info: dict):
        """处理单条消息"""
        user = msg_info.get("user", "unknown")
        content = msg_info.get("content", "")

        if not content or len(content) < 2:
            return

        # 更新用户最后消息时间
        self.user_last_message[user] = datetime.now().timestamp()

        # 消息聚合
        should_process, aggregated_content = self.aggregator.add_message(user, content)

        if not should_process:
            return

        logger.info(f"Processing aggregated message from {user}: {aggregated_content[:50]}...")

        try:
            # 获取上下文
            session_id = f"xianyu_{user}"
            context = await self.context_manager.get_context(user, session_id)

            # ========== 订单意图识别（AI增强版）==========
            order_intent = await self.customer_service.identify_intent_ai(aggregated_content)

            if order_intent and order_intent["confidence"] > 0.65:
                # 高置信度下单意图，尝试创建订单
                reply = await self._handle_order_intent(user, aggregated_content, order_intent, context)
            else:
                # 普通对话，调用AI生成回复
                prompt = self._build_contextual_prompt(user, aggregated_content, context)

                reply = await self.customer_service.chat(
                    user_id=user,
                    message=prompt,
                    session_id=session_id
                )

                logger.info(f"AI reply to {user}: {reply[:50]}...")

            # 保存到上下文
            await self.context_manager.add_to_context(user, "user", aggregated_content, session_id)
            await self.context_manager.add_to_context(user, "assistant", reply, session_id)

            # 标记消息已处理
            self.aggregator.mark_processed(user)

            # 发送回复
            await self._send_reply(user, reply)

        except Exception as e:
            logger.error(f"Failed to process message: {e}")

    async def _handle_order_intent(self, user: str, message: str, order_intent: dict, context: dict) -> str:
        """处理下单意图"""
        try:
            # 优先使用AI提取的实体信息
            ai_entities = order_intent.get("entities", {})
            order_entities = self.customer_service.extract_order_entities(message, context)

            # 合并实体，AI提取的优先
            movie_name = ai_entities.get("movie") or order_entities.get("movie")
            quantity = ai_entities.get("quantity") or order_entities.get("quantity", 2)
            city = ai_entities.get("city") or order_entities.get("city", "北京")

            # 获取电影名（尝试从上下文或消息中推断）
            if not movie_name:
                # 尝试从对话历史中推断用户想买的电影
                history = context.get("history", [])
                for msg in reversed(history):
                    if msg.get("role") == "user":
                        content = msg.get("content", "")
                        # 查找提到的电影名
                        movie = self.customer_service.extract_order_entities(content).get("movie")
                        if movie:
                            movie_name = movie
                            break

            if not movie_name:
                # 没有电影名，让用户提供
                return "您好，请问您想购买哪个电影的电影票呢？请告诉我电影名称、观影日期和影院，我来帮您查询最优惠的价格。"

            # 搜索最优惠票价
            from app.modules.ticket.service import TicketService
            ticket_service = TicketService()

            tickets = await ticket_service.search_tickets(
                movie_name=movie_name,
                city=order_entities.get("city", "北京")
            )

            if not tickets:
                return f"抱歉，暂时没有找到《{movie_name}》的电影票信息。请联系人工客服帮您查询。"

            # 选择最低价
            best_ticket = min(tickets, key=lambda t: t.price)

            # 创建订单
            order = await ticket_service.create_proxy_order(
                platform=best_ticket.platform,
                ticket_url=best_ticket.url,
                movie_name=best_ticket.movie,
                show_time=best_ticket.show_time,
                cinema=best_ticket.cinema,
                price=best_ticket.price,
                quantity=order_entities.get("quantity", 2)
            )

            logger.info(f"Created order {order['order_id']} for user {user}")

            # 通知人工客服有新订单
            await self._notify_new_order(order)

            # 构建回复
            reply = f"""您好！已为您创建代购订单 🎫

电影：《{order['movie_name']}》
影院：{order['cinema']}
数量：{order['quantity']}张
票价：{order['original_price']}元
服务费：{order['service_fee']}元
总价：{order['total_price']}元（含服务费）

订单号：{order['order_id']}

人工客服稍后会联系您确认下单，请留意闲鱼消息。"""

            return reply

        except Exception as e:
            logger.error(f"Failed to handle order intent: {e}")
            return "抱歉，系统处理出现问题，请联系人工客服帮您下单。"

    async def _notify_new_order(self, order: dict):
        """通知有新订单（飞书/日志）"""
        try:
            from app.services.lark_service import LarkService
            from app.config import get_settings

            settings = get_settings()
            lark_service = LarkService()

            message = f"""🎫 新订单待处理！

订单号：{order['order_id']}
电影：{order['movie_name']}
影院：{order['cinema']}
数量：{order['quantity']}张
总价：{order['total_price']}元

请及时处理！"""

            await lark_service.send_text_message(
                receive_id=settings.lark_app_id,
                text=message
            )
            logger.info(f"Order notification sent for {order['order_id']}")
        except Exception as e:
            logger.error(f"Failed to send order notification: {e}")
            # 通知失败不影响主流程

    def _build_contextual_prompt(self, user: str, new_message: str, context: dict) -> str:
        """
        构建带上下文的prompt
        """
        history = context.get("history", [])
        summary = context.get("summary", "")

        prompt = new_message

        if history:
            # 构建对话历史
            history_parts = []
            for msg in history[-6:]:  # 最近6条
                role = "用户" if msg.get("role") == "user" else "助手"
                content = msg.get("content", "")
                if content:
                    history_parts.append(f"{role}: {content}")

            if history_parts:
                prompt = f"""[对话背景]
最近对话摘要: {summary}

[对话历史]
{" | ".join(history_parts)}

[当前消息]
用户最新消息: {new_message}

请根据以上上下文，以专业票务客服的身份回复用户。如果用户询问电影票相关问题，可以适当推荐。"""

        return prompt

    async def _send_reply(self, user: str, message: str) -> bool:
        """发送回复"""
        try:
            if self.use_app_mode:
                success = self.app_client.send_message(user, message)
            else:
                success = await self.browser.send_message(user, message)

            if success:
                logger.info(f"Reply sent to {user} via {'APP' if self.use_app_mode else 'Browser'}")
            else:
                logger.warning(f"Failed to send reply to {user}")
            return success
        except Exception as e:
            logger.error(f"Send reply error: {e}")
            return False

    async def _proactive_recommend(self):
        """主动推荐检查"""
        try:
            now = datetime.now().timestamp()

            for user_id, last_time in list(self.user_last_message.items()):
                if self.proactive_recommender.should_recommend(user_id, last_time):
                    logger.info(f"Proactive recommendation for {user_id}")

                    # 获取上下文
                    context = await self.context_manager.get_context(user_id)

                    # 生成推荐话术
                    recommendation = self.proactive_recommender.generate_recommendation(context)

                    # 发送推荐
                    success = await self._send_reply(user_id, recommendation)

                    if success:
                        self.proactive_recommender.mark_recommended(user_id)
                        await self.context_manager.add_to_context(
                            user_id, "assistant", recommendation,
                            session_id=f"xianyu_{user_id}"
                        )

        except Exception as e:
            logger.error(f"Proactive recommendation error: {e}")

    def stop(self):
        """停止服务"""
        logger.info("Stopping listener...")
        self.running = False

        # 关闭浏览器
        if self.browser:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.browser.close())
                else:
                    loop.run_until_complete(self.browser.close())
            except:
                pass

        # APP客户端不需要异步关闭
        self.app_client = None


async def main():
    listener = XianyuMessageListener(
        poll_interval=30,
        aggregation_window=30,
        proactive_enabled=True
    )

    def signal_handler(sig, frame):
        listener.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await listener.start()
    except KeyboardInterrupt:
        listener.stop()


if __name__ == "__main__":
    asyncio.run(main())
