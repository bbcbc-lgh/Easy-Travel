import httpx

from app.config import Settings
from app.models.schemas import Attraction
from app.services.sample_data import FALLBACK_IMAGES


class UnsplashService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def enrich_images(self, city: str, attractions: list[Attraction]) -> list[Attraction]:
        if not self.settings.has_unsplash:
            for attraction in attractions:
                attraction.image_url = attraction.image_url or self._fallback_image(attraction.name)
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
                    attraction.image_url = results[0].get("urls", {}).get("regular") if results else self._fallback_image(attraction.name)
                except httpx.HTTPError:
                    attraction.image_url = self._fallback_image(attraction.name)
        return attractions

    @staticmethod
    def _fallback_image(seed: str) -> str:
        index = sum(ord(char) for char in seed) % len(FALLBACK_IMAGES)
        return FALLBACK_IMAGES[index]
