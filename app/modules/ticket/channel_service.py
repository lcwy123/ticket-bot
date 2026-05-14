"""
渠道成本管理服务
管理各影院/影片的渠道成本价
"""
import json
from typing import List, Optional, Dict
from datetime import datetime
from loguru import logger

from app.modules.ticket.models import ChannelCost


class ChannelCostService:
    """渠道成本管理服务

    使用Redis存储渠道成本数据
    """

    CACHE_KEY_CINEMA = "ticket:channel:cinema:{city}:{cinema_name}"
    CACHE_KEY_MOVIE = "ticket:channel:movie:{city}:{cinema_name}:{movie_name}"
    CACHE_KEY_ALL = "ticket:channel:all"

    def __init__(self):
        self._redis = None
        self._init_sample_data = False

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
        """获取内存存储（Redis不可用时备用）"""
        if not hasattr(self, "_memory_store"):
            self._memory_store = {}
        return self._memory_store

    def _generate_id(self) -> int:
        """生成ID"""
        if not hasattr(self, "_id_counter"):
            self._id_counter = 1
        current = self._id_counter
        self._id_counter += 1
        return current

    def _init_sample_data_if_needed(self):
        """初始化示例数据"""
        if self._init_sample_data:
            return

        self._init_sample_data = True

        # 添加一些示例渠道成本
        samples = [
            ChannelCost(
                id=self._generate_id(),
                cinema_name="万达影城(北京朝阳店)",
                movie_name="",
                city="北京",
                cost_price=28.0,
                remark="普通厅成本"
            ),
            ChannelCost(
                id=self._generate_id(),
                cinema_name="万达影城(北京朝阳店)",
                movie_name="",
                city="北京",
                cost_price=38.0,
                remark="IMAX厅成本"
            ),
            ChannelCost(
                id=self._generate_id(),
                cinema_name="CGV影城(北京颐堤港)",
                movie_name="",
                city="北京",
                cost_price=25.0,
                remark="普通厅成本"
            ),
            ChannelCost(
                id=self._generate_id(),
                cinema_name="金逸影城(北京朝阳店)",
                movie_name="",
                city="北京",
                cost_price=22.0,
                remark="普通厅成本"
            ),
            ChannelCost(
                id=self._generate_id(),
                cinema_name="大地影院",
                movie_name="",
                city="北京",
                cost_price=20.0,
                remark="普通厅成本"
            ),
        ]

        store = self._get_memory_store()
        for cost in samples:
            store[cost.id] = cost

    def add_channel_cost(
        self,
        cinema_name: str,
        city: str,
        cost_price: float,
        movie_name: str = "",
        remark: str = ""
    ) -> ChannelCost:
        """添加渠道成本"""
        self._init_sample_data_if_needed()

        redis = self._get_redis()
        cost = ChannelCost(
            id=self._generate_id(),
            cinema_name=cinema_name,
            movie_name=movie_name,
            city=city,
            cost_price=cost_price,
            remark=remark,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        if redis:
            try:
                key = self.CACHE_KEY_MOVIE.format(
                    city=city,
                    cinema_name=cinema_name,
                    movie_name=movie_name or "_all_"
                )
                redis.set(key, json.dumps({
                    "id": cost.id,
                    "cinema_name": cost.cinema_name,
                    "movie_name": cost.movie_name,
                    "city": cost.city,
                    "cost_price": cost.cost_price,
                    "remark": cost.remark,
                    "created_at": cost.created_at.isoformat(),
                    "updated_at": cost.updated_at.isoformat()
                }))
                logger.info(f"已保存渠道成本到Redis: {key}")
            except Exception as e:
                logger.error(f"Redis保存失败: {e}")
        else:
            store = self._get_memory_store()
            store[cost.id] = cost

        return cost

    def get_channel_cost(
        self,
        cinema_name: str,
        movie_name: str = "",
        city: str = "北京"
    ) -> Optional[ChannelCost]:
        """获取渠道成本

        优先匹配：影片+影院 > 影院通用
        """
        self._init_sample_data_if_needed()

        redis = self._get_redis()

        # 优先查找影片专属价格
        if movie_name:
            if redis:
                try:
                    key = self.CACHE_KEY_MOVIE.format(
                        city=city,
                        cinema_name=cinema_name,
                        movie_name=movie_name
                    )
                    data = redis.get(key)
                    if data:
                        obj = json.loads(data)
                        return ChannelCost(
                            id=obj["id"],
                            cinema_name=obj["cinema_name"],
                            movie_name=obj.get("movie_name", ""),
                            city=obj["city"],
                            cost_price=float(obj["cost_price"]),
                            remark=obj.get("remark", ""),
                            created_at=datetime.fromisoformat(obj["created_at"]),
                            updated_at=datetime.fromisoformat(obj["updated_at"])
                        )
                except Exception as e:
                    logger.debug(f"Redis读取失败: {e}")
            else:
                store = self._get_memory_store()
                for cost in store.values():
                    if (cost.cinema_name == cinema_name and
                        cost.movie_name == movie_name and
                        cost.city == city):
                        return cost

        # 查找影院通用价格
        if redis:
            try:
                key = self.CACHE_KEY_CINEMA.format(
                    city=city,
                    cinema_name=cinema_name
                )
                data = redis.get(key)
                if data:
                    obj = json.loads(data)
                    return ChannelCost(
                        id=obj["id"],
                        cinema_name=obj["cinema_name"],
                        movie_name="",
                        city=obj["city"],
                        cost_price=float(obj["cost_price"]),
                        remark=obj.get("remark", ""),
                        created_at=datetime.fromisoformat(obj["created_at"]),
                        updated_at=datetime.fromisoformat(obj["updated_at"])
                    )
            except Exception as e:
                logger.debug(f"Redis读取失败: {e}")
        else:
            store = self._get_memory_store()
            best_match = None
            for cost in store.values():
                if cost.cinema_name == cinema_name and cost.city == city:
                    if not movie_name or cost.movie_name == "":
                        best_match = cost
            return best_match

        return None

    def list_channel_costs(self, city: str = None) -> List[ChannelCost]:
        """列出所有渠道成本"""
        self._init_sample_data_if_needed()

        redis = self._get_redis()

        if redis:
            try:
                keys = redis.keys("ticket:channel:*")
                costs = []
                for key in keys:
                    data = redis.get(key)
                    if data:
                        obj = json.loads(data)
                        if city is None or obj.get("city") == city:
                            costs.append(ChannelCost(
                                id=obj["id"],
                                cinema_name=obj["cinema_name"],
                                movie_name=obj.get("movie_name", ""),
                                city=obj["city"],
                                cost_price=float(obj["cost_price"]),
                                remark=obj.get("remark", ""),
                                created_at=datetime.fromisoformat(obj["created_at"]),
                                updated_at=datetime.fromisoformat(obj["updated_at"])
                            ))
                return costs
            except Exception as e:
                logger.error(f"Redis列表读取失败: {e}")

        # 内存存储
        store = self._get_memory_store()
        costs = list(store.values())
        if city:
            costs = [c for c in costs if c.city == city]
        return costs

    def delete_channel_cost(self, cost_id: int) -> bool:
        """删除渠道成本"""
        redis = self._get_redis()

        if redis:
            try:
                # Redis的删除逻辑比较复杂，需要遍历
                keys = redis.keys("ticket:channel:*")
                for key in keys:
                    data = redis.get(key)
                    if data:
                        obj = json.loads(data)
                        if obj.get("id") == cost_id:
                            redis.delete(key)
                            return True
            except Exception as e:
                logger.error(f"Redis删除失败: {e}")

        # 内存存储
        store = self._get_memory_store()
        if cost_id in store:
            del store[cost_id]
            return True

        return False


# 全局实例
channel_cost_service = ChannelCostService()
