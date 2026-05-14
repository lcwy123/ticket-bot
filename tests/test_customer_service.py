import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_root():
    """测试根路径"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "running"


@pytest.mark.asyncio
async def test_health():
    """测试健康检查"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_customer_service_chat():
    """测试客服对话接口"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/customer-service/chat",
            json={
                "user_id": "test_user",
                "message": "你好，我想买电影票"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert "session_id" in data


@pytest.mark.asyncio
async def test_ticket_search():
    """测试票务搜索接口"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/ticket/search",
            json={
                "movie_name": "热辣滚烫",
                "city": "北京"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "tickets" in data
        assert "best_price" in data
        assert "search_time" in data


@pytest.mark.asyncio
async def test_ticket_platforms():
    """测试获取票务平台列表"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/ticket/platforms")
        assert response.status_code == 200
        data = response.json()
        assert "platforms" in data
        assert len(data["platforms"]) > 0
