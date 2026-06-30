import uvicorn

from app.Config import settings


if __name__ == "__main__":
    port = settings.api_port
    host = settings.api_host
    if settings.app_env != "development" and host in {"127.0.0.1", "localhost"}:
        host = "0.0.0.0"
    uvicorn.run(
        "app.api.Main:app",
        host=host,
        port=port,
        reload=settings.app_env == "development",
    )
