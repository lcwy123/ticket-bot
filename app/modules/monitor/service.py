import asyncio
import json
import httpx
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from loguru import logger

import redis
from playwright.async_api import async_playwright

from app.config import get_settings

settings = get_settings()


@dataclass
class Movie:
    """电影信息"""
    name: str
    release_date: str
    duration: int  # 分钟
    genre: str
    director: str
    actors: List[str]
    poster_url: str = ""
    description: str = ""
    language: str = "国语"


@dataclass
class ListedMovie:
    """已上架电影"""
    movie_name: str
    listed_at: datetime
    last_price_check: datetime
    lowest_price: float = 0
    status: str = "active"  # active, sold_out, removed


class MovieDataService:
    """电影数据服务 - 对接外部API"""

    BASE_URLS = {
        "douban": "https://api.douban.com/v2",
        "maoyan": "https://api.maoyan.com"
    }

    async def fetch_releasing_movies_douban(self, city: str = "北京") -> List[Movie]:
        """从豆瓣获取正在上映的电影"""
        movies = []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # 豆瓣上映中的电影
                response = await client.get(
                    f"{self.BASE_URLS['douban']}/film/in_theaters",
                    params={"city": city}
                )

                if response.status_code == 200:
                    data = response.json()
                    subjects = data.get("subjects", [])

                    for subject in subjects:
                        movie = Movie(
                            name=subject.get("title", ""),
                            release_date=subject.get("main_pubdate", ""),
                            duration=0,
                            genre="/".join(subject.get("genres", [])),
                            director="",
                            actors=[a.get("name", "") for a in subject.get("casts", [])],
                            poster_url=subject.get("cover", ""),
                            description=subject.get("intro", "")
                        )
                        movies.append(movie)

                    logger.info(f"Fetched {len(movies)} movies from Douban")

        except Exception as e:
            logger.error(f"Failed to fetch from Douban: {e}")

        return movies

    async def fetch_releasing_movies_maoyan(self) -> List[Movie]:
        """从猫眼获取正在上映的电影"""
        movies = []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    "https://piaofang.maoyan.com/dashboard/movie",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    # 解析猫眼数据结构
                    movie_list = data.get("data", {}).get("movieList", [])

                    for item in movie_list:
                        movie = Movie(
                            name=item.get("movieName", ""),
                            release_date=item.get("releaseDate", ""),
                            duration=item.get("duration", 0),
                            genre=item.get("type", ""),
                            director=item.get("director", ""),
                            actors=[a.get("star", "") for a in item.get("actors", [])],
                            poster_url=item.get("poster", ""),
                            description=item.get("synopsis", "")
                        )
                        movies.append(movie)

                    logger.info(f"Fetched {len(movies)} movies from Maoyan")

        except Exception as e:
            logger.error(f"Failed to fetch from Maoyan: {e}")

        return movies

    async def fetch_upcoming_movies(self, days: int = 7) -> List[Movie]:
        """获取即将上映的电影"""
        movies = []

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # 豆瓣即将上映
                response = await client.get(
                    f"{self.BASE_URLS['douban']}/filmcoming",
                    params={"start": 0, "count": 20}
                )

                if response.status_code == 200:
                    data = response.json()
                    entries = data.get("entries", [])

                    for entry in entries:
                        release_str = entry.get("release_date", "")
                        # 只取指定天数内的
                        try:
                            release_date = datetime.strptime(release_str, "%Y-%m-%d")
                            if release_date <= datetime.now() + timedelta(days=days):
                                movie = Movie(
                                    name=entry.get("title", ""),
                                    release_date=release_str,
                                    duration=entry.get("duration", 0),
                                    genre="/".join(entry.get("genres", [])),
                                    director=entry.get("directors", [{}])[0].get("name", ""),
                                    actors=[a.get("name", "") for a in entry.get("casts", [])],
                                    poster_url=entry.get("cover", ""),
                                    description=entry.get("intro", "")
                                )
                                movies.append(movie)
                        except (ValueError, IndexError):
                            continue

                    logger.info(f"Fetched {len(movies)} upcoming movies")

        except Exception as e:
            logger.error(f"Failed to fetch upcoming movies: {e}")

        return movies


class XianyuListingService:
    """闲鱼商品上架服务"""

    def __init__(self):
        self.login_url = "https://login.taobao.com"
        self.xianyu_url = "https://www.xianyu.com"

    async def login(self, page, phone: str, password: str) -> bool:
        """登录淘宝/闲鱼"""
        try:
            await page.goto(self.login_url, wait_until="networkidle")
            await page.wait_for_timeout(2000)

            # 输入账号密码
            await page.fill("#fm-login-id", phone)
            await page.fill("#fm-login-password", password)

            # 点击登录
            await page.click(".fm-btn")

            # 等待登录完成
            await page.wait_for_url("**/taobao.com**", timeout=30000)
            logger.info("Login successful")
            return True

        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    async def publish_ticket_item(
        self,
        page,
        movie: Movie,
        price: float = 50.0,
        description: str = ""
    ) -> Optional[str]:
        """发布电影票商品"""
        try:
            await page.goto(f"{self.xianyu_url}/publish", wait_until="networkidle")

            # 等待页面加载
            await page.wait_for_selector(".publish-form", timeout=10000)

            # 标题
            title = f"代购 {movie.name} 电影票 影院取票"
            await page.fill("input[name='title']", title)

            # 价格
            await page.fill("input[name='price']", str(price))

            # 商品描述
            desc = description or f"""代购电影票服务

电影名称：{movie.name}
上映日期：{movie.release_date}
导演：{movie.director}
演员：{', '.join(movie.actors[:3])}

服务说明：
1. 提前1-2小时预订
2. 影院现场取票
3. 支持全国各大城市

代购费{settings.service_fee_rate * 100:.0f}%，最低{settings.min_service_fee:.0f}元
"""
            await page.fill("textarea[name='description']", desc)

            # 选择分类（虚拟商品 > 票务）
            await page.click("select[name='category']")
            await page.wait_for_timeout(500)

            # 发布按钮
            await page.click(".publish-btn")

            await page.wait_for_timeout(3000)

            # 获取商品链接
            item_url = page.url
            logger.info(f"Published item: {title}, URL: {item_url}")
            return item_url

        except Exception as e:
            logger.error(f"Failed to publish item: {e}")
            return None

    async def update_item_price(self, page, item_id: str, new_price: float) -> bool:
        """更新商品价格"""
        try:
            await page.goto(f"{self.xianyu_url}/item/{item_id}", wait_until="networkidle")
            await page.wait_for_timeout(2000)

            # 点击编辑
            await page.click(".edit-btn")
            await page.wait_for_selector("input[name='price']", timeout=5000)

            # 修改价格
            await page.fill("input[name='price']", str(new_price))

            # 保存
            await page.click(".save-btn")
            await page.wait_for_timeout(2000)

            logger.info(f"Updated item {item_id} price to {new_price}")
            return True

        except Exception as e:
            logger.error(f"Failed to update item price: {e}")
            return False


class MonitorService:
    """院线监控服务"""

    def __init__(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        self.movie_service = MovieDataService()
        self.xianyu_service = XianyuListingService()
        self.listed_movies_key = "xianyu:monitor:listed_movies"
        self.last_check_key = "xianyu:monitor:last_check"

    def _get_listed_movies(self) -> Dict[str, ListedMovie]:
        """获取已上架电影列表"""
        data = self.redis.hgetall(self.listed_movies_key)
        result = {}
        for name, json_str in data.items():
            try:
                obj = json.loads(json_str)
                result[name] = ListedMovie(
                    movie_name=obj["movie_name"],
                    listed_at=datetime.fromisoformat(obj["listed_at"]),
                    last_price_check=datetime.fromisoformat(obj["last_price_check"]),
                    lowest_price=obj.get("lowest_price", 0),
                    status=obj.get("status", "active")
                )
            except (json.JSONDecodeError, KeyError):
                continue
        return result

    def _save_listed_movie(self, movie: ListedMovie):
        """保存已上架电影"""
        data = {
            "movie_name": movie.movie_name,
            "listed_at": movie.listed_at.isoformat(),
            "last_price_check": movie.last_price_check.isoformat(),
            "lowest_price": movie.lowest_price,
            "status": movie.status
        }
        self.redis.hset(self.listed_movies_key, movie.movie_name, json.dumps(data))

    async def fetch_releasing_movies(self) -> List[Movie]:
        """获取当前上映电影列表"""
        # 尝试多个数据源
        movies = await self.movie_service.fetch_releasing_movies_douban()

        if not movies:
            movies = await self.movie_service.fetch_releasing_movies_maoyan()

        return movies

    async def check_and_list_new_movies(self) -> List[str]:
        """检查新电影并自动上架，返回新上架的电影列表"""
        logger.info("Starting new movie check...")

        # 获取当前上映
        movies = await self.fetch_releasing_movies()

        # 获取已上架列表
        listed = self._get_listed_movies()

        new_listed = []

        for movie in movies:
            if movie.name not in listed:
                logger.info(f"New movie detected: {movie.name}")

                # 尝试自动上架
                success = await self._list_movie_ticket(movie)
                if success:
                    new_listed.append(movie.name)

                    # 更新记录
                    listed[movie.name] = ListedMovie(
                        movie_name=movie.name,
                        listed_at=datetime.now(),
                        last_price_check=datetime.now(),
                        lowest_price=50.0,  # 默认价格
                        status="active"
                    )
                    self._save_listed_movie(listed[movie.name])

        # 更新检查时间
        self.redis.set(self.last_check_key, datetime.now().isoformat())

        logger.info(f"New movie check complete. New listings: {len(new_listed)}")
        return new_listed

    async def update_listed_prices(self):
        """更新已上架商品的价格"""
        logger.info("Starting price update...")

        listed = self._get_listed_movies()
        if not listed:
            logger.info("No listed movies to update")
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # 登录闲鱼
                logged_in = await self.xianyu_service.login(
                    page,
                    settings.xianyu_phone,
                    settings.xianyu_password
                )

                if not logged_in:
                    logger.error("Failed to login to Xianyu")
                    return

                for movie_name, info in listed.items():
                    if info.status != "active":
                        continue

                    # 获取最新票价
                    tickets = await self._get_latest_price(movie_name)
                    if tickets:
                        lowest = min(t.price for t in tickets)
                        info.lowest_price = lowest
                        info.last_price_check = datetime.now()

                        # 更新闲鱼价格
                        # await self.xianyu_service.update_item_price(page, item_id, lowest)

                        self._save_listed_movie(info)
                        logger.info(f"Updated {movie_name} price: {lowest}")

            finally:
                await browser.close()

    async def _list_movie_ticket(self, movie: Movie) -> bool:
        """在闲鱼上架电影票商品"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # 登录
                logged_in = await self.xianyu_service.login(
                    page,
                    settings.xianyu_phone,
                    settings.xianyu_password
                )

                if not logged_in:
                    logger.error(f"Failed to login for {movie.name}")
                    return False

                # 发布商品
                url = await self.xianyu_service.publish_ticket_item(page, movie)
                return url is not None

            except Exception as e:
                logger.error(f"Failed to list {movie.name}: {e}")
                return False
            finally:
                await browser.close()

    async def _get_latest_price(self, movie_name: str) -> List:
        """获取某电影的最新票价"""
        from app.modules.ticket.service import TicketService

        service = TicketService()
        return await service.search_tickets(movie_name=movie_name)

    async def get_monitor_status(self) -> Dict:
        """获取监控状态"""
        listed = self._get_listed_movies()
        last_check = self.redis.get(self.last_check_key)

        return {
            "total_listed": len(listed),
            "active": sum(1 for m in listed.values() if m.status == "active"),
            "last_check": last_check,
            "listed_movies": [
                {
                    "name": m.movie_name,
                    "listed_at": m.listed_at.isoformat(),
                    "lowest_price": m.lowest_price,
                    "status": m.status
                }
                for m in listed.values()
            ]
        }
