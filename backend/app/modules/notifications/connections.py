"""In-process WebSocket connections grouped by authenticated user."""

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(user_id)
            if sockets is None:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(user_id, None)

    async def publish(self, user_id: int, payload: dict) -> int:
        async with self._lock:
            sockets = tuple(self._connections.get(user_id, ()))
        delivered = 0
        stale = []
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
                delivered += 1
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(user_id, websocket)
        return delivered


connection_manager = ConnectionManager()
