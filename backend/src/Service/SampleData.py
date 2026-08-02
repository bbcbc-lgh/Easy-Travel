from src.Model.Schemas import Attraction, Hotel, Location, Meal, WeatherInfo


CITY_CENTERS: dict[str, Location] = {
    "北京": Location(longitude=116.397128, latitude=39.916527),
    "上海": Location(longitude=121.473701, latitude=31.230416),
    "杭州": Location(longitude=120.15507, latitude=30.274084),
    "成都": Location(longitude=104.066541, latitude=30.572269),
    "西安": Location(longitude=108.93977, latitude=34.341574),
    "贵阳": Location(longitude=106.630153, latitude=26.647661),
    "重庆": Location(longitude=106.551556, latitude=29.563009),
    "广州": Location(longitude=113.264385, latitude=23.129112),
    "深圳": Location(longitude=114.057868, latitude=22.543099),
    "南京": Location(longitude=118.796877, latitude=32.060255),
    "苏州": Location(longitude=120.585315, latitude=31.298886),
    "武汉": Location(longitude=114.305393, latitude=30.593099),
    "长沙": Location(longitude=112.938814, latitude=28.228209),
    "昆明": Location(longitude=102.833669, latitude=24.88149),
    "大理": Location(longitude=100.267638, latitude=25.606486),
    "厦门": Location(longitude=118.089425, latitude=24.479833),
    "青岛": Location(longitude=120.382665, latitude=36.066938),
}

DEFAULT_CITY_CENTER = Location(longitude=104.195397, latitude=35.86166)


def city_center(city: str) -> Location:
    return CITY_CENTERS.get(city, DEFAULT_CITY_CENTER)


def sample_attractions(city: str, preferences: str, center: Location | None = None) -> list[Attraction]:
    center = center or city_center(city)
    templates = [
        ("城市博物馆", "适合了解城市历史脉络与文化背景", "历史文化", 60, 120, 4.7),
        ("中央公园", "适合慢行、拍照和放松", "自然风光", 0, 90, 4.5),
        ("老街区", "适合体验本地生活、建筑和小吃", "城市漫游", 0, 100, 4.6),
        ("艺术中心", "适合展览、设计与当代文化体验", "艺术展览", 80, 120, 4.4),
        ("观景台", "适合俯瞰城市天际线", "城市地标", 120, 80, 4.3),
        ("特色市集", "适合购买伴手礼和体验本地烟火气", "美食购物", 30, 90, 4.2),
    ]
    # These records deliberately remain generic. They are offline preview data,
    # not actual venues, and must never be represented as booking/navigation data.
    return [
        Attraction(
            name=f"{city}{name}",
            address=f"{city}核心游览区 {index + 1} 号",
            location=Location(
                longitude=round(center.longitude + (index - 2) * 0.018, 6),
                latitude=round(center.latitude + ((index % 3) - 1) * 0.012, 6),
            ),
            visit_duration=duration,
            description=f"{description}。已结合你的偏好：{preferences}。",
            category=category,
            rating=rating,
            ticket_price=price,
            source="sample",
        )
        for index, (name, description, category, price, duration, rating) in enumerate(templates)
    ]


def sample_hotels(city: str, accommodation: str, budget: str) -> list[Hotel]:
    center = city_center(city)
    accommodation_prices = {
        "\u9752\u5e74\u65c5\u820d": 120,
        "\u7ecf\u6d4e\u578b\u9152\u5e97": 280,
        "\u8212\u9002\u578b\u9152\u5e97": 520,
        "\u9ad8\u7aef\u9152\u5e97": 980,
    }
    nightly = accommodation_prices.get(accommodation, {"\u7ecf\u6d4e": 260, "\u4e2d\u7b49": 460, "\u8212\u9002": 720, "\u8c6a\u534e": 980}.get(budget, 460))
    return [
        Hotel(
            name=f"{city}{accommodation}演示住宿",
            address="离线演示数据，暂无可导航地址",
            location=Location(longitude=center.longitude + 0.01, latitude=center.latitude + 0.008),
            price_range=f"{nightly - 80}-{nightly + 120} 元/晚",
            rating="4.6",
            distance="距主要景点约 2 公里",
            type=accommodation,
            estimated_cost=nightly,
            source="sample",
        ),
        Hotel(
            name=f"{city}交通便利演示住宿",
            address="离线演示数据，暂无可导航地址",
            location=Location(longitude=center.longitude - 0.012, latitude=center.latitude - 0.006),
            price_range=f"{max(nightly - 160, 180)}-{nightly + 60} 元/晚",
            rating="4.4",
            distance="距地铁站约 300 米",
            type="交通便利",
            estimated_cost=max(nightly - 100, 200),
            source="sample",
        ),
    ]


def sample_meals(city: str, budget: str) -> list[Meal]:
    cost_map = {"经济": (20, 45, 55), "中等": (35, 75, 90), "舒适": (55, 120, 160), "豪华": (90, 220, 320)}
    breakfast, lunch, dinner = cost_map.get(budget, (35, 75, 90))
    return [
        Meal(type="breakfast", name=f"{city}早餐演示建议", address="离线演示数据，暂无具体店名和地址", description="请在酒店周边选择评分较高、营业中的早餐店。", estimated_cost=breakfast, source="sample"),
        Meal(type="lunch", name=f"{city}午餐演示建议", address="离线演示数据，暂无具体店名和地址", description="请在上午景点附近按实时营业状态选择餐厅。", estimated_cost=lunch, source="sample"),
        Meal(type="dinner", name=f"{city}晚餐演示建议", address="离线演示数据，暂无具体店名和地址", description="请结合返程路线和实时评分选择晚餐。", estimated_cost=dinner, source="sample"),
    ]


def sample_weather(start_date: str, days: int) -> list[WeatherInfo]:
    from datetime import date, timedelta

    current = date.fromisoformat(start_date)
    weathers = ["晴", "多云", "阴", "小雨"]
    return [
        WeatherInfo(
            date=(current + timedelta(days=index)).isoformat(),
            day_weather=weathers[index % len(weathers)],
            night_weather="多云",
            day_temp=24 + index,
            night_temp=16 + index,
            wind_direction="东南",
            wind_power="3级",
            source="sample",
            notice="\u6f14\u793a\u5929\u6c14\uff0c\u4ec5\u7528\u4e8e\u79bb\u7ebf\u9884\u89c8\uff1b\u51fa\u884c\u524d\u8bf7\u67e5\u8be2\u5b9e\u65f6\u5929\u6c14\u3002",
        )
        for index in range(days)
    ]
