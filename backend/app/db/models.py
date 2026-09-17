"""Explicit model registry for Alembic; domain modules do not import one another."""

from app.modules.brigades.models import Brigade, BrigadeMember
from app.modules.buildings.models import Building
from app.modules.cities.models import City
from app.modules.comments.models import TicketComment
from app.modules.districts.models import District
from app.modules.entrances.models import Entrance
from app.modules.locations.models import Location
from app.modules.notifications.models import NotificationEvent, PushSubscription
from app.modules.streets.models import Street
from app.modules.tickets.models import Ticket, TicketAssignment
from app.modules.users.models import (
    RefreshToken,
    User,
    Worker,
    WorkerSkill,
    WorkerSkillAssignment,
)

__all__ = [
    "Building",
    "Brigade",
    "BrigadeMember",
    "City",
    "District",
    "Entrance",
    "Location",
    "NotificationEvent",
    "PushSubscription",
    "RefreshToken",
    "Street",
    "Ticket",
    "TicketAssignment",
    "TicketComment",
    "User",
    "Worker",
    "WorkerSkill",
    "WorkerSkillAssignment",
]
