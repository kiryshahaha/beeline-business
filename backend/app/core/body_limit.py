"""Bound selected HTTP bodies before JSON decoding, including chunked requests."""

from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app, *, prefix, max_bytes):
        self.app, self.prefix, self.max_bytes = app, prefix, max_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not scope["path"].startswith(self.prefix)
        ):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                response = JSONResponse({"detail": "Request body too large"}, status_code=413)
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
