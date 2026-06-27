import httpx

from app.config import Settings
from app.models.schemas import Attraction, Location, TripPlanRequest, WeatherInfo
from app.services.sample_data import sample_attractions, sample_weather


class AMapService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://restapi.amap.com/v3"

    async def search_attractions(self, request: TripPlanRequest) -> list[Attraction]:
        if not self.settings.has_amap:
            return sample_attractions(request.city, request.preferences)

        raw_pois: list[dict] = []
        target_count = self._target_attraction_count(request.days)
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                for keyword in self._build_attraction_keywords(request):
                    for page in (1, 2):
                        params = {
                            "key": self.settings.amap_web_service_key,
                            "keywords": keyword,
                            "city": request.city,
                            "types": "110000|110100|110200",
                            "offset": 20,
                            "page": page,
                            "extensions": "all",
                        }
                        response = await client.get(f"{self.base_url}/place/text", params=params)
                        response.raise_for_status()
                        payload = response.json()
                        raw_pois.extend(payload.get("pois") or [])
                        if len(raw_pois) >= target_count * 3:
                            break
                    if len(raw_pois) >= target_count * 3:
                        break
        except httpx.HTTPError:
            return await self._fallback_attractions(request)

        attractions: list[Attraction] = []
        seen_names: set[str] = set()
        for poi in raw_pois:
            if not self._is_attraction_poi(poi):
                continue
            name = poi.get("name") or "未命名景点"
            if self._looks_like_non_attraction_name(name):
                continue
            normalized_name = self._normalize_name(name)
            if normalized_name in seen_names:
                continue
            location = self._parse_location(poi.get("location", ""))
            if location is None:
                continue
            seen_names.add(normalized_name)
            attractions.append(
                Attraction(
                    name=name,
                    address=poi.get("address") or request.city,
                    location=location,
                    visit_duration=90,
                    description=f"{poi.get('name')} 是 {request.city} 的推荐游览点，适合偏好 {request.preferences} 的行程。",
                    category=poi.get("type") or "景点",
                    rating=self._parse_rating(poi.get("biz_ext", {}).get("rating")),
                    ticket_price=self._estimate_ticket_price(poi.get("type", "")),
                )
            )
            if len(attractions) >= target_count:
                break

        return attractions or await self._fallback_attractions(request)

    async def query_weather(self, request: TripPlanRequest) -> list[WeatherInfo]:
        if not self.settings.has_amap:
            return sample_weather(request.start_date.isoformat(), request.days)

        try:
            adcode = await self._city_adcode(request.city)
        except httpx.HTTPError:
            return sample_weather(request.start_date.isoformat(), request.days)
        if not adcode:
            return sample_weather(request.start_date.isoformat(), request.days)

        params = {
            "key": self.settings.amap_web_service_key,
            "city": adcode,
            "extensions": "all",
        }
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(f"{self.base_url}/weather/weatherInfo", params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return sample_weather(request.start_date.isoformat(), request.days)

        casts = (payload.get("forecasts") or [{}])[0].get("casts") or []
        result = [
            WeatherInfo(
                date=cast.get("date"),
                day_weather=cast.get("dayweather", "未知"),
                night_weather=cast.get("nightweather", "未知"),
                day_temp=cast.get("daytemp", 0),
                night_temp=cast.get("nighttemp", 0),
                wind_direction=cast.get("daywind", "未知"),
                wind_power=cast.get("daypower", "未知"),
            )
            for cast in casts[: request.days]
            if cast.get("date")
        ]
        return result or sample_weather(request.start_date.isoformat(), request.days)

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

    async def _city_district(self, city: str) -> dict | None:
        params = {"key": self.settings.amap_web_service_key, "keywords": city, "subdistrict": 0}
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{self.base_url}/config/district", params=params)
            response.raise_for_status()
            payload = response.json()
        districts = payload.get("districts") or []
        return districts[0] if districts else None

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
    def _target_attraction_count(days: int) -> int:
        return max(12, min(36, days * 5))

    @staticmethod
    def _normalize_name(name: str) -> str:
        return "".join(name.lower().split())

    @staticmethod
    def _is_attraction_poi(poi: dict) -> bool:
        category = str(poi.get("type") or "")
        forbidden_categories = ("餐饮服务", "住宿服务", "购物服务", "生活服务", "商务住宅", "公司企业")
        if any(item in category for item in forbidden_categories):
            return False
        return "风景名胜" in category or "公园广场" in category

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
