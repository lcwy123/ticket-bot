import httpx
from typing import Optional
from loguru import logger

from app.config import get_settings

settings = get_settings()


class LarkService:
    """飞书服务"""

    def __init__(self):
        self.app_id = settings.lark_app_id
        self.app_secret = settings.lark_app_secret
        self.base_url = "https://open.feishu.cn/open-apis"

    async def get_access_token(self) -> str:
        """获取tenant_access_token"""
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            data = response.json()

            if data.get("code") != 0:
                raise Exception(f"Failed to get access token: {data}")
            return data["tenant_access_token"]

    async def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: dict,
        receive_id_type: str = "open_id"
    ) -> dict:
        """发送消息"""
        token = await self.get_access_token()
        url = f"{self.base_url}/im/v1/messages?receive_id_type={receive_id_type}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            data = response.json()

            if data.get("code") != 0:
                logger.error(f"Failed to send message: {data}")
                raise Exception(f"Failed to send message: {data}")

            return data

    async def send_text_message(self, receive_id: str, text: str):
        """发送文本消息"""
        return await self.send_message(
            receive_id=receive_id,
            msg_type="text",
            content={"text": text}
        )

    async def get_user_info(self, open_id: str) -> dict:
        """获取用户信息"""
        token = await self.get_access_token()
        url = f"{self.base_url}/contact/v3/users/{open_id}"

        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            return response.json()
