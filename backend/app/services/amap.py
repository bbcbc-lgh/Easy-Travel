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

        params = {
            "key": self.settings.amap_web_service_key,
            "keywords": f"{request.city} 景点 {request.preferences}",
            "city": request.city,
            "types": "110000",
            "offset": 12,
            "page": 1,
            "extensions": "all",
        }
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(f"{self.base_url}/place/text", params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return sample_attractions(request.city, request.preferences)

        pois = payload.get("pois") or []
        attractions: list[Attraction] = []
        for poi in pois:
            location = self._parse_location(poi.get("location", ""))
            if location is None:
                continue
            attractions.append(
                Attraction(
                    name=poi.get("name") or "未命名景点",
                    address=poi.get("address") or request.city,
                    location=location,
                    visit_duration=90,
                    description=f"{poi.get('name')} 是 {request.city} 的推荐游览点，适合偏好 {request.preferences} 的行程。",
                    category=poi.get("type") or "景点",
                    rating=self._parse_rating(poi.get("biz_ext", {}).get("rating")),
                    ticket_price=self._estimate_ticket_price(poi.get("type", "")),
                )
            )

        return attractions or sample_attractions(request.city, request.preferences)

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
        params = {"key": self.settings.amap_web_service_key, "keywords": city, "subdistrict": 0}
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{self.base_url}/config/district", params=params)
            response.raise_for_status()
            payload = response.json()
        districts = payload.get("districts") or []
        return districts[0].get("adcode") if districts else None

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
