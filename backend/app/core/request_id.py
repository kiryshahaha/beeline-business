"""Give every request an ID that operation logs carry and the client can quote back."""

from app.core import oplog

HEADER = b"x-request-id"


class RequestIdMiddleware:
    """Accept a well-formed `X-Request-ID` or generate one, and echo it in the response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(HEADER)
        rid = oplog.bind_request_id(incoming.decode("latin-1") if incoming else None)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = [
                    (key, value) for key, value in message.get("headers", []) if key != HEADER
                ]
                message = {**message, "headers": [*headers, (HEADER, rid.encode("ascii"))]}
            await send(message)

        await self.app(scope, receive, send_with_id)
