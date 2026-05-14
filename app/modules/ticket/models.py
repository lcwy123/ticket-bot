"""
票务模块 - 数据模型
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"           # 待处理
    QUOTED = "quoted"             # 已报价
    ACCEPTED = "accepted"         # 买家已接受
    PAID = "paid"                 # 已付款
    BOOKED = "booked"             # 已出票
    COMPLETED = "completed"       # 已完成
    CANCELLED = "cancelled"       # 已取消
    REFUNDED = "refunded"         # 已退款


class SeatType(str, Enum):
    """座位类型"""
    NORMAL = "normal"             # 普通座
    IMAX = "imax"                 # IMAX
    VIP = "vip"                   # VIP厅
    FOUR_DX = "4dx"               # 4DX
    COUPLE = "couple"             # 情侣座


@dataclass
class ShowTime:
    """场次信息"""
    show_id: str
    movie_name: str
    cinema_name: str
    cinema_address: str
    hall_name: str               # 影厅名称
    show_date: str               # 放映日期 2024-01-15
    show_time: str               # 放映时间 14:30
    duration: int                # 时长(分钟)
    language: str                # 语言版本
    price: float                 # 官方票价
    remaining_seats: int         # 剩余座位数
    url: str = ""


@dataclass
class SeatInfo:
    """座位信息"""
    seat_id: str
    row: str
    column: str
    seat_type: SeatType
    price: float                 # 座位价格
    is_available: bool


@dataclass
class OfficialTicket:
    """官方票（用于市价参考）"""
    movie_name: str
    cinema_name: str
    show_date: str
    show_time: str
    hall_name: str
    city: str
    official_price: float        # 官方票价
    channel_price: float = 0     # 渠道成本价（我们内部录入）
    service_fee: float = 0       # 服务费
    seat_type: str = "普通"
    source: str = "maoyan"       # 数据来源


@dataclass
class QuotePrice:
    """报价结果"""
    official_price: float         # 市价
    channel_cost: float          # 渠道成本
    quoted_price: float          # 我们的报价
    profit: float                # 利润
    profit_margin: float          # 利润率
    pricing_strategy: str        # 使用的报价策略


@dataclass
class ChannelCost:
    """渠道成本"""
    id: Optional[int] = None
    cinema_name: str             # 影院名称
    movie_name: str              # 影片名称（可选，空=通用）
    city: str                    # 城市
    cost_price: float            # 渠道成本价
    remark: str = ""             # 备注
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class TicketOrder:
    """票务订单"""
    id: Optional[int] = None
    order_id: str                # 订单号
    user_id: str                 # 买家闲鱼ID
    user_nickname: str = ""     # 买家昵称

    # 影片信息
    movie_name: str = ""
    cinema_name: str = ""
    city: str = ""
    show_date: str = ""
    show_time: str = ""

    # 价格信息
    official_price: float = 0   # 市价
    quoted_price: float = 0     # 我们的报价
    actual_cost: float = 0      # 实际渠道成本
    profit: float = 0           # 利润

    # 取票信息
    ticket_code: str = ""       # 取票码
    ticket_status: str = ""      # 取票状态

    # 状态
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    paid_at: datetime = None
    booked_at: datetime = None
    completed_at: datetime = None

    # 原始数据
    buyer_message: str = ""      # 买家留言
    admin_remark: str = ""      # 管理员备注
    raw_data: Dict = field(default_factory=dict)


@dataclass
class PricingConfig:
    """报价配置"""
    # 方案C: min(市价×系数, 成本价×系数)
    maidan_ratio: float = 0.8           # 市价折扣系数
    cost_ratio: float = 1.5             # 成本价加成系数
    min_profit: float = 5.0             # 最低利润(元)
    min_margin: float = 0.1             # 最低利润率(10%)

    # 备选报价策略
    use_floor_price: bool = True        # 是否使用保底价
    floor_price: float = 25.0          # 保底价
