"""FastAPI entry point and module router registration."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.access_log import install_access_log_redaction
from app.core.body_limit import BodyLimitMiddleware
from app.core.config import get_settings
from app.db.session import get_engine
from app.modules.analytics.router import router as analytics_router
from app.modules.appliances.router import (
    appliances_router,
    equipment_journal_router,
    office_stock_router,
    ticket_appliances_router,
    worker_equipment_router,
)
from app.modules.auth.router import router as auth_router
from app.modules.auth.schemas import (
    LOGIN_REQUEST_EXAMPLE,
)
from app.modules.brigades.router import router as brigades_router
from app.modules.calendar_feed.router import router as calendar_router
from app.modules.comments.router import router as comments_router
from app.modules.data_exchange.router import router as data_exchange_router
from app.modules.locations.router import router as locations_router
from app.modules.notifications.dispatcher import create_dispatcher
from app.modules.notifications.router import router as notifications_router
from app.modules.offices.router import router as offices_router
from app.modules.planning.router import router as planning_router
from app.modules.reports.router import router as reports_router
from app.modules.routing.router import router as routing_router
from app.modules.schedule.router import router as schedule_router
from app.modules.service_areas.router import router as service_areas_router
from app.modules.tickets.router import router as tickets_router
from app.modules.tickets.schemas import TICKET_CREATE_EXAMPLE, TICKET_READ_EXAMPLE
from app.modules.users.router import router as users_router
from app.modules.users.router import skills_router, workers_router
from app.modules.users.schemas import (
    USER_CREATE_OBSERVER_EXAMPLE,
    USER_CREATE_WORKER_EXAMPLE,
    USER_READ_FOREMAN_EXAMPLE,
    USER_READ_OBSERVER_EXAMPLE,
    USER_READ_WORKER_EXAMPLE,
    USER_UPDATE_EXAMPLE,
    WORKER_SKILL_CREATE_EXAMPLE,
    WORKER_SKILL_EXAMPLE,
)
from app.modules.work_types.router import router as work_types_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.core.config import get_settings

    install_access_log_redaction()
    settings = get_settings()
    task = None
    if settings.notification_dispatcher_enabled:
        dispatcher = create_dispatcher()
        task = asyncio.create_task(dispatcher.run(settings.notification_poll_interval_seconds))
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Планирование выездных работ",
    description=(
        "Заявки, адресный справочник, пользователи, бригады и авторизация. "
        "Бригадир видит только собственную бригаду и заявки её исполнителей."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

settings = get_settings()
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
if cors_origins == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(BodyLimitMiddleware, prefix="/api/v1/planning", max_bytes=64 * 1024)
app.include_router(locations_router)
app.include_router(routing_router)
app.include_router(analytics_router)
app.include_router(reports_router)
app.include_router(planning_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(skills_router)
app.include_router(workers_router)
app.include_router(offices_router)
app.include_router(office_stock_router)
app.include_router(appliances_router)
app.include_router(brigades_router)
app.include_router(work_types_router)
app.include_router(tickets_router)
app.include_router(ticket_appliances_router)
app.include_router(worker_equipment_router)
app.include_router(equipment_journal_router)
app.include_router(calendar_router)
app.include_router(comments_router)
app.include_router(notifications_router)
app.include_router(data_exchange_router)
app.include_router(schedule_router)
app.include_router(service_areas_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness only: this endpoint does not check database readiness."""
    return {"status": "ok"}


def check_database_readiness() -> tuple[bool, bool]:
    """Return database connectivity and whether its schema matches Alembic heads."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            current_heads = set(MigrationContext.configure(connection).get_current_heads())
    except Exception:
        return False, False

    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    except Exception:
        return True, False
    return True, current_heads == expected_heads


async def check_planner_readiness() -> bool:
    """Check planner liveness without calling Geoapify or the paid routing provider."""
    settings = get_settings()
    url = settings.planner_base_url.rstrip("/") + "/health"
    timeout = httpx.Timeout(
        settings.planner_read_timeout_seconds,
        connect=settings.planner_connect_timeout_seconds,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
        return response.status_code == 200
    except (httpx.HTTPError, ValueError):
        return False


@app.get("/ready", tags=["system"])
async def readiness() -> JSONResponse:
    database_available, migrations_current = check_database_readiness()
    planner_available = await check_planner_readiness()
    ready = database_available and migrations_current and planner_available
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": {
                "database": "ok" if database_available else "unavailable",
                "migrations": "ok" if migrations_current else "pending",
                "planner": "ok" if planner_available else "unavailable",
            },
        },
    )


default_openapi = app.openapi


def openapi_with_examples() -> dict:
    schema = default_openapi()
    # FastAPI removes None recursively while generating OpenAPI. Restore the examples
    # afterwards so Swagger shows nullable response fields and unset manual duration.
    schemas = schema["components"]["schemas"]
    schemas["TicketCreate"]["examples"] = [TICKET_CREATE_EXAMPLE]
    schemas["TicketRead"]["examples"] = [TICKET_READ_EXAMPLE]

    if "UserCreate" in schemas:
        schemas["UserCreate"]["examples"] = [
            USER_CREATE_WORKER_EXAMPLE,
            USER_CREATE_OBSERVER_EXAMPLE,
        ]
    if "UserUpdate" in schemas:
        schemas["UserUpdate"]["examples"] = [USER_UPDATE_EXAMPLE]
    if "UserRead" in schemas:
        schemas["UserRead"]["examples"] = [
            USER_READ_WORKER_EXAMPLE,
            USER_READ_OBSERVER_EXAMPLE,
            USER_READ_FOREMAN_EXAMPLE,
        ]
    if "WorkerSkillCreate" in schemas:
        schemas["WorkerSkillCreate"]["examples"] = [WORKER_SKILL_CREATE_EXAMPLE]
    if "WorkerSkillRead" in schemas:
        schemas["WorkerSkillRead"]["examples"] = [WORKER_SKILL_EXAMPLE]
    if "LoginRequest" in schemas:
        schemas["LoginRequest"]["examples"] = [LOGIN_REQUEST_EXAMPLE]

    return schema


app.openapi = openapi_with_examples
