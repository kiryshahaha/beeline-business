"""Explicit model registry for Alembic; domain modules do not import one another."""

from app.modules.appliances.models import (
    Appliance,
    ApplianceMovement,
    ApplianceOperation,
    ApplianceStock,
    OfficeKitReserve,
    TicketAppliance,
    TicketApplianceState,
    WorkerAppliance,
)
from app.modules.brigades.models import Brigade, BrigadeMember
from app.modules.buildings.models import Building
from app.modules.calendar_feed.models import CalendarToken
from app.modules.cities.models import City
from app.modules.comments.models import TicketComment
from app.modules.data_exchange.models import DataImport
from app.modules.districts.models import District
from app.modules.entrances.models import Entrance
from app.modules.locations.models import Location
from app.modules.notifications.models import NotificationEvent, PushSubscription
from app.modules.offices.models import Office  # noqa: F401
from app.modules.planning.models import PlanningPlan, PlanningPlanRoute
from app.modules.routing.models import Route
from app.modules.streets.models import Street
from app.modules.tickets.models import Ticket, TicketAssignment
from app.modules.users.models import (
    RefreshToken,
    User,
    Worker,
    WorkerSkill,
    WorkerSkillAssignment,
)
from app.modules.work_types.models import (
    WorkType,
    WorkTypePlanningRule,
    WorkTypeRequiredAppliance,
    WorkTypeRequiredSkill,
)

__all__ = [
    "Appliance",
    "ApplianceMovement",
    "ApplianceOperation",
    "ApplianceStock",
    "OfficeKitReserve",
    "TicketApplianceState",
    "WorkerAppliance",
    "Building",
    "Brigade",
    "BrigadeMember",
    "CalendarToken",
    "City",
    "District",
    "DataImport",
    "Entrance",
    "Location",
    "NotificationEvent",
    "PushSubscription",
    "RefreshToken",
    "Route",
    "Street",
    "Ticket",
    "TicketAppliance",
    "TicketAssignment",
    "TicketComment",
    "User",
    "Worker",
    "WorkerSkill",
    "WorkerSkillAssignment",
    "WorkType",
    "WorkTypePlanningRule",
    "WorkTypeRequiredSkill",
    "WorkTypeRequiredAppliance",
    "PlanningPlan",
    "PlanningPlanRoute",
]
