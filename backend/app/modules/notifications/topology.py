"""Which process delivers live notifications.

Supported mode: one backend process delivers WebSocket events, and a client that was
offline or reconnects catches up from the stored history (`last_event_id`). There is no
shared channel between processes, so a second process must not pretend to deliver:
it would claim events, find no local socket and the recipient connected to the first
process would silently get nothing.

The delivery role is a PostgreSQL session advisory lock held on a dedicated connection.
Only the holder runs the dispatcher and accepts WebSocket connections; another process
closes new sockets with 1013 ("try again later"), so the client reconnects — possibly
to the delivery process — and replays what it missed. If the holder's connection drops,
the lock is released by PostgreSQL and the role can move to another process.
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core import oplog

DELIVERY_LOCK_KEY = (17321, 2)


class DeliveryLease:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._connection: Connection | None = None

    @property
    def held(self) -> bool:
        return self._connection is not None

    def acquire(self) -> bool:
        if self._connection is not None:
            return True
        connection = self._engine.connect()
        try:
            granted = connection.execute(
                text("SELECT pg_try_advisory_lock(:space, :key)"),
                {"space": DELIVERY_LOCK_KEY[0], "key": DELIVERY_LOCK_KEY[1]},
            ).scalar_one()
            connection.commit()
        except Exception:
            connection.close()
            raise
        if not granted:
            connection.close()
            oplog.log("notifications.delivery_role", logging.WARNING, role="secondary")
            return False
        self._connection = connection
        oplog.log("notifications.delivery_role", role="primary")
        return True

    def alive(self) -> bool:
        """Still holding the role; a broken connection means the lock is already gone."""
        if self._connection is None:
            return False
        try:
            self._connection.execute(text("SELECT 1"))
            self._connection.commit()
            return True
        except SQLAlchemyError:
            self._drop()
            oplog.log("notifications.delivery_role", logging.ERROR, role="lost")
            return False

    def release(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute(
                text("SELECT pg_advisory_unlock(:space, :key)"),
                {"space": DELIVERY_LOCK_KEY[0], "key": DELIVERY_LOCK_KEY[1]},
            )
            self._connection.commit()
        finally:
            self._drop()

    def _drop(self) -> None:
        connection, self._connection = self._connection, None
        try:
            connection.close()
        except SQLAlchemyError:
            pass


class DeliveryState:
    """What the WebSocket endpoint asks: may this process hold live sockets now?"""

    def __init__(self) -> None:
        self.lease: DeliveryLease | None = None

    def accepts_live_sockets(self) -> bool:
        # Without a dispatcher (tests, one-off scripts) nothing is delivered live anyway:
        # sockets still authenticate and receive the history replay.
        return self.lease is None or self.lease.held


delivery_state = DeliveryState()
