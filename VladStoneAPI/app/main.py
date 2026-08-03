import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.request_limits import RequestBodyLimitMiddleware
from app.api.routes import auth, combat, health, me, telemetry, ws
from app.core.config import get_settings
from app.db.session import init_db
from app.services.combat_timer_worker import run_combat_timer_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    timer_task = asyncio.create_task(run_combat_timer_worker())
    try:
        yield
    finally:
        timer_task.cancel()
        with suppress(asyncio.CancelledError):
            await timer_task


def create_app() -> FastAPI:
    settings = get_settings()
    init_db()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):5173",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestBodyLimitMiddleware)
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(me.router, prefix=settings.api_prefix)
    app.include_router(combat.router, prefix=settings.api_prefix)
    app.include_router(telemetry.router, prefix=settings.api_prefix)
    app.include_router(ws.router)
    return app


app = create_app()
