from fastapi import APIRouter, BackgroundTasks
from typing import List

router = APIRouter()


@router.post("/trigger-check")
async def trigger_movie_check(background_tasks: BackgroundTasks):
    """手动触发电影检查"""
    async def check():
        from app.modules.monitor.service import MonitorService
        service = MonitorService()
        new_listings = await service.check_and_list_new_movies()
        return new_listings

    task = background_tasks.add_task(check)
    return {"status": "triggered", "task_id": id(task)}


@router.get("/status")
async def get_monitor_status():
    """获取监控状态"""
    from app.modules.monitor.service import MonitorService

    service = MonitorService()
    status = await service.get_monitor_status()
    return status


@router.post("/trigger-price-check")
async def trigger_price_check(background_tasks: BackgroundTasks):
    """手动触发价格检查"""
    async def check():
        from app.modules.monitor.service import MonitorService
        service = MonitorService()
        await service.update_listed_prices()

    background_tasks.add_task(check)
    return {"status": "triggered"}


@router.get("/listed-movies")
async def get_listed_movies():
    """获取已上架电影列表"""
    from app.modules.monitor.service import MonitorService

    service = MonitorService()
    status = await service.get_monitor_status()
    return {"movies": status.get("listed_movies", [])}


@router.post("/publish/{movie_name}")
async def publish_movie(movie_name: str, price: float = 50.0, background_tasks: BackgroundTasks = None):
    """手动上架某电影票商品"""
    from app.modules.monitor.service import MonitorService, Movie

    async def publish():
        service = MonitorService()
        movie = Movie(
            name=movie_name,
            release_date="",
            duration=0,
            genre="",
            director="",
            actors=[]
        )
        success = await service._list_movie_ticket(movie)
        return success

    if background_tasks:
        background_tasks.add_task(publish)
        return {"status": "triggered", "movie": movie_name}

    result = await publish()
    return {"status": "success" if result else "failed", "movie": movie_name}


@router.get("/upcoming")
async def get_upcoming_movies(days: int = 7):
    """获取即将上映的电影"""
    from app.modules.monitor.service import MovieDataService

    service = MovieDataService()
    movies = await service.fetch_upcoming_movies(days=days)
    return {
        "movies": [
            {
                "name": m.name,
                "release_date": m.release_date,
                "duration": m.duration,
                "genre": m.genre,
                "actors": m.actors
            }
            for m in movies
        ]
    }
