"""QWeather (和风天气) daily forecast provider.

Open-Meteo works everywhere but is noticeably less precise over China and offers
no severe-weather alerts. QWeather is the better source there; it is activated
only when ``QWEATHER_API_KEY`` is configured, and any failure (including a date
range it cannot cover) returns ``None`` so the caller keeps Open-Meteo as the
fallback.

QWeather issues a *per-account* API host (e.g. ``abc123.re.qweatherapi.com``).
Using the legacy ``devapi.qweather.com`` with a new key returns
``403 Invalid Host``; ``QWEATHER_HOST`` must be the host shown in the console.
"""

import logging
from datetime import timedelta

import httpx

from src.config import Settings
from src.model.schemas import Location, TripPlanRequest, WeatherInfo

logger = logging.getLogger(__name__)


class QWeatherService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.host = settings.qweather_host

    @property
    def enabled(self) -> bool:
        return bool(self.settings.qweather_api_key) and not self.settings.use_sample_data

    async def daily_forecast(
        self,
        request: TripPlanRequest,
        location: Location,
    ) -> list[WeatherInfo] | None:
        if not self.enabled:
            return None

        params = {
            "location": f"{location.longitude:.4f},{location.latitude:.4f}",
            "key": self.settings.qweather_api_key,
            "lang": "zh",
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"https://{self.host}/v7/weather/7d", params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            # Never log str(exc): httpx embeds the full URL, which carries the key.
            status_code = exc.response.status_code
            if status_code == 403:
                logger.warning(
                    "qweather rejected the API host %r: set QWEATHER_HOST to the "
                    "per-account host shown in the QWeather console",
                    self.host,
                )
            else:
                logger.warning("qweather http %s", status_code)
            return None
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("qweather request failed: %s", type(exc).__name__)
            return None

        if str(payload.get("code")) != "200":
            logger.warning("qweather returned code %s", payload.get("code"))
            return None

        by_date = {str(item.get("fxDate")): item for item in payload.get("daily") or []}
        dates = [(request.start_date + timedelta(days=index)) for index in range(request.days)]
        # Partial coverage is worse than a consistent source: let the caller fall back.
        if any(item.isoformat() not in by_date for item in dates):
            return None

        weather: list[WeatherInfo] = []
        for current in dates:
            item = by_date[current.isoformat()]
            weather.append(
                WeatherInfo(
                    date=current.isoformat(),
                    day_weather=str(item.get("textDay") or "天气待定"),
                    night_weather=str(item.get("textNight") or "天气待定"),
                    day_temp=self._temp(item.get("tempMax")),
                    night_temp=self._temp(item.get("tempMin")),
                    wind_direction=str(item.get("windDirDay") or "未知"),
                    wind_power=str(item.get("windScaleDay") or "未知"),
                    notice="天气由和风天气预报服务提供。",
                    source="qweather",
                )
            )
        return weather

    @staticmethod
    def _temp(value: object) -> int:
        try:
            return round(float(str(value)))
        except (TypeError, ValueError):
            return 0
