from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "闲鱼AI助手"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/ticket_bot"
    redis_url: str = "redis://localhost:6379/0"

    # MiniMax API (Anthropic兼容)
    anthropic_api_key: str = ""  # MiniMax API Key
    anthropic_base_url: str = "https://api.minimaxi.com/anthropic"
    anthropic_model: str = "MiniMax-M2.7"
    anthropic_max_tokens: int = 1024

    # Lark (Feishu)
    lark_app_id: str = "cli_aa8952b1f1399bef"
    lark_app_secret: str = "6pzRmW0sehYueV4I9Noh3dmRQxMLhZf7"
    lark_bot_name: str = "闲鱼AI助手"

    # Lark Agent (手机控制专用)
    lark_agent_app_id: str = "cli_aa8952b1f1399bef"
    lark_agent_app_secret: str = "6pzRmW0sehYueV4I9Noh3dmRQxMLhZf7"
    lark_agent_bot_name: str = "手机助手"

    # Xianyu (闲鱼)
    xianyu_phone: str = ""
    xianyu_password: str = ""

    # Xianyu APP Mode (vs Browser Mode)
    use_app_mode: bool = False  # True=使用APP客户端, False=使用浏览器
    xianyu_device_addr: str = ""  # 设备地址，如 "192.168.31.101:5555"
    xianyu_poll_interval: int = 30  # 消息轮询间隔(秒)

    # Webhook
    webhook_secret: str = ""  # Webhook 签名密钥，用于验证通知来源

    # Movie Ticket Platforms
    maoyan_url: str = "https://www.maoyan.com"
    taobao_ticket_url: str = "https://iao.tmall.com"

    # Service Fee
    service_fee_rate: float = 0.05  # 5% service fee
    min_service_fee: float = 2.0  # minimum 2 yuan

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
