import asyncio
import logging
from collections.abc import Iterable
from datetime import timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from src.config import Settings
from src.model.schemas import (
    Attraction,
    DayPlan,
    Hotel,
    Location,
    PriceSource,
    RouteLeg,
    TripPlan,
    TripPlanRequest,
    WeatherInfo,
)
from src.planning.density import HEAVY_LOAD, attraction_load
from src.planning.must_visit import matches as _same_place
from src.planning.must_visit import normalize as _normalize_place
from src.service.cache import TTLCache
from src.service.logging import log_event
from src.service.qweather import QWeatherService
from src.service.sample_data import city_center, sample_attractions, sample_hotels, sample_weather

logger = logging.getLogger(__name__)

# Candidate depth: page 1 alone caps the pool at ~20 POIs per keyword. A second
# page roughly doubles the pool without touching the 8 s search budget.
MAX_POI_PAGES = 2
POI_PAGE_SIZE = 20
#: Base budget for one keyword sweep. Longer trips need more pages, so the caller
#: scales it up (see `_search_attractions_uncached`); a fixed 8s cut long trips off
#: mid-way and left them with too few candidates to plan.
POI_SEARCH_TIMEOUT_SECONDS = 8.0

# Scenic-ish POI types: 风景名胜 / 公园广场 / 旅游景点 / 科教文化 / 博物馆.
ATTRACTION_TYPES = "110000|110100|110200|140000|140100"
# 购物服务. Fetched only when the user asked to shop: a mall is a destination in
# its own right ("one mall fills half a day"), but it is not a sightseeing stop for
# someone who asked for history.
SHOPPING_TYPES = "060000"
SHOPPING_PREFERENCE_TERMS = ("购物", "逛街", "商场", "购物中心", "买", "市集")
SHOPPING_KEYWORDS = ("购物中心", "商场", "百货", "万达广场", "万象城")
SHOPPING_CATEGORY_TERMS = ("购物中心", "商场", "百货", "商业街")
# Share of the candidate list a shopping stop may take. Without a cap, adding
# malls swapped one monotony for another: a real run returned five malls over three
# days and nothing else.
SHOPPING_CANDIDATE_SHARE = 0.4

#: A pool that is mostly heavy venues cannot produce a good itinerary no matter
#: how well the model chooses. When the user asked for nature or a relaxed pace,
#: a museum-dominated candidate list is topped up with parks instead.
_HEAVY_SHARE_TRIGGER = 0.6
_NATURE_PREFERENCES = ("自然风光", "休闲", "摄影")
_PARK_TYPES = "110100|110101"
_DIVERSITY_TOP_UP = 3


class MustVisitNotFound(Exception):
    """A place the user insists on could not be found in the live data.

    Raised instead of silently returning a plan without it: "I asked for the
    Forbidden City and got a park" is worse than a clear 422.
    """

    def __init__(self, names: list[str]) -> None:
        super().__init__("must-visit place(s) not found: " + ", ".join(names))
        self.names = names


class AMapService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.v3_base_url = "https://restapi.amap.com/v3"
        self.v5_base_url = "https://restapi.amap.com/v5"
        self.qweather = QWeatherService(settings)
        # Sample mode is for tests and offline demos: caching it would only make
        # stale demo data survive longer than it should.
        self._cache = (
            TTLCache(settings.cache_ttl_seconds) if settings.cache_enabled and not settings.use_sample_data else None
        )

    def _cache_get(self, key: tuple) -> Any:
        """Heterogeneous cache (POI lists, route legs): values are callers' own types."""
        return self._cache.get(key) if self._cache is not None else None

    def _cache_set(self, key: tuple, value: Any) -> None:
        if self._cache is not None:
            self._cache.set(key, value)

    async def search_attractions(self, request: TripPlanRequest) -> list[Attraction]:
        cache_key = ("attractions", request.city, request.preferences, request.days, tuple(request.must_visit))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return [item.model_copy(deep=True) for item in cached]
        result = await self._search_attractions_uncached(request)
        self._cache_set(cache_key, result)
        return result

    async def _search_attractions_uncached(self, request: TripPlanRequest) -> list[Attraction]:
        if not self.settings.has_amap:
            return sample_attractions(
                request.city,
                request.preferences,
                count=self._target_attraction_count(request.days),
            )

        pinned = await self._search_must_visit(request)
        if len(pinned) < len(request.must_visit):
            found = "、".join(item.name for item in pinned)
            missing = [name for name in request.must_visit if not any(_same_place(name, item.name) for item in pinned)]
            log_event(
                logger,
                "amap.must_visit_missing",
                level=logging.WARNING,
                city=request.city,
                requested=request.must_visit,
                missing=missing,
                found=found,
            )
            raise MustVisitNotFound(missing)

        target_count = self._target_attraction_count(request.days)
        try:
            pois = await self._search_pois(
                city=request.city,
                keywords=self._build_attraction_keywords(request),
                types=self._attraction_types(request),
                target_count=target_count * 2,
                timeout_seconds=min(POI_SEARCH_TIMEOUT_SECONDS + request.days, 20.0),
            )
        except httpx.HTTPError as exc:
            log_event(
                logger,
                "amap.attraction_search_failed",
                level=logging.WARNING,
                reason=type(exc).__name__,
                city=request.city,
                target_count=target_count,
                error=str(exc),
            )
            return await self._fallback_attractions(request)

        attractions: list[Attraction] = []
        seen_names: set[str] = set()
        allow_shopping = self._wants_shopping(request)
        shopping_cap = self._shopping_cap(target_count) if allow_shopping else 0
        shopping_taken = 0
        for poi in pois:
            if not self._is_attraction_poi(poi, allow_shopping=allow_shopping):
                continue
            name = self._text(poi.get("name"), "未命名景点")
            if self._looks_like_non_attraction_name(name):
                continue
            normalized_name = self._normalize_name(name)
            if normalized_name in seen_names:
                continue
            category = AMapService._poi_category(poi) or "景点"
            if "购物服务" in category:
                # Malls are welcome, but not at the price of an all-mall trip.
                if shopping_taken >= shopping_cap:
                    continue
                shopping_taken += 1
            attraction = self._to_attraction(poi, request)
            if attraction is None:
                continue
            seen_names.add(normalized_name)
            attractions.append(attraction)
            if len(attractions) >= target_count:
                break

        if attractions:
            merged = _merge_by_name(pinned, attractions)
            return await self._top_up_diversity(request, merged)

        if pinned:
            return pinned

        return await self._fallback_attractions(request)

    async def search_by_name(self, name: str, request: TripPlanRequest) -> list[Attraction]:
        """Look up one place by name. The bound on the planner's retrieval retry.

        When the model names a stop the candidate pool did not contain, this is how
        that place can still be fetched instead of the whole trip degrading. It
        returns at most a few matches and never invents one.
        """
        try:
            pois = await self._search_pois(
                city=request.city,
                keywords=[name],
                types=self._attraction_types(request),
                target_count=3,
            )
        except httpx.HTTPError as exc:
            log_event(
                logger,
                "amap.lookup_failed",
                level=logging.DEBUG,
                city=request.city,
                name=name,
                error=str(exc),
            )
            return []
        found: list[Attraction] = []
        for poi in pois:
            if not self._is_attraction_poi(poi, allow_shopping=self._wants_shopping(request)):
                continue
            item = self._to_attraction(poi, request)
            if item is not None:
                found.append(item)
        return found

    async def _search_must_visit(self, request: TripPlanRequest) -> list[Attraction]:
        """Look each must-visit place up by name and keep the best match.

        Searched one name at a time on purpose: the keyword endpoint ranks by
        relevance to the whole query, so batching several place names returns
        results for whichever one the index likes best.
        """
        found: list[Attraction] = []
        for name in request.must_visit:
            try:
                pois = await self._search_pois(
                    city=request.city,
                    keywords=[name],
                    types=self._attraction_types(request),
                    target_count=3,
                )
            except httpx.HTTPError as exc:
                log_event(
                    logger,
                    "amap.must_visit_search_failed",
                    level=logging.WARNING,
                    city=request.city,
                    name=name,
                    error=str(exc),
                )
                continue
            best = self._pick_must_visit(pois, name, request)
            if best is not None:
                found.append(best)
        return found

    def _pick_must_visit(self, pois: list[dict[str, Any]], name: str, request: TripPlanRequest) -> Attraction | None:
        """The POI that *is* the place asked for, never merely a search hit.

        A near-miss is not good enough here: "I asked for the museum and got a
        shopping street" is exactly the failure a must-visit list exists to
        prevent, so a non-matching result is treated as "not found" (422) rather
        than silently substituted.
        """
        fallback: Attraction | None = None
        for poi in pois:
            if not self._is_attraction_poi(poi, allow_shopping=self._wants_shopping(request)):
                continue
            item = self._to_attraction(poi, request)
            if item is None:
                continue
            if not _same_place(name, item.name):
                continue
            if self._normalize_name(name) == self._normalize_name(item.name):
                return item
            fallback = fallback or item
        return fallback

    def _to_attraction(self, poi: dict[str, Any], request: TripPlanRequest) -> Attraction | None:
        """Map one AMap POI to an :class:`Attraction`, or ``None`` if it is unusable.

        Kept separate from the search loop so the diversity top-up below builds
        records the same way instead of duplicating forty field mappings.
        """
        name = self._text(poi.get("name"), "未命名景点")
        location = self._poi_location(poi)
        if not name or location is None:
            return None
        category = AMapService._poi_category(poi) or "景点"
        ticket_price, price_source = self._ticket_price(category)
        return Attraction(
            name=name,
            address=self._poi_address(poi, request.city),
            location=location,
            visit_duration=self._estimate_visit_duration(category, name),
            description=self._poi_description(name, request.city, request.preferences, category),
            category=category,
            rating=self._poi_rating(poi),
            image_url=self._poi_photo(poi),
            ticket_price=ticket_price,
            price_source=price_source,
            opening_hours=self._opening_hours(poi),
            contact_phone=self._poi_phone(poi),
            level=self._poi_level(poi),
            source="amap",
        )

    async def _top_up_diversity(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
    ) -> list[Attraction]:
        """Add a few light stops when the pool is dominated by heavy venues.

        This does not second-guess the model: it only makes sure the pool contains
        the kind of place the user asked for. A city whose first keyword happens to
        be "博物馆" otherwise offers nothing but museums, and no amount of clever
        choosing fixes a candidate set that contains no parks.
        """
        if len(attractions) < 3:
            return attractions
        heavy = sum(1 for item in attractions if attraction_load(item) >= HEAVY_LOAD)
        if heavy / len(attractions) <= _HEAVY_SHARE_TRIGGER:
            return attractions
        if not any(term in request.preferences for term in _NATURE_PREFERENCES):
            return attractions

        try:
            pois = await self._search_pois(
                city=request.city,
                keywords=["公园", "湖"],
                types=_PARK_TYPES,
                target_count=_DIVERSITY_TOP_UP * 2,
            )
        except httpx.HTTPError as exc:
            log_event(
                logger,
                "amap.diversity_top_up_failed",
                level=logging.DEBUG,
                reason=type(exc).__name__,
                city=request.city,
                error=str(exc),
            )
            return attractions

        seen = {self._normalize_name(item.name) for item in attractions}
        added = 0
        for poi in pois:
            if not self._is_attraction_poi(poi):
                continue
            item = self._to_attraction(poi, request)
            if item is None:
                continue
            key = self._normalize_name(item.name)
            if key in seen:
                continue
            seen.add(key)
            attractions.append(item)
            added += 1
            if added >= _DIVERSITY_TOP_UP:
                break

        if added:
            log_event(
                logger,
                "amap.diversity_top_up",
                city=request.city,
                heavy=heavy,
                total_before=len(attractions) - added,
                added=added,
            )
        return attractions

    async def search_hotels(self, request: TripPlanRequest) -> list[Hotel]:
        cache_key = ("hotels", request.city, request.accommodation, request.budget)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return [item.model_copy(deep=True) for item in cached]
        result = await self._search_hotels_uncached(request)
        self._cache_set(cache_key, result)
        return result

    async def _search_hotels_uncached(self, request: TripPlanRequest) -> list[Hotel]:
        if not self.settings.has_amap:
            return sample_hotels(request.city, request.accommodation, request.budget)

        try:
            pois = await self._search_pois(
                city=request.city,
                keywords=self._build_hotel_keywords(request),
                types="100000|100100|100101|100102|100105",
                target_count=8,
            )
        except httpx.HTTPError as exc:
            log_event(
                logger,
                "amap.hotel_search_failed",
                level=logging.WARNING,
                reason=type(exc).__name__,
                city=request.city,
                error=str(exc),
            )
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
            nightly, price_source = self._hotel_cost(request.budget, request.accommodation, poi)
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
                    price_source=price_source,
                    source="amap",
                )
            )
            if len(hotels) >= 6:
                break

        return hotels or sample_hotels(request.city, request.accommodation, request.budget)

    async def query_weather(self, request: TripPlanRequest) -> list[WeatherInfo]:
        cache_key = ("weather", request.city, request.start_date.isoformat(), request.days)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return [item.model_copy(deep=True) for item in cached]
        result = await self._query_weather_uncached(request)
        self._cache_set(cache_key, result)
        return result

    async def _query_weather_uncached(self, request: TripPlanRequest) -> list[WeatherInfo]:
        if self.settings.use_sample_data:
            return sample_weather(request.start_date.isoformat(), request.days)
        location = city_center(request.city)
        if self.settings.has_amap:
            try:
                location = await self._city_location(request.city) or location
            except httpx.HTTPError as exc:
                log_event(
                    logger,
                    "amap.city_location_failed",
                    level=logging.DEBUG,
                    reason=type(exc).__name__,
                    city=request.city,
                )
        if self.settings.has_qweather:
            # Better precision over China; falls back to Open-Meteo when it
            # cannot cover every requested date.
            qweather = await self.qweather.daily_forecast(request, location)
            if qweather is not None:
                return qweather

        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,wind_direction_10m_dominant",
            "timezone": "Asia/Shanghai",
            "start_date": request.start_date.isoformat(),
            "end_date": request.resolved_end_date.isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                response.raise_for_status()
                daily = response.json().get("daily") or {}
            dates = daily.get("time") or []
            codes = daily.get("weather_code") or []
            high = daily.get("temperature_2m_max") or []
            low = daily.get("temperature_2m_min") or []
            speed = daily.get("wind_speed_10m_max") or []
            direction = daily.get("wind_direction_10m_dominant") or []
            values = (dates, codes, high, low, speed, direction)
            if not all(len(value) == request.days for value in values):
                raise ValueError("incomplete forecast")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            log_event(
                logger,
                "weather.unavailable",
                level=logging.WARNING,
                reason=type(exc).__name__,
                city=request.city,
                start_date=request.start_date.isoformat(),
                days=request.days,
                error=str(exc),
            )
            return self._unavailable_weather_range(request, None)
        weather_map = {
            0: "\u6674",
            1: "\u5927\u90e8\u6674\u6717",
            2: "\u591a\u4e91",
            3: "\u9634",
            45: "\u96fe",
            48: "\u51bb\u96fe",
            51: "\u6bdb\u6bdb\u96e8",
            53: "\u5c0f\u96e8",
            55: "\u5bc6\u96e8",
            61: "\u5c0f\u96e8",
            63: "\u4e2d\u96e8",
            65: "\u5927\u96e8",
            71: "\u5c0f\u96ea",
            73: "\u4e2d\u96ea",
            75: "\u5927\u96ea",
            80: "\u9635\u96e8",
            81: "\u5f3a\u9635\u96e8",
            82: "\u66b4\u96e8",
            95: "\u96f7\u66b4\u96e8",
        }
        directions = (
            "\u5317",
            "\u4e1c\u5317",
            "\u4e1c",
            "\u4e1c\u5357",
            "\u5357",
            "\u897f\u5357",
            "\u897f",
            "\u897f\u5317",
        )
        return [
            WeatherInfo(
                date=str(dates[index]),
                day_weather=self._weather_text(weather_map, codes[index]),
                night_weather=self._weather_text(weather_map, codes[index]),
                day_temp=round(float(high[index])),
                night_temp=round(float(low[index])),
                wind_direction=directions[round((self._to_int(direction[index]) or 0) / 45) % 8],
                wind_power=f"{round(float(speed[index]))} km/h",
                notice="\u5929\u6c14\u7531 Open-Meteo \u9884\u62a5\u670d\u52a1\u63d0\u4f9b\u3002",
                source="open_meteo",
            )
            for index in range(request.days)
        ]

    async def enrich_daily_routes(
        self,
        plan: TripPlan,
        request: TripPlanRequest,
        day_indexes: set[int] | None = None,
    ) -> TripPlan:
        """Fill in route legs. Passing ``day_indexes`` recalculates only those days.

        A day whose stops changed after the first pass (the load trim can drop
        one) must be recalculated, or its route list keeps pointing at a stop that
        is no longer in the plan.
        """
        route_tasks: list[tuple[DayPlan, list[asyncio.Task[RouteLeg]]]] = []
        for day in plan.days:
            if day_indexes is not None and day.day_index not in day_indexes:
                continue
            route_points: list[tuple[str, Location]] = []
            if day.hotel and day.hotel.location:
                route_points.append((day.hotel.name, day.hotel.location))
            route_points.extend((item.name, item.location) for item in day.attractions)
            if len(route_points) < 2:
                day.routes = []
                continue

            route_tasks.append(
                (
                    day,
                    [
                        asyncio.create_task(
                            self.estimate_route(
                                origin_name=origin_name,
                                origin=origin,
                                destination_name=destination_name,
                                destination=destination,
                                request=request,
                            )
                        )
                        for (origin_name, origin), (destination_name, destination) in zip(
                            route_points, route_points[1:], strict=False
                        )
                    ],
                )
            )
        for day, tasks in route_tasks:
            day.routes = list(await asyncio.gather(*tasks))
        return plan

    async def estimate_route(
        self,
        origin_name: str,
        origin: Location,
        destination_name: str,
        destination: Location,
        request: TripPlanRequest,
    ) -> RouteLeg:
        cache_key = (
            "route",
            round(origin.longitude, 4),
            round(origin.latitude, 4),
            round(destination.longitude, 4),
            round(destination.latitude, 4),
            request.transportation,
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return RouteLeg.model_validate(cached)
        leg = await self._estimate_route_uncached(origin_name, origin, destination_name, destination, request)
        self._cache_set(cache_key, leg.model_dump())
        return leg

    async def _estimate_route_uncached(
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
        except httpx.HTTPError as exc:
            log_event(
                logger,
                "amap.route_failed",
                level=logging.DEBUG,
                reason=type(exc).__name__,
                mode=mode,
                origin=origin_name,
                destination=destination_name,
            )
            parsed = None

        if parsed is None:
            return self._haversine_route(origin_name, origin, destination_name, destination, request.transportation)
        distance, duration = parsed
        if duration <= 0:
            # The API gave a distance but no duration; estimate the time from
            # that distance rather than reporting the default 1 minute.
            estimated = self._haversine_route(
                origin_name, origin, destination_name, destination, request.transportation
            )
            duration = estimated.duration_minutes
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
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        pois: list[dict[str, Any]] = []
        seen: set[str] = set()
        keyword_list = list(keywords)
        # Breadth before depth. Without a per-keyword slice the first keyword fills
        # the target by itself and the rest are never searched - which is how a
        # shopping trip came back with nothing but malls.
        per_keyword = max(3, -(-target_count // max(1, len(keyword_list))))
        budget = POI_SEARCH_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        try:
            async with asyncio.timeout(budget):
                for keyword in keyword_list:
                    from_keyword = 0
                    page = 1
                    while page <= MAX_POI_PAGES:
                        results: list[dict[str, Any]] = []
                        for search in (self._search_pois_v5, self._search_pois_v3):
                            try:
                                results = await search(city, keyword, types, page=page)
                            except httpx.HTTPError as exc:
                                log_event(
                                    logger,
                                    "amap.poi_search_failed",
                                    level=logging.DEBUG,
                                    reason=type(exc).__name__,
                                    endpoint=search.__name__,
                                    city=city,
                                    keyword=keyword,
                                    page=page,
                                )
                                continue
                            if results:
                                break
                        if not results:
                            break
                        for poi in results:
                            name = self._text(poi.get("name"), "")
                            identity = f"{self._normalize_name(name)}|{self._text(poi.get('location'), '')}"
                            if not name or identity in seen:
                                continue
                            seen.add(identity)
                            pois.append(poi)
                            from_keyword += 1
                            if len(pois) >= target_count:
                                return pois
                            if from_keyword >= per_keyword:
                                break
                        if from_keyword >= per_keyword or len(results) < POI_PAGE_SIZE:
                            break
                        page += 1
        except TimeoutError:
            log_event(
                logger,
                "amap.search_timeout",
                level=logging.WARNING,
                reason="timeout",
                city=city,
                collected=len(pois),
                target_count=target_count,
            )
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

    async def _fallback_attractions(self, request: TripPlanRequest) -> list[Attraction]:
        center = None
        if self.settings.has_amap:
            try:
                center = await self._city_location(request.city)
            except httpx.HTTPError as exc:
                log_event(
                    logger,
                    "amap.fallback_center_failed",
                    level=logging.DEBUG,
                    reason=type(exc).__name__,
                    city=request.city,
                )
                center = None
        return sample_attractions(
            request.city,
            request.preferences,
            center=center,
            count=self._target_attraction_count(request.days),
        )

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
        async with httpx.AsyncClient(timeout=5) as client:
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
            notice = f"行程日期超过天气预报最晚日期 {latest_forecast_date}，无法保证查询天气。"
        else:
            notice = "暂时无法获取天气预报，无法保证查询天气。"
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
            source="unavailable",
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
        preference_keywords = [
            f"{request.city} {part}" for part in preference_parts if not AMapService._is_meal_preference(part)
        ]
        keywords = [*preference_keywords, *base_keywords]
        if AMapService._wants_shopping(request):
            # "贵阳 购物" matches shops, not malls; these are the names a shopper
            # actually searches for, and a mall comes back as one POI.
            keywords.extend(f"{request.city} {term}" for term in SHOPPING_KEYWORDS)
        return list(dict.fromkeys(keywords))

    @staticmethod
    def _shopping_cap(target_count: int) -> int:
        """How many shopping stops the candidate list may contain."""
        return max(1, round(target_count * SHOPPING_CANDIDATE_SHARE))

    @staticmethod
    def _wants_shopping(request: TripPlanRequest) -> bool:
        return any(term in request.preferences for term in SHOPPING_PREFERENCE_TERMS)

    @staticmethod
    def _attraction_types(request: TripPlanRequest) -> str:
        """POI types to search, widened to shopping only when the user asked for it."""
        if AMapService._wants_shopping(request):
            return f"{ATTRACTION_TYPES}|{SHOPPING_TYPES}"
        return ATTRACTION_TYPES

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
    def _target_attraction_count(days: int) -> int:
        """How many candidates a trip of this length needs.

        The old ceiling of 16 was fine for a 3-day trip and starving for a 14-day
        one: with fewer candidates than days, the model has to invent a place or
        repeat one, and the validator rejects both - so the trip degraded to the
        rule engine. Three per day, capped where the extra pages stop paying off.
        """
        return max(8, min(45, days * 3))

    @staticmethod
    def _is_meal_preference(preference: str) -> bool:
        return any(keyword in preference for keyword in ("美食", "餐饮", "小吃", "探店"))

    @staticmethod
    def _normalize_name(name: str) -> str:
        return "".join(name.lower().split())

    @staticmethod
    def _is_attraction_poi(poi: dict[str, Any], allow_shopping: bool = False) -> bool:
        """Whether a POI may be offered as a stop.

        ``allow_shopping`` is off unless the user asked to shop: a mall can fill
        half a day, but only if that is what the trip is about. Supermarkets and
        single shops stay out either way - the category has to name a mall, a
        department store or a commercial street.
        """
        category = AMapService._poi_category(poi)
        forbidden_categories = (
            "餐饮服务",
            "住宿服务",
            "生活服务",
            "商务住宅",
            "公司企业",
            "学校",
            "培训",
        )
        if any(item in category for item in forbidden_categories):
            return False

        if "购物服务" in category:
            return allow_shopping and any(item in category for item in SHOPPING_CATEGORY_TERMS)

        attraction_categories = ("风景名胜", "公园广场", "博物馆", "美术馆", "展览馆", "纪念馆", "图书馆")
        return any(item in category for item in attraction_categories)

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
    def _opening_hours(poi: dict[str, Any]) -> str | None:
        """Raw opening-hours text from AMap, kept as-is so the UI can show the source."""
        business = AMapService._biz_ext(poi)
        for key in ("opentime_week", "opentime_today", "open_time", "opentime"):
            value = business.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _poi_photo(poi: dict[str, Any]) -> str | None:
        photos = poi.get("photos")
        if not isinstance(photos, list):
            return None
        for photo in photos:
            if isinstance(photo, dict):
                url = photo.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
        return None

    @staticmethod
    def _poi_phone(poi: dict[str, Any]) -> str | None:
        tel = AMapService._biz_ext(poi).get("tel")
        if isinstance(tel, str):
            cleaned = tel.strip()
            if cleaned and cleaned != "[]":
                return cleaned
        return None

    @staticmethod
    def _poi_level(poi: dict[str, Any]) -> str | None:
        business = AMapService._biz_ext(poi)
        keytag = business.get("keytag")
        if isinstance(keytag, str) and any(mark in keytag for mark in ("A级", "景区", "5A", "4A", "3A")):
            return keytag.strip()
        level = business.get("level")
        if isinstance(level, str) and level.strip():
            return level.strip()
        return None

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
        if not isinstance(value, (int, float, str)):
            return None
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        return rating if 0 <= rating <= 5 else None

    def _weather_text(self, weather_map: dict[int, str], value: object) -> str:
        """Map an Open-Meteo weather code to Chinese; an unknown code stays unknown."""
        code = self._to_int(value)
        if code is None:
            return "\u5929\u6c14\u5f85\u5b9a"
        return weather_map.get(code, "\u5929\u6c14\u5f85\u5b9a")

    @staticmethod
    def _ticket_price(category: str) -> tuple[int, PriceSource]:
        """Return (price, price_source). Never invent a price we cannot justify."""
        if not category or category == "景点":
            return 0, "unknown"
        if any(keyword in category for keyword in ("博物馆", "美术馆", "展览馆", "科技馆")):
            return 50, "estimated"
        if any(keyword in category for keyword in ("风景", "公园", "广场")):
            return 30, "estimated"
        if any(keyword in category for keyword in ("纪念", "寺", "塔", "古镇")):
            return 60, "estimated"
        return 0, "unknown"

    @staticmethod
    def _estimate_visit_duration(category: str, name: str) -> int:
        # A mall is a half-day in itself: shops, food, cinema, all under one roof.
        if any(item in category for item in SHOPPING_CATEGORY_TERMS) or "万达" in name:
            return 150
        if "博物馆" in category or "艺术" in name:
            return 120
        if "公园" in category or "风景" in category:
            return 100
        return 90

    @staticmethod
    def _estimate_hotel_cost(budget: str, accommodation: str, poi: dict[str, Any]) -> int:
        business_cost = AMapService._to_int(AMapService._biz_ext(poi).get("cost"))
        if business_cost:
            return business_cost
        costs = {
            "\u9752\u5e74\u65c5\u820d": 120,
            "\u7ecf\u6d4e\u578b\u9152\u5e97": 280,
            "\u8212\u9002\u578b\u9152\u5e97": 520,
            "\u9ad8\u7aef\u9152\u5e97": 980,
        }
        return costs.get(
            accommodation,
            {"\u7ecf\u6d4e": 260, "\u4e2d\u7b49": 460, "\u8212\u9002": 720, "\u8c6a\u534e": 980}.get(budget, 460),
        )

    @staticmethod
    def _hotel_cost(budget: str, accommodation: str, poi: dict[str, Any]) -> tuple[int, PriceSource]:
        business_cost = AMapService._to_int(AMapService._biz_ext(poi).get("cost"))
        if business_cost:
            return business_cost, "api"
        return AMapService._estimate_hotel_cost(budget, accommodation, {}), "estimated"

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
        if duration <= 0:
            # Driving directions answer with `distance` and `steps`, but no
            # `duration` at the path level - reporting the missing value as a
            # duration turned every leg into "1 分钟". Fall back to a speed
            # estimate instead, and say so by returning None for the caller.
            return distance, 0
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


def _merge_by_name(primary: list[Attraction], secondary: list[Attraction]) -> list[Attraction]:
    """Primary first (must-visit places), then secondary minus anything already there."""
    merged = list(primary)
    seen = {_normalize_place(item.name) for item in primary}
    for item in secondary:
        key = _normalize_place(item.name)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
