"""HTTP protocol fixture. Artificial 60-second legs are not real road estimates."""

import os

import httpx
from fastapi import FastAPI, Request, Response

from tests.planning_fakes import geoapify_response

if os.getenv("APP_ENV") != "test":
    raise RuntimeError("Fixture server requires APP_ENV=test")

app = FastAPI()


@app.api_route("/v1/{path}", methods=["POST", "GET"])
async def fixture(path: str, request: Request):
    if path not in ("routing", "routematrix"):
        return Response(status_code=404)
    result = geoapify_response(
        httpx.Request(request.method, str(request.url), content=await request.body())
    )
    return Response(
        content=result.content, status_code=result.status_code, media_type="application/json"
    )


@app.get("/health")
def health():
    return {"status": "ok", "provider": "test-fixture"}
