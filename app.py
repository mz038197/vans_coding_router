from contextlib import asynccontextmanager
import asyncio
import os

from fastapi import FastAPI

from src.bootstrap import build_container
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from src.presentation.fastapi.routers.portal_router import create_portal_router
from src.infrastructure.jobs.log_archive_job import run_daily_archive_job

REQUEST_TIMEOUT = 900.0

container = build_container(
    request_timeout=REQUEST_TIMEOUT,
    config_path=os.getenv("VCR_CONFIG"),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    archive_stop_event = asyncio.Event()
    archive_task = None
    if container.archive_repo is not None:
        archive_task = asyncio.create_task(
            run_daily_archive_job(
                container.archive_repo,
                container.prompt_log_retention_days,
                archive_stop_event,
            )
        )
    await container.llm_gateway.startup()
    try:
        yield
    finally:
        archive_stop_event.set()
        if archive_task is not None:
            archive_task.cancel()
        await container.llm_gateway.shutdown()


app = FastAPI(title="Vans Coding Router", lifespan=lifespan)

# Error handlers
register_error_handlers(app)

# Middleware
app.add_middleware(ApiKeyMiddleware, auth_use_case=container.auth_use_case)

# Routers
app.include_router(create_api_router(container.api_use_case))
if container.portal_use_case is not None and container.router_settings is not None:
    app.include_router(create_portal_router(container.portal_use_case, container.router_settings))
