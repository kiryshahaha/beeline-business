"""FastAPI entry point and module router registration."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.appliances.router import (
    appliances_router,
    office_stock_router,
    ticket_appliances_router,
)
from app.modules.auth.router import router as auth_router
from app.modules.auth.schemas import (
    LOGIN_REQUEST_EXAMPLE,
    REFRESH_TOKEN_REQUEST_EXAMPLE,
    TOKEN_RESPONSE_EXAMPLE,
)
from app.modules.brigades.router import router as brigades_router
from app.modules.comments.router import router as comments_router
from app.modules.data_exchange.router import router as data_exchange_router
from app.modules.locations.router import router as locations_router
from app.modules.notifications.dispatcher import create_dispatcher
from app.modules.notifications.router import router as notifications_router
from app.modules.offices.router import router as offices_router
from app.modules.routing.router import router as routing_router
from app.modules.tickets.router import router as tickets_router
from app.modules.tickets.schemas import TICKET_CREATE_EXAMPLE, TICKET_READ_EXAMPLE
from app.modules.users.router import router as users_router
from app.modules.users.router import skills_router
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.core.config import get_settings

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

app.include_router(locations_router)
app.include_router(routing_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(skills_router)
app.include_router(offices_router)
app.include_router(office_stock_router)
app.include_router(appliances_router)
app.include_router(brigades_router)
app.include_router(tickets_router)
app.include_router(ticket_appliances_router)
app.include_router(comments_router)
app.include_router(notifications_router)
app.include_router(routes_router)
app.include_router(data_exchange_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness only: this endpoint does not check database readiness."""
    return {"status": "ok"}


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
    if "RefreshTokenRequest" in schemas:
        schemas["RefreshTokenRequest"]["examples"] = [REFRESH_TOKEN_REQUEST_EXAMPLE]
    if "TokenResponse" in schemas:
        schemas["TokenResponse"]["examples"] = [TOKEN_RESPONSE_EXAMPLE]

    return schema


app.openapi = openapi_with_examples
