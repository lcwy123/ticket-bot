import asyncio
from typing import List, Optional, Dict
from dataclasses import dataclass, field
from loguru import logger
from playwright.async_api import async_playwright

from app.config import get_settings

settings = get_settings()


@dataclass
class TicketInfo:
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
    raw_data: Dict = field(default_factory=dict)


@dataclass
class MovieSearchResult:
    movie_name: str
    city: str
    tickets: List[TicketInfo] = field(default_factory=list)
    best_price: Optional[TicketInfo] = None
    search_time: float = field(default_factory=lambda: asyncio.get_event_loop().time)


class TicketPlatform:
    """票务平台基类"""

    def __init__(self, name: str, base_url: str):
        self.name = name
        self.base_url = base_url

    async def search(
        self,
        movie_name: Optional[str] = None,
        city: Optional[str] = None,
        cinema_name: Optional[str] = None,
        date: Optional[str] = None
    ) -> List[TicketInfo]:
        raise NotImplementedError


class MaoyanPlatform(TicketPlatform):
    """猫眼电影票平台"""

    def __init__(self):
        super().__init__("猫眼", "https://www.maoyan.com")

    async def search(
        self,
        movie_name: Optional[str] = None,
        city: Optional[str] = None,
        cinema_name: Optional[str] = None,
        date: Optional[str] = None
    ) -> List[TicketInfo]:
        tickets = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # 搜索电影
                if movie_name:
                    await page.goto(f"{self.base_url}/search")
                    await page.fill('input[type="text"]', movie_name)
                    await page.click('button[type="submit"]')
                    await page.wait_for_load_state("networkidle", timeout=10000)

                    # 解析搜索结果
                    movie_links = await page.query_selector_all(".movie-title")
                    if movie_links:
                        await movie_links[0].click()
                        await page.wait_for_load_state("networkidle", timeout=10000)

                # 获取影院列表
                cinema_selector = ".cinema-item"
                cinemas = await page.query_selector_all(cinema_selector)

                for cinema in cinemas[:10]:  # 取前10家影院
                    name_elem = await cinema.query_selector(".cinema-name")
                    price_elem = await cinema.query_selector(".price")

                    if name_elem and price_elem:
                        cinema_name_text = await name_elem.inner_text()
                        price_text = await price_elem.inner_text()

                        try:
                            price = float(price_text.replace("¥", "").strip())
                            service_fee = self._calculate_service_fee(price)

                            tickets.append(TicketInfo(
                                platform=self.name,
                                price=price + service_fee,
                                original_price=price,
                                service_fee=service_fee,
                                show_time="",
                                cinema=cinema_name_text,
                                movie=movie_name or "",
                                url=page.url,
                                raw_data={}
                            ))
                        except ValueError:
                            continue

                logger.info(f"Maoyan: found {len(tickets)} tickets")

            except Exception as e:
                logger.error(f"Maoyan search error: {e}")
            finally:
                await browser.close()

        return tickets

    def _calculate_service_fee(self, price: float) -> float:
        fee = price * settings.service_fee_rate
        return max(fee, settings.min_service_fee)


class TaobaoPlatform(TicketPlatform):
    """淘宝电影票平台"""

    def __init__(self):
        super().__init__("淘宝电影", "https://www.taobao.com")

    async def search(
        self,
        movie_name: Optional[str] = None,
        city: Optional[str] = None,
        cinema_name: Optional[str] = None,
        date: Optional[str] = None
    ) -> List[TicketInfo]:
        # TODO: 淘宝电影需要登录，且反爬较严格
        # 暂时返回空列表，后续实现
        logger.info("Taobao platform search not yet implemented")
        return []


class MtimePlatform(TicketPlatform):
    """时光网电影票平台"""

    def __init__(self):
        super().__init__("时光网", "https://www.mtime.com")

    async def search(
        self,
        movie_name: Optional[str] = None,
        city: Optional[str] = None,
        cinema_name: Optional[str] = None,
        date: Optional[str] = None
    ) -> List[TicketInfo]:
        tickets = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                if movie_name:
                    await page.goto(f"{self.base_url}/search")
                    await page.fill('#search-keyword', movie_name)
                    await page.click('.search-btn')
                    await page.wait_for_load_state("networkidle", timeout=10000)

                    # 解析结果
                    results = await page.query_selector_all(".movie-item")
                    if results:
                        await results[0].click()
                        await page.wait_for_load_state("networkidle", timeout=10000)

                # 获取影院和价格
                cinema_items = await page.query_selector_all(".cinema-list li")

                for item in cinema_items[:10]:
                    name_elem = await item.query_selector(".name")
                    price_elem = await item.query_selector(".price")

                    if name_elem and price_elem:
                        name = await name_elem.inner_text()
                        price_str = await price_elem.inner_text()

                        try:
                            price = float(price_str.replace("¥", "").strip())
                            service_fee = self._calculate_service_fee(price)

                            tickets.append(TicketInfo(
                                platform=self.name,
                                price=price + service_fee,
                                original_price=price,
                                service_fee=service_fee,
                                show_time="",
                                cinema=name,
                                movie=movie_name or "",
                                url=page.url,
                                raw_data={}
                            ))
                        except ValueError:
                            continue

                logger.info(f"Mtime: found {len(tickets)} tickets")

            except Exception as e:
                logger.error(f"Mtime search error: {e}")
            finally:
                await browser.close()

        return tickets

    def _calculate_service_fee(self, price: float) -> float:
        fee = price * settings.service_fee_rate
        return max(fee, settings.min_service_fee)


class TicketService:
    """电影票代购服务"""

    def __init__(self):
        self.platforms: List[TicketPlatform] = [
            MaoyanPlatform(),
            # TaobaoPlatform(),  # 暂不支持
            MtimePlatform(),
        ]

    def _calculate_service_fee(self, original_price: float) -> float:
        """计算代购手续费"""
        fee = original_price * settings.service_fee_rate
        return max(fee, settings.min_service_fee)

    async def search_tickets(
        self,
        movie_name: Optional[str] = None,
        city: Optional[str] = None,
        cinema_name: Optional[str] = None,
        date: Optional[str] = None
    ) -> List[TicketInfo]:
        """搜索多平台电影票"""
        tasks = [
            platform.search(movie_name, city, cinema_name, date)
            for platform in self.platforms
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_tickets = []
        for i, platform_tickets in enumerate(results):
            if isinstance(platform_tickets, list):
                all_tickets.extend(platform_tickets)
                logger.info(f"{self.platforms[i].name}: found {len(platform_tickets)} tickets")
            elif isinstance(platform_tickets, Exception):
                logger.error(f"{self.platforms[i].name} error: {platform_tickets}")

        logger.info(f"Total tickets found: {len(all_tickets)}")
        return all_tickets

    async def get_best_price(
        self,
        movie_name: str,
        city: str = "北京"
    ) -> Optional[TicketInfo]:
        """获取某电影最低价"""
        tickets = await self.search_tickets(movie_name=movie_name, city=city)
        if not tickets:
            return None
        return min(tickets, key=lambda t: t.price)

    async def search_cinemas(
        self,
        movie_name: str,
        city: str,
        date: Optional[str] = None
    ) -> List[Dict]:
        """搜索某电影在各大影院的报价"""
        tickets = await self.search_tickets(movie_name=movie_name, city=city, date=date)

        # 按影院分组
        cinema_map = {}
        for ticket in tickets:
            key = ticket.cinema
            if key not in cinema_map or ticket.price < cinema_map[key].price:
                cinema_map[key] = ticket

        return [
            {
                "cinema": t.cinema,
                "platform": t.platform,
                "price": t.price,
                "original_price": t.original_price,
                "service_fee": t.service_fee,
                "url": t.url
            }
            for t in cinema_map.values()
        ]

    async def create_proxy_order(
        self,
        platform: str,
        ticket_url: str,
        movie_name: str,
        show_time: str,
        cinema: str,
        price: float,
        quantity: int = 2
    ) -> dict:
        """创建代购订单"""
        service_fee = self._calculate_service_fee(price)
        total_price = price + service_fee

        order = {
            "order_id": f"PROXY_{platform.upper()}_{int(asyncio.get_event_loop().time())}",
            "platform": platform,
            "movie_name": movie_name,
            "show_time": show_time,
            "cinema": cinema,
            "original_price": price,
            "service_fee": service_fee,
            "total_price": total_price,
            "quantity": quantity,
            "status": "pending",
            "ticket_url": ticket_url
        }

        logger.info(f"Created proxy order: {order['order_id']}")
        return order
