import json
import uuid
import asyncio
import re
import os
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

import redis
from anthropic import Anthropic
from loguru import logger

from app.config import get_settings

settings = get_settings()

# ========== 用户上下文文件管理 ==========
CONTEXT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "user_contexts")
MAX_CONTEXT_FILE_SIZE = 1 * 1024 * 1024  # 1MB
CONTEXT_COMPRESS_THRESHOLD = 0.8  # 80% 触发压缩

COMPRESS_PROMPT = """你是一个对话摘要压缩器。请将以下对话历史压缩为简洁的摘要，保留关键信息：

压缩规则：
1. 保留用户的基本信息（姓名、偏好、历史订单关键信息）
2. 保留最近3轮对话的完整内容
3. 更早的对话只保留关键事实（如：用户询问过什么电影、确定过什么信息）
4. 用简洁的要点形式输出，不要长篇大论
5. 输出格式：

## 用户信息
- 姓名/ID：xxx
- 偏好：xxx
- 历史订单摘要：xxx

## 最近对话
[最近3轮的完整对话]

## 历史关键信息
- [要点1]
- [要点2]
- ...

请压缩以下对话："""


class UserContextManager:
    """管理每个用户的对话上下文文件，支持自动压缩"""

    def __init__(self, anthropic_client: Anthropic = None):
        os.makedirs(CONTEXT_DIR, exist_ok=True)
        self.anthropic = anthropic_client

    def _safe_filename(self, user_id: str) -> str:
        """将 user_id 转为安全文件名"""
        safe = re.sub(r'[^a-zA-Z0-9_\-\u4e00-\u9fff]', '_', user_id)
        return safe[:80] if len(safe) > 80 else safe

    def _get_user_file(self, user_id: str) -> str:
        return os.path.join(CONTEXT_DIR, f"{self._safe_filename(user_id)}.json")

    def _get_file_size(self, user_id: str) -> int:
        path = self._get_user_file(user_id)
        if os.path.exists(path):
            return os.path.getsize(path)
        return 0

    def _should_compress(self, user_id: str) -> bool:
        size = self._get_file_size(user_id)
        return size > MAX_CONTEXT_FILE_SIZE * CONTEXT_COMPRESS_THRESHOLD

    def load_context(self, user_id: str) -> List[Dict]:
        """加载用户对话上下文"""
        path = self._get_user_file(user_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"加载用户上下文失败 [{user_id}]: {e}")
            return []

    def save_context(self, user_id: str, messages: List[Dict]):
        """保存用户对话上下文"""
        path = self._get_user_file(user_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户上下文失败 [{user_id}]: {e}")

    def append_message(self, user_id: str, role: str, content: str, metadata: Dict = None):
        """追加一条消息到用户上下文"""
        messages = self.load_context(user_id)
        entry = {
            "role": role,
            "content": content,
            "timestamp": asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else __import__("time").time(),
        }
        if metadata:
            entry["metadata"] = metadata
        messages.append(entry)

        # 限制单次写入的消息数量（保留最近200条，避免内存问题）
        if len(messages) > 200:
            messages = messages[-200:]

        self.save_context(user_id, messages)

    async def compress_context(self, user_id: str) -> bool:
        """使用 AI 压缩用户上下文"""
        if not self.anthropic:
            logger.warning(f"无法压缩上下文 [{user_id}]: 无 AI 客户端")
            return False

        messages = self.load_context(user_id)
        if len(messages) < 10:
            return False  # 消息太少，不值得压缩

        logger.info(f"压缩用户上下文 [{user_id}]: {len(messages)} 条消息, "
                    f"文件大小 {self._get_file_size(user_id) / 1024:.1f}KB")

        # 构造压缩输入
        raw_text = ""
        for msg in messages:
            role_label = "用户" if msg["role"] == "user" else "助手"
            content = msg.get("content", "")[:500]
            raw_text += f"[{role_label}]: {content}\n"

        try:
            response = self.anthropic.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                system="你是一个专业的对话摘要助手，擅长从对话中提取关键信息并压缩。",
                messages=[{"role": "user", "content": COMPRESS_PROMPT + "\n\n" + raw_text}]
            )

            summary = ""
            for block in response.content:
                if block.type == "text" and block.text:
                    summary = block.text
                    break

            if summary:
                # 保留压缩摘要 + 最近5条消息
                recent = messages[-5:] if len(messages) > 5 else messages
                compressed = [
                    {"role": "system", "content": f"[上下文摘要]\n{summary}", "is_summary": True}
                ]
                compressed.extend(recent)
                self.save_context(user_id, compressed)
                logger.info(f"上下文压缩完成 [{user_id}]: "
                           f"{len(messages)} -> {len(compressed)} 条, "
                           f"新文件大小 {self._get_file_size(user_id) / 1024:.1f}KB")
                return True

        except Exception as e:
            logger.error(f"压缩上下文失败 [{user_id}]: {e}")

        return False

    async def append_and_check(self, user_id: str, role: str, content: str, metadata: Dict = None):
        """追加消息并自动检查是否需要压缩"""
        self.append_message(user_id, role, content, metadata)

        if self._should_compress(user_id):
            await self.compress_context(user_id)

    def get_context_summary(self, user_id: str) -> str:
        """获取用户上下文的可读摘要（用于注入 system prompt）"""
        messages = self.load_context(user_id)
        if not messages:
            return ""

        parts = []
        summary_msg = None

        for msg in messages:
            if msg.get("is_summary"):
                summary_msg = msg.get("content", "")

        if summary_msg:
            parts.append(summary_msg)
            parts.append("\n--- 最近对话 ---")

        # 添加最近10条消息
        recent = [m for m in messages if not m.get("is_summary")][-10:]
        for msg in recent:
            role_label = "用户" if msg["role"] == "user" else "客服"
            parts.append(f"[{role_label}]: {msg.get('content', '')[:200]}")

        return "\n".join(parts)


class MessageSource(Enum):
    XIANYU = "xianyu"
    LARK = "lark"
    SYSTEM = "system"


@dataclass
class ChatMessage:
    source: MessageSource
    user_id: str
    content: str
    session_id: str = ""
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time)
    metadata: Dict = field(default_factory=dict)


class CustomerService:
    SYSTEM_PROMPT = """你是一个专业的闲鱼电影票代购客服助手，名为"票小二"。

## 你的核心能力
1. **电影票咨询**：解答票价、场次、影院等问题
2. **智能下单**：理解用户买票需求，引导完成代购流程
3. **个性推荐**：根据用户偏好推荐热门电影和优惠
4. **订单跟进**：帮助用户查询订单状态

## 对话风格要求
- 亲切友好，像朋友聊天一样自然
- 专业高效，准确回答票务问题
- 适度营销，在对话中自然推荐优惠
- 使用口语化表达，避免过于正式的书面语

## 重要业务规则
1. 代购手续费：5%，最低2元
2. 回复用户前先理解其真实需求（买票？问价？投诉？）
3. 如果用户表现出下单意图，务必确认：电影名、日期、数量、影院
4. 不确定的信息不要瞎猜，可以说"帮您查一下"
5. 遇到复杂问题或情绪化用户，及时转人工

## 上下文理解
- 记住用户之前询问的电影或偏好
- 如果用户说"还是那个"、"继续"等，指代之前讨论的内容
- 结合用户历史对话提供连贯服务

## 回复格式建议
- 简短的确认+信息：不用长篇大论
- 涉及价格时：主动说明是否有优惠
- 下单场景：清晰列出订单信息让用户确认"""

    def __init__(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        self.anthropic = Anthropic(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url
        )
        self.session_prefix = "xianyu:chat:session:"
        self.conversation_prefix = "xianyu:chat:conversation:"
        self.message_queue_key = "xianyu:chat:message_queue"
        self._processing = False
        self.context_manager = UserContextManager(anthropic_client=self.anthropic)

    def _get_conversation_key(self, session_id: str) -> str:
        return f"{self.conversation_prefix}{session_id}"

    async def chat(self, user_id: str, message: str, session_id: Optional[str] = None) -> str:
        """处理用户消息并返回AI回复（含文件持久化上下文）"""
        if not session_id:
            session_id = str(uuid.uuid4())

        conversation_key = self._get_conversation_key(session_id)
        history = self.redis.lrange(conversation_key, 0, -1)
        messages = [json.loads(h) for h in history] if history else []

        # 从文件加载用户历史上下文并注入 system prompt
        context_summary = self.context_manager.get_context_summary(user_id)
        system_prompt = self.SYSTEM_PROMPT
        if context_summary:
            system_prompt = self.SYSTEM_PROMPT + "\n\n## 历史对话上下文\n" + context_summary

        messages.append({"role": "user", "content": message})

        try:
            response = self.anthropic.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                system=system_prompt,
                messages=messages
            )

            # 遍历content blocks找到text类型
            reply = ""
            for block in response.content:
                if block.type == "text" and block.text:
                    reply = block.text
                    break

            self.redis.lpush(conversation_key, json.dumps({"role": "user", "content": message}))
            self.redis.lpush(conversation_key, json.dumps({"role": "assistant", "content": reply}))
            self.redis.expire(conversation_key, 86400)

            self.redis.sadd(f"{self.session_prefix}{user_id}", session_id)

            # 持久化到用户上下文文件（自动检测是否需要压缩）
            await self.context_manager.append_and_check(user_id, "user", message)
            await self.context_manager.append_and_check(user_id, "assistant", reply)

            logger.info(f"Chat response for user {user_id}: {reply[:50]}...")
            return reply

        except Exception as e:
            logger.error(f"AI API error: {e}")
            return "抱歉，AI服务暂时不可用，请稍后再试。"

    async def chat_with_context(
        self,
        user_id: str,
        message: str,
        context: Dict = None,
        session_id: Optional[str] = None
    ) -> str:
        """带上下文的AI客服对话（增强版）"""
        # 如果没有传入context，自动获取用户上下文
        if context is None:
            context = await self.get_context_for_user(user_id, session_id)

        # 构建增强版系统提示
        system_parts = [self.SYSTEM_PROMPT, "\n\n## 当前用户信息"]

        # 用户偏好信息
        prefs = context.get("preferences", {})
        if prefs.get("favorite_movies"):
            movies = "、".join(prefs["favorite_movies"][:5])
            system_parts.append(f"- 常看的电影：{movies}")
        if prefs.get("favorite_cities"):
            system_parts.append(f"- 常在城市：{', '.join(prefs['favorite_cities'])}")
        if prefs.get("preferred_quantity"):
            system_parts.append(f"- 购票数量偏好：{prefs['preferred_quantity']}张")
        if prefs.get("total_orders", 0) > 0:
            system_parts.append(f"- 累计订单数：{prefs['total_orders']}笔")

        # 最近订单
        last_order = prefs.get("last_order")
        if last_order:
            system_parts.append(f"\n## 最近订单")
            system_parts.append(f"- 电影：{last_order.get('movie_name', '未知')}")
            system_parts.append(f"- 影院：{last_order.get('cinema', '未知')}")
            system_parts.append(f"- 数量：{last_order.get('quantity', 2)}张")

        # 对话历史摘要
        recent_history = context.get("recent_history", [])
        if recent_history:
            system_parts.append(f"\n## 最近对话")
            for msg in recent_history[-4:]:  # 最近2轮对话
                role = "用户" if msg.get("role") == "user" else "助手"
                content = msg.get("content", "")[:100]
                if content:
                    system_parts.append(f"- {role}：{content}")

        system_with_context = "\n".join(system_parts)

        if not session_id:
            session_id = str(uuid.uuid4())

        conversation_key = self._get_conversation_key(session_id)
        history = self.redis.lrange(conversation_key, 0, -1)
        messages = [json.loads(h) for h in history] if history else []

        messages.append({"role": "user", "content": message})

        try:
            response = self.anthropic.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                system=system_with_context,
                messages=messages
            )

            # 遍历content blocks找到text类型
            reply = ""
            for block in response.content:
                if block.type == "text" and block.text:
                    reply = block.text
                    break

            self.redis.lpush(conversation_key, json.dumps({"role": "user", "content": message}))
            self.redis.lpush(conversation_key, json.dumps({"role": "assistant", "content": reply}))
            self.redis.expire(conversation_key, 86400)

            return reply

        except Exception as e:
            logger.error(f"AI API error: {e}")
            return "抱歉，AI服务暂时不可用，请稍后再试。"

    async def queue_message(self, msg: ChatMessage) -> str:
        """将消息加入处理队列"""
        msg.session_id = msg.session_id or str(uuid.uuid4())
        msg_str = json.dumps({
            "source": msg.source.value,
            "user_id": msg.user_id,
            "content": msg.content,
            "session_id": msg.session_id,
            "timestamp": msg.timestamp,
            "metadata": msg.metadata
        })
        self.redis.lpush(self.message_queue_key, msg_str)
        logger.info(f"Message queued for user {msg.user_id}")
        return msg.session_id

    async def process_message_queue(self) -> int:
        """处理消息队列（后台运行）"""
        if self._processing:
            return 0

        self._processing = True
        processed = 0

        try:
            from app.services.lark_service import LarkService

            lark_service = LarkService()

            while True:
                msg_json = self.redis.rpop(self.message_queue_key)
                if not msg_json:
                    break

                msg_dict = json.loads(msg_json)
                msg = ChatMessage(
                    source=MessageSource(msg_dict["source"]),
                    user_id=msg_dict["user_id"],
                    content=msg_dict["content"],
                    session_id=msg_dict.get("session_id", ""),
                    timestamp=msg_dict.get("timestamp", 0),
                    metadata=msg_dict.get("metadata", {})
                )

                reply = await self.chat(msg.user_id, msg.content, msg.session_id)

                # 如果是闲鱼消息，同步到飞书通知
                if msg.source == MessageSource.XIANYU:
                    try:
                        await lark_service.send_text_message(
                            receive_id=settings.lark_app_id,
                            text=f"客户：{msg.user_id}发来消息\n内容：{msg.content}\n\nAI回复：{reply}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send Lark notification: {e}")

                processed += 1

        finally:
            self._processing = False

        logger.info(f"Processed {processed} messages from queue")
        return processed

    async def get_user_sessions(self, user_id: str) -> list:
        """获取用户的所有会话ID"""
        sessions = self.redis.smembers(f"{self.session_prefix}{user_id}")
        return list(sessions)

    async def get_conversation_history(self, session_id: str, limit: int = 20) -> List[Dict]:
        """获取会话历史"""
        conversation_key = self._get_conversation_key(session_id)
        history = self.redis.lrange(conversation_key, 0, limit - 1)
        return [json.loads(h) for h in reversed(history)]

    async def clear_user_sessions(self, user_id: str):
        """清除用户的所有会话"""
        sessions = self.redis.smembers(f"{self.session_prefix}{user_id}")
        for session_id in sessions:
            self.redis.delete(f"{self.conversation_prefix}{session_id}")
        self.redis.delete(f"{self.session_prefix}{user_id}")

    async def get_pending_messages_count(self) -> int:
        """获取待处理消息数量"""
        return self.redis.llen(self.message_queue_key)

    # ============== 用户偏好管理 ==============

    USER_PREFERENCES_KEY = "xianyu:chat:preferences:"

    async def get_user_preferences(self, user_id: str) -> Dict:
        """
        获取用户偏好设置
        包含：常看电影、常去城市、偏好影院、上次订单等
        """
        key = f"{self.USER_PREFERENCES_KEY}{user_id}"
        data = self.redis.get(key)
        if data:
            return json.loads(data)
        return {
            "favorite_movies": [],
            "favorite_cities": [],
            "favorite_cinemas": [],
            "last_order": None,
            "total_orders": 0,
            "preferred_quantity": 2,
        }

    async def update_user_preferences(self, user_id: str, preferences: Dict):
        """更新用户偏好设置"""
        key = f"{self.USER_PREFERENCES_KEY}{user_id}"
        # 合并现有偏好和新偏好
        existing = await self.get_user_preferences(user_id)
        existing.update(preferences)
        self.redis.set(key, json.dumps(existing), ex=86400 * 30)  # 30天过期

    async def record_user_order(self, user_id: str, order_info: Dict):
        """记录用户的订单，用于偏好学习"""
        prefs = await self.get_user_preferences(user_id)
        # 更新最后订单
        prefs["last_order"] = order_info
        prefs["total_orders"] = prefs.get("total_orders", 0) + 1
        # 如果是新电影，加入收藏
        movie = order_info.get("movie_name")
        if movie and movie not in prefs["favorite_movies"]:
            prefs["favorite_movies"].insert(0, movie)
            if len(prefs["favorite_movies"]) > 10:
                prefs["favorite_movies"] = prefs["favorite_movies"][:10]
        # 更新常购数量
        prefs["preferred_quantity"] = order_info.get("quantity", 2)
        await self.update_user_preferences(user_id, prefs)

    async def get_context_for_user(self, user_id: str, session_id: str = None) -> Dict:
        """
        构建发送给AI的完整上下文
        包含：用户偏好、历史对话摘要、最后订单
        """
        prefs = await self.get_user_preferences(user_id)
        history = []
        if session_id:
            history = await self.get_conversation_history(session_id, limit=6)

        context = {
            "user_id": user_id,
            "preferences": prefs,
            "recent_history": history[-6:] if history else [],
        }
        return context

    # ============== AI意图识别 ==============

    INTENT_PROMPT = """分析用户消息的意图，只返回JSON格式的纯文本，不要有其他内容。

用户消息：{message}

可能的意图类型：
- buy_ticket：想买电影票（包含电影名、数量、日期等）
- inquiry：只是咨询价格或信息
- complaint：投诉或售后问题
- casual：闲聊或问候
- other：其他

同时提取关键信息（如果能提取的话）：
- movie: 用户想看的电影名
- quantity: 购票数量（数字）
- city: 城市
- time: 观影时间描述

请返回如下格式的JSON（不要有其他文字）：
{{"intent": "意图类型", "confidence": 0.0-1.0, "entities": {{"movie": "...", "quantity": 数字, "city": "...", "time": "..."}}}}"""

    async def identify_intent_ai(self, message: str) -> Optional[Dict]:
        """
        使用AI识别用户意图（增强版）
        返回意图类型、置信度和提取的实体信息
        """
        try:
            response = self.anthropic.messages.create(
                model=settings.anthropic_model,
                max_tokens=256,
                system="你是一个意图识别助手，专门分析用户消息的买票意图。",
                messages=[{"role": "user", "content": self.INTENT_PROMPT.format(message=message)}]
            )

            # 解析AI返回的JSON
            reply = ""
            for block in response.content:
                if block.type == "text" and block.text:
                    reply = block.text.strip()
                    break

            import re
            # 提取JSON
            json_match = re.search(r'\{.*\}', reply, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                # 确保返回格式正确
                return {
                    "intent": result.get("intent", "other"),
                    "confidence": result.get("confidence", 0.5),
                    "entities": result.get("entities", {})
                }

        except Exception as e:
            logger.error(f"AI intent recognition error: {e}")

        return {"intent": "other", "confidence": 0.0, "entities": {}}

    def identify_order_intent(self, message: str) -> Optional[Dict]:
        """
        识别用户消息中的下单意图
        返回: {"intent": "buy_ticket", "confidence": 0.85, "entities": {...}} 或 None
        """
        import re

        # 下单关键词
        buy_keywords = ["买", "订", "要", "下单", "购买", "来一张", "来两张", "帮买", "帮我买", "代买"]
        # 排除词（这些情况下不算下单）
        exclude_keywords = ["不买", "不订", "不要", "退", "退款", "取消"]

        # 检查是否包含下单关键词
        has_buy_keyword = any(k in message for k in buy_keywords)
        has_exclude_keyword = any(k in message for k in exclude_keywords)

        if has_exclude_keyword:
            return None

        if not has_buy_keyword:
            return None

        # 提取数量
        quantity = 2  # 默认2张
        quantity_patterns = [
            r'(\d+)张',
            r'来?(\d+)张',
            r'买(\d+)张',
            r'(\d+)个人?',
        ]
        for pattern in quantity_patterns:
            match = re.search(pattern, message)
            if match:
                quantity = int(match.group(1))
                break

        # 计算置信度
        confidence = 0.6
        if any(k in message for k in ["下单", "购买", "代买"]):
            confidence = 0.85
        elif any(k in message for k in ["帮买", "帮我买", "要", "订"]):
            confidence = 0.75
        elif "买" in message:
            confidence = 0.7

        # 如果提到电影相关词汇，提高置信度
        movie_keywords = ["电影票", "票", "影院", "电影院", "场次", "座位"]
        if any(k in message for k in movie_keywords):
            confidence = min(confidence + 0.1, 0.95)

        return {
            "intent": "buy_ticket",
            "confidence": confidence,
            "entities": {
                "quantity": quantity
            }
        }

    def extract_order_entities(self, message: str, context: Dict = None) -> Dict:
        """
        从用户消息中提取订单相关信息
        返回: {"movie": "...", "time": "...", "cinema": "...", "quantity": 2, "city": "北京"}
        """
        import re
        from datetime import datetime, timedelta

        entities = {
            "quantity": 2,
            "city": "北京",
            "movie": None,
            "time": None,
            "cinema": None
        }

        # 提取数量
        quantity_patterns = [
            r'(\d+)张',
            r'来?(\d+)张',
            r'买(\d+)张',
            r'(\d+)个人?',
        ]
        for pattern in quantity_patterns:
            match = re.search(pattern, message)
            if match:
                entities["quantity"] = int(match.group(1))
                break

        # 提取电影名（需要结合上下文或AI，这里用简单模式）
        # 常见电影名模式：X票、买X、订X
        movie_patterns = [
            r'(哪吒[之2]?)',
            r'(唐探1900)',
            r'(热辣滚烫)',
            r'(飞驰人生2?)',
            r'(熊出没.*?)',
            r'(长津湖.*?)',
            r'(流浪地球.*?)',
            r'(.*)电影票',
            r'买([^\s\d]+?)(?:张|张票)?',
            r'订([^\s\d]+?)(?:张|张票)?',
            r'来(\d+)张(.+?)(?:的?票?)?',
        ]

        # 这些词出现说明捕获的不是电影名
        invalid_movie_keywords = ['订', '买', '要', '下单', '帮', '我', '张']

        for pattern in movie_patterns:
            match = re.search(pattern, message)
            if match:
                potential_movie = match.group(1) if match.lastindex == 1 else match.group(2) if match.lastindex == 2 else match.group(1)
                # 排除明显不是电影名的词
                if potential_movie and len(potential_movie) >= 2:
                    # 如果包含这些词，说明不是电影名
                    if any(k in potential_movie for k in invalid_movie_keywords):
                        continue
                    if potential_movie.isdigit():
                        continue
                    entities["movie"] = potential_movie.strip()
                    break

        # 提取时间（如"今天"、"明天"、"下午3点"等）
        time_patterns = [
            (r'今天', datetime.now()),
            (r'明天', datetime.now() + timedelta(days=1)),
            (r'后天', datetime.now() + timedelta(days=2)),
            (r'大后天', datetime.now() + timedelta(days=3)),
        ]
        for pattern, default_time in time_patterns:
            if pattern in message:
                entities["time"] = default_time.strftime("%Y-%m-%d")
                break

        # 提取城市
        city_patterns = [
            r'北京|上海|广州|深圳|杭州|成都|武汉|南京|西安|重庆',
        ]
        for pattern in city_patterns:
            match = re.search(pattern, message)
            if match:
                entities["city"] = match.group(0)
                break

        # 如果有上下文，使用上下文中的电影名
        if context and not entities["movie"]:
            if "recent_orders" in context:
                # 从历史订单中获取最近的电影
                pass
            if "preferences" in context:
                # 从偏好设置中获取
                pass

        return entities
