from collections.abc import Iterable
from datetime import timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from app.Config import Settings
from app.models.Schemas import Attraction, Hotel, Location, Meal, RouteLeg, TripPlan, TripPlanRequest, WeatherInfo
from app.services.SampleData import sample_attractions, sample_hotels, sample_meals, sample_weather


class AMapService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.v3_base_url = "https://restapi.amap.com/v3"
        self.v5_base_url = "https://restapi.amap.com/v5"

    async def search_attractions(self, request: TripPlanRequest) -> list[Attraction]:
        if not self.settings.has_amap:
            return sample_attractions(request.city, request.preferences)

        target_count = self._target_attraction_count(request.days)
        try:
            pois = await self._search_pois(
                city=request.city,
                keywords=self._build_attraction_keywords(request),
                types="110000|110100|110200|140000|140100",
                target_count=target_count * 3,
            )
        except httpx.HTTPError:
            return await self._fallback_attractions(request)

        attractions: list[Attraction] = []
        seen_names: set[str] = set()
        for poi in pois:
            if not self._is_attraction_poi(poi):
                continue
            name = self._text(poi.get("name"), "未命名景点")
            if self._looks_like_non_attraction_name(name):
                continue
            normalized_name = self._normalize_name(name)
            if normalized_name in seen_names:
                continue
            location = self._poi_location(poi)
            if location is None:
                continue
            seen_names.add(normalized_name)
            category = self._poi_category(poi) or "景点"
            attractions.append(
                Attraction(
                    name=name,
                    address=self._poi_address(poi, request.city),
                    location=location,
                    visit_duration=self._estimate_visit_duration(category, name),
                    description=self._poi_description(name, request.city, request.preferences, category),
                    category=category,
                    rating=self._poi_rating(poi),
                    ticket_price=self._estimate_ticket_price(category),
                )
            )
            if len(attractions) >= target_count:
                break

        return attractions or await self._fallback_attractions(request)

    async def search_hotels(self, request: TripPlanRequest) -> list[Hotel]:
        if not self.settings.has_amap:
            return sample_hotels(request.city, request.accommodation, request.budget)

        try:
            pois = await self._search_pois(
                city=request.city,
                keywords=self._build_hotel_keywords(request),
                types="100000|100100|100101|100102|100105",
                target_count=18,
            )
        except httpx.HTTPError:
            return sample_hotels(request.city, request.accommodation, request.budget)

        hotels: list[Hotel] = []
        seen_names: set[str] = set()
        for poi in pois:
            name = self._text(poi.get("name"), "")
            location = self._poi_location(poi)
            if not name or location is None or self._normalize_name(name) in seen_names:
                continue
            seen_names.add(self._normalize_name(name))
            rating = self._text(self._biz_ext(poi).get("rating"), "")
            nightly = self._estimate_hotel_cost(request.budget, poi)
            hotels.append(
                Hotel(
                    name=name,
                    address=self._poi_address(poi, request.city),
                    location=location,
                    price_range=f"{max(nightly - 80, 120)}-{nightly + 120} 元/晚",
                    rating=rating or "暂无评分",
                    distance="按行程景点位置动态选择",
                    type=self._poi_category(poi) or request.accommodation,
                    estimated_cost=nightly,
                )
            )
            if len(hotels) >= 6:
                break

        return hotels or sample_hotels(request.city, request.accommodation, request.budget)

    async def search_meals(self, request: TripPlanRequest) -> list[Meal]:
        if not self.settings.has_amap:
            return sample_meals(request.city, request.budget)

        try:
            pois = await self._search_pois(
                city=request.city,
                keywords=self._build_food_keywords(request),
                types="050000",
                target_count=max(24, request.days * 6),
            )
        except httpx.HTTPError:
            return sample_meals(request.city, request.budget)

        meal_types = ("breakfast", "lunch", "dinner")
        meals: list[Meal] = []
        seen_names: set[str] = set()
        for index, poi in enumerate(pois):
            name = self._text(poi.get("name"), "")
            location = self._poi_location(poi)
            if not name or location is None or self._normalize_name(name) in seen_names:
                continue
            seen_names.add(self._normalize_name(name))
            meals.append(
                Meal(
                    type=meal_types[index % len(meal_types)],
                    name=name,
                    address=self._poi_address(poi, request.city),
                    location=location,
                    description=self._poi_category(poi) or "本地餐饮推荐",
                    estimated_cost=self._estimate_meal_cost(request.budget, poi),
                )
            )
            if len(meals) >= max(9, request.days * 3):
                break

        return meals or sample_meals(request.city, request.budget)

    async def query_weather(self, request: TripPlanRequest) -> list[WeatherInfo]:
        if not self.settings.has_amap:
            return sample_weather(request.start_date.isoformat(), request.days)

        try:
            adcode = await self._city_adcode(request.city)
        except httpx.HTTPError:
            return self._unavailable_weather_range(request, None)
        if not adcode:
            return self._unavailable_weather_range(request, None)

        params = {
            "key": self.settings.amap_web_service_key,
            "city": adcode,
            "extensions": "all",
        }
        try:
            payload = await self._get_json(f"{self.v3_base_url}/weather/weatherInfo", params)
        except httpx.HTTPError:
            return self._unavailable_weather_range(request, None)

        casts = [
            cast
            for cast in (payload.get("forecasts") or [{}])[0].get("casts") or []
            if cast.get("date")
        ]
        if not casts:
            return self._unavailable_weather_range(request, None)

        cast_by_date = {cast["date"]: cast for cast in casts}
        latest_forecast_date = max(cast_by_date)
        result: list[WeatherInfo] = []
        for index in range(request.days):
            current_date = (request.start_date + timedelta(days=index)).isoformat()
            cast = cast_by_date.get(current_date)
            if cast is None:
                result.append(self._unavailable_weather(current_date, latest_forecast_date))
                continue
            result.append(
                WeatherInfo(
                    date=current_date,
                    day_weather=cast.get("dayweather", "未知"),
                    night_weather=cast.get("nightweather", "未知"),
                    day_temp=cast.get("daytemp", 0),
                    night_temp=cast.get("nighttemp", 0),
                    wind_direction=cast.get("daywind", "未知"),
                    wind_power=cast.get("daypower", "未知"),
                )
            )
        return result

    async def enrich_daily_routes(self, plan: TripPlan, request: TripPlanRequest) -> TripPlan:
        for day in plan.days:
            route_points: list[tuple[str, Location]] = []
            if day.hotel and day.hotel.location:
                route_points.append((day.hotel.name, day.hotel.location))
            route_points.extend((item.name, item.location) for item in day.attractions)
            if len(route_points) < 2:
                day.routes = []
                continue

            day.routes = []
            for (origin_name, origin), (destination_name, destination) in zip(route_points, route_points[1:]):
                day.routes.append(
                    await self.estimate_route(
                        origin_name=origin_name,
                        origin=origin,
                        destination_name=destination_name,
                        destination=destination,
                        request=request,
                    )
                )
        return plan

    async def estimate_route(
        self,
        origin_name: str,
        origin: Location,
        destination_name: str,
        destination: Location,
        request: TripPlanRequest,
    ) -> RouteLeg:
        if not self.settings.has_amap:
            return self._haversine_route(origin_name, origin, destination_name, destination, request.transportation)

        mode = self._route_mode(request.transportation)
        params = {
            "key": self.settings.amap_web_service_key,
            "origin": self._format_location(origin),
            "destination": self._format_location(destination),
        }
        if mode == "transit":
            params["city1"] = request.city
            params["city2"] = request.city

        try:
            payload = await self._get_json(self._route_endpoint(mode), params)
            parsed = self._parse_route_payload(payload, mode)
        except httpx.HTTPError:
            parsed = None

        if parsed is None:
            return self._haversine_route(origin_name, origin, destination_name, destination, request.transportation)
        distance, duration = parsed
        return RouteLeg(
            origin=origin_name,
            destination=destination_name,
            distance_meters=distance,
            duration_minutes=duration,
            mode=request.transportation,
        )

    async def _search_pois(
        self,
        city: str,
        keywords: Iterable[str],
        types: str,
        target_count: int,
    ) -> list[dict[str, Any]]:
        pois: list[dict[str, Any]] = []
        for keyword in keywords:
            for page in (1, 2):
                payload = await self._search_pois_v5(city, keyword, types, page)
                pois.extend(payload)
                if len(pois) >= target_count:
                    return pois
        if pois:
            return pois
        for keyword in keywords:
            for page in (1, 2):
                payload = await self._search_pois_v3(city, keyword, types, page)
                pois.extend(payload)
                if len(pois) >= target_count:
                    return pois
        return pois

    async def _search_pois_v5(self, city: str, keyword: str, types: str, page: int) -> list[dict[str, Any]]:
        params = {
            "key": self.settings.amap_web_service_key,
            "keywords": keyword,
            "types": types,
            "region": city,
            "city_limit": "true",
            "show_fields": "business,photos",
            "page_size": 25,
            "page_num": page,
        }
        payload = await self._get_json(f"{self.v5_base_url}/place/text", params)
        return payload.get("pois") or []

    async def _search_pois_v3(self, city: str, keyword: str, types: str, page: int) -> list[dict[str, Any]]:
        params = {
            "key": self.settings.amap_web_service_key,
            "keywords": keyword,
            "city": city,
            "types": types,
            "citylimit": "true",
            "offset": 20,
            "page": page,
            "extensions": "all",
        }
        payload = await self._get_json(f"{self.v3_base_url}/place/text", params)
        return payload.get("pois") or []

    async def _city_adcode(self, city: str) -> str | None:
        district = await self._city_district(city)
        return district.get("adcode") if district else None

    async def _fallback_attractions(self, request: TripPlanRequest) -> list[Attraction]:
        center = None
        if self.settings.has_amap:
            try:
                center = await self._city_location(request.city)
            except httpx.HTTPError:
                center = None
        return sample_attractions(request.city, request.preferences, center=center)

    async def _city_location(self, city: str) -> Location | None:
        district = await self._city_district(city)
        if not district:
            return None
        return self._parse_location(district.get("center", ""))

    async def _city_district(self, city: str) -> dict[str, Any] | None:
        params = {
            "key": self.settings.amap_web_service_key,
            "keywords": city,
            "subdistrict": 0,
            "extensions": "base",
        }
        payload = await self._get_json(f"{self.v3_base_url}/config/district", params)
        districts = payload.get("districts") or []
        return districts[0] if districts else None

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if str(payload.get("status", "1")) == "0":
            raise httpx.HTTPStatusError(
                f"AMap API error: {payload.get('info') or payload.get('message')}",
                request=response.request,
                response=response,
            )
        return payload

    @staticmethod
    def _unavailable_weather_range(request: TripPlanRequest, latest_forecast_date: str | None) -> list[WeatherInfo]:
        return [
            AMapService._unavailable_weather(
                (request.start_date + timedelta(days=index)).isoformat(),
                latest_forecast_date,
            )
            for index in range(request.days)
        ]

    @staticmethod
    def _unavailable_weather(date: str, latest_forecast_date: str | None) -> WeatherInfo:
        if latest_forecast_date:
            notice = f"行程日期超过高德天气预报最晚日期 {latest_forecast_date}，无法保证查询天气。"
        else:
            notice = "暂时无法获取高德天气预报，无法保证查询天气。"
        return WeatherInfo(
            date=date,
            day_weather="暂无预报",
            night_weather="暂无预报",
            day_temp=0,
            night_temp=0,
            wind_direction="未知",
            wind_power="未知",
            forecast_available=False,
            notice=notice,
        )

    @staticmethod
    def _build_attraction_keywords(request: TripPlanRequest) -> list[str]:
        base_keywords = [
            f"{request.city} 景点",
            f"{request.city} 必游",
            f"{request.city} 博物馆",
            f"{request.city} 公园",
            f"{request.city} 老街",
            f"{request.city} 地标",
        ]
        preference_parts = [
            part.strip()
            for part in request.preferences.replace("，", ",").replace("、", ",").split(",")
            if part.strip()
        ]
        preference_keywords = [f"{request.city} {part}" for part in preference_parts[:4]]
        keywords = [f"{request.city} 景点 {request.preferences}", *preference_keywords, *base_keywords]
        return list(dict.fromkeys(keywords))

    @staticmethod
    def _build_hotel_keywords(request: TripPlanRequest) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    f"{request.city} {request.accommodation}",
                    f"{request.city} 酒店",
                    f"{request.city} 住宿",
                    f"{request.city} 民宿",
                ]
            )
        )

    @staticmethod
    def _build_food_keywords(request: TripPlanRequest) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    f"{request.city} 美食",
                    f"{request.city} 特色餐厅",
                    f"{request.city} 小吃",
                    f"{request.city} 老字号",
                    f"{request.city} {request.preferences} 餐厅",
                ]
            )
        )

    @staticmethod
    def _target_attraction_count(days: int) -> int:
        return max(12, min(36, days * 5))

    @staticmethod
    def _normalize_name(name: str) -> str:
        return "".join(name.lower().split())

    @staticmethod
    def _is_attraction_poi(poi: dict[str, Any]) -> bool:
        category = AMapService._poi_category(poi)
        forbidden_categories = ("餐饮服务", "住宿服务", "购物服务", "生活服务", "商务住宅", "公司企业")
        if any(item in category for item in forbidden_categories):
            return False
        return any(item in category for item in ("风景名胜", "公园广场", "科教文化", "博物馆"))

    @staticmethod
    def _looks_like_non_attraction_name(name: str) -> bool:
        food_or_shop_terms = (
            "餐厅",
            "饭店",
            "酒楼",
            "小吃",
            "火锅",
            "烧烤",
            "咖啡",
            "奶茶",
            "甜品",
            "椰子鸡",
            "窑鸡",
            "盐焗",
            "门店",
        )
        if any(term in name for term in food_or_shop_terms):
            return True
        return name.endswith("店") or "店)" in name or "店）" in name

    @staticmethod
    def _poi_location(poi: dict[str, Any]) -> Location | None:
        return AMapService._parse_location(poi.get("location", ""))

    @staticmethod
    def _poi_address(poi: dict[str, Any], fallback: str) -> str:
        return AMapService._text(poi.get("address"), fallback)

    @staticmethod
    def _poi_category(poi: dict[str, Any]) -> str:
        return AMapService._text(poi.get("type") or poi.get("typecode"), "")

    @staticmethod
    def _biz_ext(poi: dict[str, Any]) -> dict[str, Any]:
        biz_ext = poi.get("biz_ext") or poi.get("business") or {}
        return biz_ext if isinstance(biz_ext, dict) else {}

    @staticmethod
    def _poi_rating(poi: dict[str, Any]) -> float | None:
        return AMapService._parse_rating(AMapService._biz_ext(poi).get("rating"))

    @staticmethod
    def _poi_description(name: str, city: str, preferences: str, category: str) -> str:
        return f"{name} 是 {city} 的推荐游览点，类型为 {category or '景点'}，适合偏好 {preferences} 的行程。"

    @staticmethod
    def _parse_location(value: str) -> Location | None:
        try:
            longitude, latitude = value.split(",", 1)
            return Location(longitude=float(longitude), latitude=float(latitude))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _parse_rating(value: object) -> float | None:
        try:
            rating = float(value)
            return rating if 0 <= rating <= 5 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _estimate_ticket_price(category: str) -> int:
        if "博物馆" in category:
            return 50
        if "风景" in category or "公园" in category:
            return 30
        return 60

    @staticmethod
    def _estimate_visit_duration(category: str, name: str) -> int:
        if "博物馆" in category or "艺术" in name:
            return 120
        if "公园" in category or "风景" in category:
            return 100
        return 90

    @staticmethod
    def _estimate_hotel_cost(budget: str, poi: dict[str, Any]) -> int:
        cost_map = {"经济": 260, "中等": 460, "舒适": 720, "豪华": 1200}
        biz_cost = AMapService._to_int(AMapService._biz_ext(poi).get("cost"))
        if biz_cost:
            return biz_cost
        return cost_map.get(budget, 460)

    @staticmethod
    def _estimate_meal_cost(budget: str, poi: dict[str, Any]) -> int:
        cost_map = {"经济": 45, "中等": 85, "舒适": 140, "豪华": 260}
        biz_cost = AMapService._to_int(AMapService._biz_ext(poi).get("cost"))
        if biz_cost:
            return biz_cost
        return cost_map.get(budget, 85)

    @staticmethod
    def _to_int(value: object) -> int | None:
        try:
            return int(float(str(value).replace("元", "").strip()))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _text(value: object, fallback: str) -> str:
        if isinstance(value, list):
            return fallback
        if value is None:
            return fallback
        text = str(value).strip()
        return text if text else fallback

    @staticmethod
    def _format_location(location: Location) -> str:
        return f"{location.longitude},{location.latitude}"

    @staticmethod
    def _route_mode(transportation: str) -> str:
        if "自驾" in transportation:
            return "driving"
        if "步行" in transportation:
            return "walking"
        if "公共" in transportation or "公交" in transportation or "地铁" in transportation:
            return "transit"
        return "driving"

    def _route_endpoint(self, mode: str) -> str:
        if mode == "walking":
            return f"{self.v5_base_url}/direction/walking"
        if mode == "transit":
            return f"{self.v3_base_url}/direction/transit/integrated"
        return f"{self.v5_base_url}/direction/driving"

    @staticmethod
    def _parse_route_payload(payload: dict[str, Any], mode: str) -> tuple[int, int] | None:
        route = payload.get("route") or {}
        if mode == "transit":
            transits = route.get("transits") or []
            if not transits:
                return None
            distance = AMapService._to_int(transits[0].get("distance")) or 0
            duration = AMapService._to_int(transits[0].get("duration")) or 0
            return distance, max(round(duration / 60), 1)

        paths = route.get("paths") or []
        if not paths:
            return None
        distance = AMapService._to_int(paths[0].get("distance")) or 0
        duration = AMapService._to_int(paths[0].get("duration")) or 0
        return distance, max(round(duration / 60), 1)

    @staticmethod
    def _haversine_route(
        origin_name: str,
        origin: Location,
        destination_name: str,
        destination: Location,
        mode: str,
    ) -> RouteLeg:
        longitude_delta = radians(destination.longitude - origin.longitude)
        latitude_delta = radians(destination.latitude - origin.latitude)
        origin_latitude = radians(origin.latitude)
        destination_latitude = radians(destination.latitude)
        haversine = (
            sin(latitude_delta / 2) ** 2
            + cos(origin_latitude) * cos(destination_latitude) * sin(longitude_delta / 2) ** 2
        )
        distance = int(6371000 * 2 * asin(sqrt(haversine)))
        speed_meters_per_minute = 650 if "自驾" in mode or "打车" in mode else 320
        duration = max(round(distance / speed_meters_per_minute), 1)
        return RouteLeg(
            origin=origin_name,
            destination=destination_name,
            distance_meters=distance,
            duration_minutes=duration,
            mode=mode,
        )
