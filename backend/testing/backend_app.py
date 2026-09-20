"""Backend with fixed clock and deterministic Geoapify only; planner remains real HTTP."""

import os
from urllib.parse import urlparse

import httpx
from sqlalchemy.engine import make_url

from app.main import app
from app.modules.planning.router import get_clock, get_provider_factory
from app.modules.routing.client import AsyncGeoapifyRoutingClient, GeoapifyRoutingClient
from app.modules.routing.router import get_geoapify_routing_client
from planning_scenarios import NOW
from tests.planning_fakes import geoapify_response

if os.getenv("APP_ENV") != "test" or not (
    make_url(os.environ["DATABASE_URL"]).database or ""
).endswith("_test"):
    raise RuntimeError("Test entry point requires APP_ENV=test and a database ending in _test")

provider_url = os.environ["TEST_GEOAPIFY_URL"]
if urlparse(provider_url).hostname not in ("127.0.0.1", "localhost"):
    raise RuntimeError("Fixture server must be on loopback")

app.dependency_overrides[get_clock] = lambda: lambda: NOW
app.dependency_overrides[get_provider_factory] = lambda: (
    lambda: AsyncGeoapifyRoutingClient("fixture-only-key", base_url=provider_url)
)
app.dependency_overrides[get_geoapify_routing_client] = lambda: GeoapifyRoutingClient(
    "fixture-only-key", transport=httpx.MockTransport(geoapify_response)
)
