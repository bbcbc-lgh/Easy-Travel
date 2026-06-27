import httpx

from app.config import Settings
from app.models.schemas import Attraction


class UnsplashService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def enrich_images(self, city: str, attractions: list[Attraction]) -> list[Attraction]:
        if not self.settings.has_unsplash:
            for attraction in attractions:
                attraction.image_url = self._fallback_image(city)
            return attractions

        async with httpx.AsyncClient(timeout=12) as client:
            for attraction in attractions:
                params = {
                    "query": f"{city} {attraction.name} travel",
                    "per_page": 1,
                    "orientation": "landscape",
                    "client_id": self.settings.unsplash_access_key,
                }
                try:
                    response = await client.get("https://api.unsplash.com/search/photos", params=params)
                    response.raise_for_status()
                    results = response.json().get("results") or []
                    attraction.image_url = (
                        results[0].get("urls", {}).get("regular") if results else self._fallback_image(city)
                    )
                except httpx.HTTPError:
                    attraction.image_url = self._fallback_image(city)
        return attractions

    @staticmethod
    def _fallback_image(city: str) -> str:
        return f"https://source.unsplash.com/1200x800/?{city},travel"
