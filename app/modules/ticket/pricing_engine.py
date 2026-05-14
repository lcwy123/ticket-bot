"""
智能报价引擎
方案C: 就低不就高 = min(市价×0.8, 渠道成本×1.5)
"""
from typing import Optional
from dataclasses import dataclass
from loguru import logger

from app.modules.ticket.models import QuotePrice, PricingConfig, OfficialTicket
from app.modules.ticket.channel_service import channel_cost_service


class PricingEngine:
    """智能报价引擎

    报价策略（方案C）:
    报价 = min(市价×0.8, 渠道成本×1.5)

    同时确保:
    - 最低利润 ≥ min_profit (默认5元)
    - 最低利润率 ≥ min_margin (默认10%)
    """

    def __init__(self, config: PricingConfig = None):
        self.config = config or PricingConfig()

    def quote(
        self,
        official_price: float,
        channel_cost: float = 0,
        cinema_name: str = "",
        movie_name: str = "",
        city: str = "北京"
    ) -> QuotePrice:
        """
        计算报价

        Args:
            official_price: 官方/市价
            channel_cost: 渠道成本（如果为0，会尝试自动查找）
            cinema_name: 影院名称
            movie_name: 影片名称
            city: 城市

        Returns:
            QuotePrice对象
        """
        # 如果没有传入渠道成本，尝试自动查找
        if channel_cost == 0 and cinema_name:
            cost_obj = channel_cost_service.get_channel_cost(
                cinema_name=cinema_name,
                movie_name=movie_name,
                city=city
            )
            if cost_obj:
                channel_cost = cost_obj.cost_price
                logger.debug(f"自动找到渠道成本: {channel_cost}")

        # 方案C计算
        maidan_price = official_price * self.config.maidan_ratio
        cost_markup_price = channel_cost * self.config.cost_ratio if channel_cost > 0 else 0

        if cost_markup_price > 0:
            quoted_price = min(maidan_price, cost_markup_price)
        else:
            # 没有渠道成本时，只能用市价折扣
            quoted_price = maidan_price

        # 应用保底价
        if self.config.use_floor_price and quoted_price < self.config.floor_price:
            quoted_price = self.config.floor_price

        # 确保最低利润
        if channel_cost > 0:
            min_price = channel_cost + self.config.min_profit
            if quoted_price < min_price:
                quoted_price = min_price

        # 计算利润
        profit = quoted_price - channel_cost if channel_cost > 0 else 0
        profit_margin = (profit / quoted_price * 100) if quoted_price > 0 else 0

        # 如果有渠道成本，确保利润率达标
        if channel_cost > 0 and profit_margin < self.config.min_margin * 100:
            # 提价到满足最低利润率
            min_profit_price = channel_cost / (1 - self.config.min_margin)
            quoted_price = max(quoted_price, min_profit_price)
            profit = quoted_price - channel_cost
            profit_margin = (profit / quoted_price * 100) if quoted_price > 0 else 0

        return QuotePrice(
            official_price=official_price,
            channel_cost=channel_cost,
            quoted_price=round(quoted_price, 2),
            profit=round(profit, 2),
            profit_margin=round(profit_margin, 1),
            pricing_strategy="C: min(市价×0.8, 成本×1.5)"
        )

    def quote_from_ticket(
        self,
        ticket: OfficialTicket,
        channel_cost: float = 0
    ) -> QuotePrice:
        """从OfficialTicket对象报价"""
        return self.quote(
            official_price=ticket.official_price,
            channel_cost=channel_cost or ticket.channel_price,
            cinema_name=ticket.cinema_name,
            movie_name=ticket.movie_name,
            city=ticket.city
        )

    def batch_quote(
        self,
        tickets: list,
        channel_costs: dict = None
    ) -> list:
        """
        批量报价

        Args:
            tickets: OfficialTicket列表
            channel_costs: {cinema_name: cost} 字典

        Returns:
            [(ticket, quote), ...] 列表
        """
        results = []
        for ticket in tickets:
            cost = (channel_costs or {}).get(ticket.cinema_name, 0)
            quote = self.quote_from_ticket(ticket, cost)
            results.append((ticket, quote))

        return results

    def get_profit_analysis(
        self,
        official_price: float,
        quoted_price: float,
        channel_cost: float
    ) -> dict:
        """
        获取利润分析

        Returns:
            利润分析字典
        """
        profit = quoted_price - channel_cost
        profit_margin = (profit / quoted_price * 100) if quoted_price > 0 else 0
        discount = (1 - quoted_price / official_price) * 100 if official_price > 0 else 0

        return {
            "official_price": official_price,
            "quoted_price": quoted_price,
            "channel_cost": channel_cost,
            "profit": round(profit, 2),
            "profit_margin": round(profit_margin, 1),
            "buyer_discount": round(discount, 1),  # 给买家的折扣
            "roi": round((profit / channel_cost * 100), 1) if channel_cost > 0 else 0,  # 投资回报率
        }


# 全局实例
pricing_engine = PricingEngine()


# 便捷函数
def quote_price(
    official_price: float,
    channel_cost: float = 0,
    cinema_name: str = "",
    movie_name: str = "",
    city: str = "北京"
) -> QuotePrice:
    """快捷报价函数"""
    return pricing_engine.quote(
        official_price=official_price,
        channel_cost=channel_cost,
        cinema_name=cinema_name,
        movie_name=movie_name,
        city=city
    )
