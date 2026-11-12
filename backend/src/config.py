from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.model.llm_profile import ModelProfile
from src.service.logging import mask_secret

#: One `.env` for the whole project, at the repository root. The backend reads it
#: here; the frontend reads the same file through Vite's `envDir`. Keeping a single
#: file avoids the failure this project actually hit: a key edited in one copy and
#: silently ignored because the running process read the other.
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "EasyTravel"
    app_env: str = "development"
    api_host: str = Field(default="127.0.0.1", validation_alias="FASTAPI_API_HOST")
    api_port: int = Field(default=8000, validation_alias="FASTAPI_API_PORT")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 0
    llm_reasoning_effort: str = ""
    llm_total_budget_seconds: float = 150.0
    llm_profiles: list[ModelProfile] = Field(default_factory=list)

    # Every backend variable carries the FASTAPI_ prefix, so a single `.env` can
    # hold the frontend's VITE_* keys too without the two sets colliding.
    amap_web_service_key: str = Field(
        default="",
        validation_alias=AliasChoices("FASTAPI_AMAP_WEB_KEY", "AMAP_WEB_KEY"),
    )
    use_sample_data: bool = False

    qweather_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FASTAPI_QWEATHER_API_KEY", "QWEATHER_API_KEY"),
    )
    qweather_host: str = Field(
        default="devapi.qweather.com",
        validation_alias=AliasChoices("FASTAPI_QWEATHER_HOST", "QWEATHER_HOST"),
    )

    database_path: str = "data/easy_travel.sqlite3"

    # Local cost protection, not a product quota: it only guards the API keys the
    # user put in `.env` against an accidental loop.
    plan_daily_limit: int = 20
    plan_max_concurrency: int = 2
    plan_queue_timeout_seconds: float = 8.0
    plan_max_revisions: int = 1

    cache_enabled: bool = True
    cache_ttl_seconds: int = 600

    log_level: str = "INFO"
    log_format: str = "text"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # Fields with a validation_alias (AMAP_WEB_KEY, FASTAPI_API_HOST, ...)
        # must also accept their field name, otherwise `Settings(amap_web_service_key=...)`
        # is silently ignored and tests only pass when a local .env exists.
        populate_by_name=True,
    )

    @computed_field
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key) and not self.use_sample_data

    @property
    def has_amap(self) -> bool:
        return bool(self.amap_web_service_key) and not self.use_sample_data

    @property
    def has_qweather(self) -> bool:
        return bool(self.qweather_api_key) and not self.use_sample_data

    @property
    def model_profiles(self) -> list[ModelProfile]:
        """Configured profiles, or a single one derived from the legacy flat settings."""
        if self.llm_profiles:
            return list(self.llm_profiles)
        return [
            ModelProfile(
                name=self.llm_model,
                tier="primary",
                base_url=self.llm_base_url or None,
                api_key=self.llm_api_key or None,
                timeout_seconds=self.llm_timeout_seconds,
                max_tokens=self.llm_max_tokens,
                supports_reasoning_effort=bool(self.llm_reasoning_effort),
                reasoning_effort=self.llm_reasoning_effort or None,
            )
        ]

    def describe(self) -> dict[str, Any]:
        """Flat, secret-free summary of the configuration actually in effect."""
        key = mask_secret(self.llm_api_key)
        amap = mask_secret(self.amap_web_service_key)
        profiles = " > ".join(
            f"{profile.name}(tier={profile.tier},timeout={profile.timeout_seconds}s,"
            f"max_tokens={profile.max_tokens or 'default'},retries={profile.max_retries},"
            f"reasoning_effort={profile.reasoning_effort or 'default'})"
            for profile in self.model_profiles
        )
        return {
            "app_name": self.app_name,
            "app_env": self.app_env,
            "llm.enabled": self.has_llm,
            "llm.profiles": profiles,
            "llm.total_budget_seconds": self.llm_total_budget_seconds,
            "llm.api_key_set": key["set"],
            "llm.api_key_length": key["length"],
            "amap.enabled": self.has_amap,
            "amap.web_key_set": amap["set"],
            "qweather.enabled": self.has_qweather,
            "qweather.host": self.qweather_host,
            "sample_data": self.use_sample_data,
            "database_path": self.database_path,
            # "cost_guard" rather than "limits": this protects the user's own API
            # keys, it is not a product-level quota.
            "cost_guard.daily": self.plan_daily_limit,
            "cost_guard.max_concurrency": self.plan_max_concurrency,
            "cost_guard.queue_timeout_seconds": self.plan_queue_timeout_seconds,
            "quality.max_revisions": self.plan_max_revisions,
            "cache.enabled": self.cache_enabled,
            "cache.ttl_seconds": self.cache_ttl_seconds,
            "cors_origins": self.cors_origin_list,
            "log_level": self.log_level,
            "log_format": self.log_format,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
