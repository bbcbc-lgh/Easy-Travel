import os

import uvicorn

from app.config import settings


if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.api_port))
    host = "0.0.0.0" if "PORT" in os.environ else settings.api_host
    uvicorn.run(
        "app.api.main:app",
        host=host,
        port=port,
        reload=settings.app_env == "development",
    )
