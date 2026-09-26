"""In-process WebSocket connections grouped by authenticated user.

The map lives in this process only. That is why exactly one process may hold live
sockets (see `topology.py`): another process could claim an event, find no socket of
its own and the recipient connected elsewhere would silently get nothing.
"""

import asyncio
from collections import defaultdict, deque

from fastapi import WebSocket

# Ids already sent on a socket, so the reconnect replay and live delivery of the same
# event do not reach the client twice. The replay is bounded, so is this memory.
SENT_IDS_KEPT = 1000


class _Subscriber:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self._sent: set[int] = set()
        self._order: deque[int] = deque()

    def already_sent(self, event_id) -> bool:
        return event_id is not None and event_id in self._sent

    def remember(self, event_id) -> None:
        if event_id is None or event_id in self._sent:
            return
        self._sent.add(event_id)
        self._order.append(event_id)
        if len(self._order) > SENT_IDS_KEPT:
            self._sent.discard(self._order.popleft())


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, dict[WebSocket, _Subscriber]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[user_id][websocket] = _Subscriber(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(user_id)
            if sockets is None:
                return
            sockets.pop(websocket, None)
            if not sockets:
                self._connections.pop(user_id, None)

    async def send(self, user_id: int, websocket: WebSocket, payload: dict) -> bool:
        """Send one event to one socket unless it already has it; True if sent now."""
        async with self._lock:
            subscriber = self._connections.get(user_id, {}).get(websocket)
            if subscriber is None or subscriber.already_sent(payload.get("id")):
                return False
            subscriber.remember(payload.get("id"))
        await websocket.send_json(payload)
        return True

    async def publish(self, user_id: int, payload: dict) -> int:
        """Send to every socket of the user; returns how many actually received it."""
        async with self._lock:
            subscribers = tuple(self._connections.get(user_id, {}).values())
        delivered = 0
        stale = []
        for subscriber in subscribers:
            if subscriber.already_sent(payload.get("id")):
                # Received through the replay; for delivery accounting it has it.
                delivered += 1
                continue
            try:
                subscriber.remember(payload.get("id"))
                await subscriber.websocket.send_json(payload)
                delivered += 1
            except RuntimeError:
                stale.append(subscriber.websocket)
        for websocket in stale:
            await self.disconnect(user_id, websocket)
        return delivered

    async def close_all(self, code: int, reason: str) -> None:
        """Drop every socket, e.g. when this process stops being the delivery process."""
        async with self._lock:
            sockets = [
                (user_id, websocket)
                for user_id, entries in self._connections.items()
                for websocket in entries
            ]
            self._connections.clear()
        for _user_id, websocket in sockets:
            try:
                await websocket.close(code=code, reason=reason)
            except RuntimeError:
                pass


connection_manager = ConnectionManager()
