"""
票务订单服务
管理订单全生命周期
"""
import uuid
import json
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from dataclasses import asdict
from loguru import logger

from app.modules.ticket.models import TicketOrder, OrderStatus, QuotePrice
from app.modules.ticket.pricing_engine import pricing_engine


class OrderService:
    """票务订单服务

    使用Redis存储订单数据
    """

    ORDER_KEY = "ticket:order:{order_id}"
    ORDER_LIST_KEY = "ticket:orders:list"
    ORDER_USER_KEY = "ticket:order:user:{user_id}"

    def __init__(self):
        self._redis = None

    def _get_redis(self):
        """延迟初始化Redis"""
        if self._redis is None:
            try:
                import redis
                from app.config import get_settings
                settings = get_settings()
                self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            except Exception as e:
                logger.warning(f"Redis不可用，使用内存存储: {e}")
                self._redis = None
        return self._redis

    def _get_memory_store(self) -> Dict:
        """获取内存存储"""
        if not hasattr(self, "_memory_store"):
            self._memory_store = {}
        return self._memory_store

    def _generate_order_id(self) -> str:
        """生成订单号"""
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        uid = str(uuid.uuid4())[:6].upper()
        return f"TK{ts}{uid}"

    def create_order(
        self,
        user_id: str,
        user_nickname: str = "",
        movie_name: str = "",
        cinema_name: str = "",
        city: str = "",
        show_date: str = "",
        show_time: str = "",
        official_price: float = 0,
        quoted_price: float = 0,
        actual_cost: float = 0,
        buyer_message: str = "",
        **kwargs
    ) -> TicketOrder:
        """创建新订单"""
        redis = self._get_redis()

        order = TicketOrder(
            order_id=self._generate_order_id(),
            user_id=user_id,
            user_nickname=user_nickname,
            movie_name=movie_name,
            cinema_name=cinema_name,
            city=city,
            show_date=show_date,
            show_time=show_time,
            official_price=official_price,
            quoted_price=quoted_price,
            actual_cost=actual_cost,
            profit=quoted_price - actual_cost,
            status=OrderStatus.PENDING,
            buyer_message=buyer_message,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            raw_data=kwargs
        )

        if redis:
            try:
                key = self.ORDER_KEY.format(order_id=order.order_id)
                self._redis.set(key, json.dumps(asdict(order), default=str))
                self._redis.zadd(self.ORDER_LIST_KEY, {order.order_id: datetime.now().timestamp()})
                self._redis.sadd(self.ORDER_USER_KEY.format(user_id=user_id), order.order_id)
                logger.info(f"订单已保存到Redis: {order.order_id}")
            except Exception as e:
                logger.error(f"Redis保存订单失败: {e}")
        else:
            store = self._get_memory_store()
            store[order.order_id] = order

        logger.info(f"创建订单: {order.order_id} - {movie_name}@{cinema_name}")
        return order

    def get_order(self, order_id: str) -> Optional[TicketOrder]:
        """获取订单"""
        redis = self._get_redis()

        if redis:
            try:
                key = self.ORDER_KEY.format(order_id=order_id)
                data = self._redis.get(key)
                if data:
                    obj = json.loads(data)
                    return self._deserialize_order(obj)
            except Exception as e:
                logger.error(f"Redis获取订单失败: {e}")
        else:
            store = self._get_memory_store()
            return store.get(order_id)

        return None

    def update_order(self, order: TicketOrder) -> TicketOrder:
        """更新订单"""
        order.updated_at = datetime.now()

        redis = self._get_redis()

        if redis:
            try:
                key = self.ORDER_KEY.format(order_id=order.order_id)
                self._redis.set(key, json.dumps(asdict(order), default=str))
            except Exception as e:
                logger.error(f"Redis更新订单失败: {e}")
        else:
            store = self._get_memory_store()
            store[order.order_id] = order

        logger.info(f"更新订单: {order.order_id} - status={order.status.value}")
        return order

    def list_orders(
        self,
        status: OrderStatus = None,
        user_id: str = None,
        limit: int = 50
    ) -> List[TicketOrder]:
        """列出订单"""
        redis = self._get_redis()

        orders = []

        if redis:
            try:
                # 获取所有订单ID
                order_ids = self._redis.zrevrange(self.ORDER_LIST_KEY, 0, limit - 1)
                for oid in order_ids:
                    order = self.get_order(oid)
                    if order:
                        if status and order.status != status:
                            continue
                        if user_id and order.user_id != user_id:
                            continue
                        orders.append(order)
            except Exception as e:
                logger.error(f"Redis列出订单失败: {e}")
        else:
            store = self._get_memory_store()
            orders = list(store.values())
            if status:
                orders = [o for o in orders if o.status == status]
            if user_id:
                orders = [o for o in orders if o.user_id == user_id]
            orders.sort(key=lambda x: x.created_at, reverse=True)
            orders = orders[:limit]

        return orders

    def update_order_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        **kwargs
    ) -> Optional[TicketOrder]:
        """更新订单状态"""
        order = self.get_order(order_id)
        if not order:
            return None

        order.status = new_status
        order.updated_at = datetime.now()

        # 更新各状态时间
        if new_status == OrderStatus.PAID:
            order.paid_at = datetime.now()
        elif new_status == OrderStatus.BOOKED:
            order.booked_at = datetime.now()
        elif new_status == OrderStatus.COMPLETED:
            order.completed_at = datetime.now()

        # 其他字段更新
        for key, value in kwargs.items():
            if hasattr(order, key):
                setattr(order, key, value)

        return self.update_order(order)

    def set_ticket_code(
        self,
        order_id: str,
        ticket_code: str,
        ticket_status: str = "已出票"
    ) -> Optional[TicketOrder]:
        """录入取票码"""
        return self.update_order_status(
            order_id,
            OrderStatus.BOOKED,
            ticket_code=ticket_code,
            ticket_status=ticket_status
        )

    def _deserialize_order(self, obj: dict) -> TicketOrder:
        """反序列化订单"""
        obj.pop("_id", None)

        # 转换status
        if isinstance(obj.get("status"), str):
            try:
                obj["status"] = OrderStatus(obj["status"])
            except ValueError:
                obj["status"] = OrderStatus.PENDING

        # 转换datetime
        for field in ["created_at", "updated_at", "paid_at", "booked_at", "completed_at"]:
            if isinstance(obj.get(field), str):
                try:
                    obj[field] = datetime.fromisoformat(obj[field])
                except (ValueError, TypeError):
                    obj[field] = None

        return TicketOrder(**obj)

    def get_statistics(self, days: int = 30) -> dict:
        """获取统计数据"""
        redis = self._get_redis()

        orders = self.list_orders(limit=1000)
        start_date = datetime.now() - timedelta(days=days)

        # 过滤时间范围
        orders = [o for o in orders if o.created_at >= start_date]

        total_orders = len(orders)
        completed_orders = [o for o in orders if o.status == OrderStatus.COMPLETED]
        paid_orders = [o for o in orders if o.status in [OrderStatus.PAID, OrderStatus.BOOKED, OrderStatus.COMPLETED]]

        total_revenue = sum(o.quoted_price for o in paid_orders)
        total_cost = sum(o.actual_cost for o in paid_orders)
        total_profit = sum(o.profit for o in paid_orders)

        return {
            "period_days": days,
            "total_orders": total_orders,
            "completed_orders": len(completed_orders),
            "pending_orders": len([o for o in orders if o.status == OrderStatus.PENDING]),
            "quoted_orders": len([o for o in orders if o.status == OrderStatus.QUOTED]),
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "avg_profit_per_order": round(total_profit / len(completed_orders), 2) if completed_orders else 0,
            "top_movies": self._get_top_movies(orders, 5),
            "top_cinemas": self._get_top_cinemas(orders, 5),
        }

    def _get_top_movies(self, orders: List[TicketOrder], limit: int) -> List[dict]:
        """获取热门电影"""
        movie_stats = {}
        for o in orders:
            if o.movie_name:
                if o.movie_name not in movie_stats:
                    movie_stats[o.movie_name] = {"count": 0, "profit": 0}
                movie_stats[o.movie_name]["count"] += 1
                movie_stats[o.movie_name]["profit"] += o.profit

        sorted_movies = sorted(movie_stats.items(), key=lambda x: x[1]["count"], reverse=True)
        return [{"movie": m, "count": s["count"], "profit": round(s["profit"], 2)} for m, s in sorted_movies[:limit]]

    def _get_top_cinemas(self, orders: List[TicketOrder], limit: int) -> List[dict]:
        """获取热门影院"""
        cinema_stats = {}
        for o in orders:
            if o.cinema_name:
                if o.cinema_name not in cinema_stats:
                    cinema_stats[o.cinema_name] = {"count": 0, "profit": 0}
                cinema_stats[o.cinema_name]["count"] += 1
                cinema_stats[o.cinema_name]["profit"] += o.profit

        sorted_cinemas = sorted(cinema_stats.items(), key=lambda x: x[1]["count"], reverse=True)
        return [{"cinema": c, "count": s["count"], "profit": round(s["profit"], 2)} for c, s in sorted_cinemas[:limit]]


# 全局实例
order_service = OrderService()
