from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    app_name: str = "EasyTravel"
    app_env: str = "development"
    api_host: str = Field("127.0.0.1", validation_alias="FASTAPI_API_HOST")
    api_port: int = Field(8000, validation_alias="FASTAPI_API_PORT")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "gpt-4o-mini"

    amap_web_service_key: str = Field("", validation_alias="FASTAPI_AMAP_WEB_KEY")
    use_sample_data: bool = False

    database_path: str = "data/easy_travel.sqlite3"

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
