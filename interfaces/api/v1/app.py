from fastapi import FastAPI
from interfaces.api.v1.routes import router as v1_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Binary Options Trading Bot API",
        version="1.0.0",
    )
    app.include_router(v1_router, prefix="/api/v1")
    return app
