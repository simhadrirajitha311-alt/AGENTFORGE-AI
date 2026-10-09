from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import get_settings
from app.logging_config import configure_logging
from app.storage import Store

configure_logging()


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    application.state.store = Store(settings.database_path)
    try:
        yield
    finally:
        application.state.store.close()


app = FastAPI(title="AgentForge AI", version="0.1.0", lifespan=lifespan)


def store_for(application: FastAPI | None = None) -> Store:
    target = application or app
    if not hasattr(target.state, "store"):
        target.state.store = Store(get_settings().database_path)
    return target.state.store


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
def ready() -> dict[str, str]:
    with store_for().connect() as connection:
        connection.execute("SELECT 1")
    return {"status": "ready", "database": "ok"}


app.include_router(router)
