"""Explicit exchange allowlist. Credentials and delivery tokens never leave the DB."""

from app.db import models  # noqa: F401
from app.db.base import Base

TABLE_NAMES = frozenset(
    {
        "work_types",
        "work_type_planning_rules",
        "work_type_required_skills",
        "work_type_required_appliances",
        "cities",
        "districts",
        "divisions",
        "streets",
        "buildings",
        "entrances",
        "locations",
        "users",
        "workers",
        "worker_skills",
        "worker_skill_assignments",
        "offices",
        "brigades",
        "brigade_members",
        "tickets",
        "ticket_assignments",
        "ticket_comments",
        "appliances",
        "appliance_stocks",
        "ticket_appliances",
        "equipment_movements",
        "notification_events",
        "work_events",
        "worker_day_states",
        "day_plan_revisions",
        "routes",
    }
)
TABLES = {table.name: table for table in Base.metadata.sorted_tables if table.name in TABLE_NAMES}
TABLES["routes"] = TABLES.pop("routes")  # GeoJSON also refers to tickets and locations.
EXCLUDED_COLUMNS = {"users": {"password_hash"}}
FORMAT_VERSION = "2"


def columns_for(name: str):
    return [c for c in TABLES[name].columns if c.name not in EXCLUDED_COLUMNS.get(name, set())]


def describe_tables() -> dict:
    return {
        "format_version": FORMAT_VERSION,
        "tables": {
            name: [
                {
                    "name": c.name,
                    "type": str(c.type),
                    "nullable": c.nullable,
                    "required": c.primary_key
                    or (not c.nullable and c.server_default is None and c.default is None),
                }
                for c in columns_for(name)
            ]
            for name in TABLES
        },
        "excluded": [
            "users.password_hash",
            "refresh_tokens",
            "calendar_tokens",
            "push_subscriptions",
            "data_imports",
            "planning_plans",
            "planning_plan_routes",
            "office_kit_reserves",
            "worker_appliances",
            "appliance_operations",
            "appliance_movements",
            "ticket_appliance_states",
        ],
    }
