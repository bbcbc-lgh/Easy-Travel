import asyncio
from datetime import date

from src.config import Settings
from src.model.schemas import Location, TripPlanRequest
from src.service.amap import AMapService
from src.service.qweather import QWeatherService

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def request(days: int = 3) -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 20),
        days=days,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def qweather_payload(dates: list[str]) -> dict:
    return {
        "code": "200",
        "daily": [
            {
                "fxDate": day,
                "textDay": "晴",
                "textNight": "多云",
                "tempMax": "18",
                "tempMin": "9",
                "windDirDay": "西北风",
                "windScaleDay": "3-4",
            }
            for day in dates
        ],
    }


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self, payload: dict, calls: list) -> None:
        self.payload = payload
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self.payload)


def test_qweather_maps_daily_forecast(monkeypatch) -> None:
    service = QWeatherService(Settings(qweather_api_key="key"))
    calls: list = []
    payload = qweather_payload(["2026-11-20", "2026-11-21", "2026-11-22"])
    monkeypatch.setattr(
        "src.service.qweather.httpx.AsyncClient",
        lambda **kwargs: FakeClient(payload, calls),
    )

    weather = asyncio.run(service.daily_forecast(request(3), HANGZHOU))

    assert weather is not None
    assert [item.source for item in weather] == ["qweather"] * 3
    assert weather[0].day_weather == "晴"
    assert weather[0].day_temp == 18
    assert weather[0].night_temp == 9
    assert "和风天气" in (weather[0].notice or "")
    assert calls and calls[0][1]["location"].startswith("120.1550,30.2740")


def test_qweather_returns_none_when_dates_are_not_covered(monkeypatch) -> None:
    service = QWeatherService(Settings(qweather_api_key="key"))
    payload = qweather_payload(["2026-11-20"])  # only one of three days
    monkeypatch.setattr(
        "src.service.qweather.httpx.AsyncClient",
        lambda **kwargs: FakeClient(payload, []),
    )

    assert asyncio.run(service.daily_forecast(request(3), HANGZHOU)) is None


def test_qweather_is_disabled_without_a_key() -> None:
    service = QWeatherService(Settings(qweather_api_key=""))

    assert service.enabled is False
    assert asyncio.run(service.daily_forecast(request(), HANGZHOU)) is None


def test_weather_prefers_qweather_when_enabled(monkeypatch) -> None:
    amap = AMapService(Settings(qweather_api_key="key", amap_web_service_key="k"))
    seen: list[str] = []

    async def fake_qweather(req, location):
        seen.append("qweather")
        return await QWeatherService(Settings(qweather_api_key="key")).daily_forecast(req, location)

    payload = qweather_payload(["2026-11-20", "2026-11-21", "2026-11-22"])
    monkeypatch.setattr(
        "src.service.qweather.httpx.AsyncClient",
        lambda **kwargs: FakeClient(payload, []),
    )
    monkeypatch.setattr(amap.qweather, "daily_forecast", fake_qweather)

    weather = asyncio.run(amap.query_weather(request(3)))

    assert seen == ["qweather"]
    assert weather and weather[0].source == "qweather"


def test_weather_falls_back_to_open_meteo(monkeypatch) -> None:
    amap = AMapService(Settings(qweather_api_key="key", amap_web_service_key="k"))
    open_meteo = {
        "daily": {
            "time": ["2026-11-20", "2026-11-21", "2026-11-22"],
            "weather_code": [0, 2, 61],
            "temperature_2m_max": [18.0, 17.0, 15.0],
            "temperature_2m_min": [9.0, 8.0, 7.0],
            "wind_speed_10m_max": [10.0, 12.0, 9.0],
            "wind_direction_10m_dominant": [90.0, 180.0, 270.0],
        }
    }

    async def no_qweather(req, location):
        return None

    monkeypatch.setattr(amap.qweather, "daily_forecast", no_qweather)
    monkeypatch.setattr(
        "src.service.amap.httpx.AsyncClient",
        lambda **kwargs: FakeClient(open_meteo, []),
    )

    weather = asyncio.run(amap.query_weather(request(3)))

    assert weather and all(item.source == "open_meteo" for item in weather)
