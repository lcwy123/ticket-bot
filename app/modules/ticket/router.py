from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter()


# ============== 请求/响应模型 ==============

class TicketSearchRequest(BaseModel):
    movie_name: Optional[str] = None
    city: Optional[str] = None
    cinema_name: Optional[str] = None
    date: Optional[str] = None


class TicketInfo(BaseModel):
    platform: str
    price: float
    original_price: float
    service_fee: float
    show_time: str
    cinema: str
    movie: str
    url: str
    seat_type: str = "普通"
    language: str = "国语"


class TicketSearchResponse(BaseModel):
    tickets: List[TicketInfo]
    best_price: Optional[TicketInfo]
    search_time: datetime


class OrderRequest(BaseModel):
    platform: str
    ticket_url: str
    movie_name: str
    show_time: str
    cinema: str
    price: float
    quantity: int = 2


# ============== 官方票价查询 ==============

@router.post("/search", response_model=TicketSearchResponse)
async def search_tickets(request: TicketSearchRequest):
    """搜索多平台电影票价格"""
    from app.modules.ticket.service import TicketService

    service = TicketService()
    tickets = await service.search_tickets(
        movie_name=request.movie_name,
        city=request.city,
        cinema_name=request.cinema_name,
        date=request.date
    )

    best_price = min(tickets, key=lambda t: t.price) if tickets else None

    return TicketSearchResponse(
        tickets=tickets,
        best_price=best_price,
        search_time=datetime.now()
    )


@router.get("/movie/{movie_name}")
async def get_movie_tickets(movie_name: str, city: str = "北京"):
    """获取指定电影的最低票价"""
    from app.modules.ticket.service import TicketService

    service = TicketService()
    tickets = await service.search_tickets(movie_name=movie_name, city=city)
    best_price = min(tickets, key=lambda t: t.price) if tickets else None
    return {"tickets": tickets, "best_price": best_price}


@router.get("/movie/{movie_name}/cinemas")
async def get_movie_cinemas(movie_name: str, city: str = "北京"):
    """获取某电影在各大影院的报价"""
    from app.modules.ticket.service import TicketService

    service = TicketService()
    cinemas = await service.search_cinemas(movie_name=movie_name, city=city)
    return {"cinemas": cinemas}


@router.get("/best-price/{movie_name}")
async def get_best_price(movie_name: str, city: str = "北京"):
    """获取某电影最低价"""
    from app.modules.ticket.service import TicketService

    service = TicketService()
    best = await service.get_best_price(movie_name=movie_name, city=city)
    if not best:
        raise HTTPException(status_code=404, detail="No tickets found")
    return {"best": best}


# ============== 官方票价API（新） ==============

@router.get("/official/showtimes")
async def get_showtimes(movie_name: str, city: str = "北京", date: str = None):
    """获取电影场次信息（官方票价）"""
    from app.modules.ticket.price_service import official_price_service

    shows = await official_price_service.search_movie_shows(movie_name, city, date)
    return {
        "movie_name": movie_name,
        "city": city,
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "showtimes": [
            {
                "show_id": s.show_id,
                "cinema_name": s.cinema_name,
                "hall_name": s.hall_name,
                "show_date": s.show_date,
                "show_time": s.show_time,
                "duration": s.duration,
                "language": s.language,
                "price": s.price,
                "remaining_seats": s.remaining_seats,
            }
            for s in shows
        ]
    }


@router.get("/official/price")
async def get_official_price(movie_name: str, cinema_name: str, city: str = "北京"):
    """获取某影院的官方票价"""
    from app.modules.ticket.price_service import official_price_service

    ticket = await official_price_service.get_official_price(movie_name, cinema_name, city)
    if not ticket:
        raise HTTPException(status_code=404, detail="未找到该影院的票价信息")

    return {
        "movie_name": ticket.movie_name,
        "cinema_name": ticket.cinema_name,
        "city": ticket.city,
        "show_date": ticket.show_date,
        "show_time": ticket.show_time,
        "official_price": ticket.official_price,
        "source": ticket.source,
    }


# ============== 渠道成本管理 ==============

class ChannelCostRequest(BaseModel):
    cinema_name: str
    city: str = "北京"
    cost_price: float
    movie_name: str = ""  # 可选，空=影院通用
    remark: str = ""


@router.post("/channel-cost")
async def add_channel_cost(request: ChannelCostRequest):
    """添加渠道成本"""
    from app.modules.ticket.channel_service import channel_cost_service

    cost = channel_cost_service.add_channel_cost(
        cinema_name=request.cinema_name,
        city=request.city,
        cost_price=request.cost_price,
        movie_name=request.movie_name,
        remark=request.remark
    )
    return {"success": True, "cost": {
        "id": cost.id,
        "cinema_name": cost.cinema_name,
        "movie_name": cost.movie_name,
        "city": cost.city,
        "cost_price": cost.cost_price,
        "remark": cost.remark,
    }}


@router.get("/channel-cost")
async def list_channel_costs(city: str = None):
    """列出渠道成本"""
    from app.modules.ticket.channel_service import channel_cost_service

    costs = channel_cost_service.list_channel_costs(city)
    return {
        "costs": [
            {
                "id": c.id,
                "cinema_name": c.cinema_name,
                "movie_name": c.movie_name,
                "city": c.city,
                "cost_price": c.cost_price,
                "remark": c.remark,
            }
            for c in costs
        ]
    }


@router.get("/channel-cost/{cinema_name}")
async def get_channel_cost(cinema_name: str, movie_name: str = "", city: str = "北京"):
    """获取指定影院/影片的渠道成本"""
    from app.modules.ticket.channel_service import channel_cost_service

    cost = channel_cost_service.get_channel_cost(cinema_name, movie_name, city)
    if not cost:
        return {"found": False, "message": "未找到该渠道成本"}

    return {
        "found": True,
        "cost": {
            "cinema_name": cost.cinema_name,
            "movie_name": cost.movie_name,
            "city": cost.city,
            "cost_price": cost.cost_price,
            "remark": cost.remark,
        }
    }


@router.delete("/channel-cost/{cost_id}")
async def delete_channel_cost(cost_id: int):
    """删除渠道成本"""
    from app.modules.ticket.channel_service import channel_cost_service

    success = channel_cost_service.delete_channel_cost(cost_id)
    return {"success": success}


# ============== 智能报价 ==============

class QuoteRequest(BaseModel):
    official_price: float
    channel_cost: float = 0
    cinema_name: str = ""
    movie_name: str = ""
    city: str = "北京"


@router.post("/quote")
async def quote_price(request: QuoteRequest):
    """智能报价（方案C）"""
    from app.modules.ticket.pricing_engine import pricing_engine

    quote = pricing_engine.quote(
        official_price=request.official_price,
        channel_cost=request.channel_cost,
        cinema_name=request.cinema_name,
        movie_name=request.movie_name,
        city=request.city
    )

    return {
        "official_price": quote.official_price,
        "channel_cost": quote.channel_cost,
        "quoted_price": quote.quoted_price,
        "profit": quote.profit,
        "profit_margin": quote.profit_margin,
        "strategy": quote.pricing_strategy,
    }


@router.post("/quote/batch")
async def batch_quote(movie_name: str, city: str = "北京"):
    """批量报价：查询场次后批量报价"""
    from app.modules.ticket.price_service import official_price_service
    from app.modules.ticket.pricing_engine import pricing_engine

    shows = await official_price_service.search_movie_shows(movie_name, city)
    results = []

    for show in shows:
        quote = pricing_engine.quote(
            official_price=show.price,
            cinema_name=show.cinema_name,
            movie_name=movie_name,
            city=city
        )
        results.append({
            "show_id": show.show_id,
            "cinema_name": show.cinema_name,
            "hall_name": show.hall_name,
            "show_time": f"{show.show_date} {show.show_time}",
            "official_price": show.price,
            "quoted_price": quote.quoted_price,
            "profit": quote.profit,
            "profit_margin": quote.profit_margin,
        })

    return {"movie_name": movie_name, "city": city, "quotes": results}


# ============== 订单管理 ==============

class CreateOrderRequest(BaseModel):
    user_id: str
    user_nickname: str = ""
    movie_name: str
    cinema_name: str
    city: str = "北京"
    show_date: str = ""
    show_time: str = ""
    official_price: float = 0
    quoted_price: float = 0
    actual_cost: float = 0
    buyer_message: str = ""


@router.post("/order")
async def create_order(request: CreateOrderRequest):
    """创建票务订单"""
    from app.modules.ticket.order_service import order_service

    order = order_service.create_order(
        user_id=request.user_id,
        user_nickname=request.user_nickname,
        movie_name=request.movie_name,
        cinema_name=request.cinema_name,
        city=request.city,
        show_date=request.show_date,
        show_time=request.show_time,
        official_price=request.official_price,
        quoted_price=request.quoted_price,
        actual_cost=request.actual_cost,
        buyer_message=request.buyer_message,
    )
    return {"order": {
        "order_id": order.order_id,
        "status": order.status.value,
        "created_at": order.created_at.isoformat(),
    }}


@router.get("/order/{order_id}")
async def get_order(order_id: str):
    """获取订单详情"""
    from app.modules.ticket.order_service import order_service

    order = order_service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    return {
        "order_id": order.order_id,
        "user_id": order.user_id,
        "user_nickname": order.user_nickname,
        "movie_name": order.movie_name,
        "cinema_name": order.cinema_name,
        "city": order.city,
        "show_date": order.show_date,
        "show_time": order.show_time,
        "official_price": order.official_price,
        "quoted_price": order.quoted_price,
        "actual_cost": order.actual_cost,
        "profit": order.profit,
        "ticket_code": order.ticket_code,
        "ticket_status": order.ticket_status,
        "status": order.status.value,
        "created_at": order.created_at.isoformat(),
        "buyer_message": order.buyer_message,
    }


@router.get("/orders")
async def list_orders(status: str = None, user_id: str = None, limit: int = 50):
    """列出订单"""
    from app.modules.ticket.order_service import order_service
    from app.modules.ticket.models import OrderStatus

    status_enum = OrderStatus(status) if status else None
    orders = order_service.list_orders(status=status_enum, user_id=user_id, limit=limit)

    return {
        "orders": [
            {
                "order_id": o.order_id,
                "user_nickname": o.user_nickname,
                "movie_name": o.movie_name,
                "cinema_name": o.cinema_name,
                "quoted_price": o.quoted_price,
                "profit": o.profit,
                "status": o.status.value,
                "created_at": o.created_at.isoformat(),
                "ticket_code": o.ticket_code,
            }
            for o in orders
        ]
    }


@router.post("/order/{order_id}/ticket-code")
async def set_ticket_code(order_id: str, ticket_code: str):
    """录入取票码"""
    from app.modules.ticket.order_service import order_service

    order = order_service.set_ticket_code(order_id, ticket_code)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    return {"success": True, "order_id": order.order_id, "ticket_code": order.ticket_code}


@router.post("/order/{order_id}/status")
async def update_order_status(order_id: str, status: str):
    """更新订单状态"""
    from app.modules.ticket.order_service import order_service
    from app.modules.ticket.models import OrderStatus

    try:
        new_status = OrderStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的订单状态")

    order = order_service.update_order_status(order_id, new_status)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    return {"success": True, "order_id": order.order_id, "status": order.status.value}


@router.get("/statistics")
async def get_statistics(days: int = 30):
    """获取统计数据"""
    from app.modules.ticket.order_service import order_service

    stats = order_service.get_statistics(days)
    return stats


# ============== 平台列表 ==============

@router.get("/platforms")
async def get_platforms():
    """获取支持的票务平台列表"""
    return {
        "platforms": [
            {"name": "猫眼", "code": "maoyan", "status": "active"},
            {"name": "淘宝电影", "code": "taobao", "status": "inactive"},
            {"name": "时光网", "code": "mtime", "status": "active"}
        ]
    }


@router.post("/order/{order_id}/confirm")
async def confirm_order(order_id: str, background_tasks: BackgroundTasks):
    """确认订单并开始代购（预留）"""
    # TODO: 实现订单确认和代购流程
    return {"status": "pending", "order_id": order_id, "message": "订单确认功能待实现"}
