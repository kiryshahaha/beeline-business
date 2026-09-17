"""Database queries and transactions for appliances and stock."""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.appliances.enums import ApplianceType
from app.modules.appliances.models import Appliance, ApplianceStock, TicketAppliance
from app.modules.appliances.schemas import ApplianceCreate, ApplianceUpdate


def create_appliance(session: Session, data: ApplianceCreate) -> Appliance:
    appliance = Appliance(
        name=data.name,
        description=data.description,
        type=data.type,
        unit=data.unit,
        is_active=True,
    )
    session.add(appliance)
    session.flush()
    return appliance


def get_appliance(session: Session, appliance_id: int) -> Appliance | None:
    return session.get(Appliance, appliance_id)


def get_appliance_by_name(session: Session, name: str) -> Appliance | None:
    statement = select(Appliance).where(Appliance.name.ilike(name.strip()))
    return session.scalars(statement).first()


def list_appliances(
    session: Session,
    *,
    type: ApplianceType | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Appliance]:
    statement = select(Appliance)
    if type is not None:
        statement = statement.where(Appliance.type == type)
    if is_active is not None:
        statement = statement.where(Appliance.is_active == is_active)
    if search:
        statement = statement.where(Appliance.name.ilike(f"%{search.strip()}%"))
    statement = statement.order_by(Appliance.name).limit(limit).offset(offset)
    return list(session.scalars(statement).all())


def update_appliance(session: Session, appliance: Appliance, data: ApplianceUpdate) -> Appliance:
    if data.name is not None:
        appliance.name = data.name
    if data.description is not None:
        appliance.description = data.description
    if data.type is not None:
        appliance.type = data.type
    if data.unit is not None:
        appliance.unit = data.unit
    if data.is_active is not None:
        appliance.is_active = data.is_active
    session.flush()
    return appliance


def delete_appliance(session: Session, appliance: Appliance) -> None:
    session.delete(appliance)
    session.flush()


def get_office_stock(
    session: Session, office_id: int, appliance_id: int, *, for_update: bool = False
) -> ApplianceStock | None:
    statement = select(ApplianceStock).where(
        ApplianceStock.office_id == office_id,
        ApplianceStock.appliance_id == appliance_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalars(statement).first()


def set_office_stock(
    session: Session, office_id: int, appliance_id: int, stock: int
) -> ApplianceStock:
    stock_row = get_office_stock(session, office_id, appliance_id, for_update=True)
    if stock_row is None:
        stock_row = ApplianceStock(
            office_id=office_id,
            appliance_id=appliance_id,
            stock=stock,
        )
        session.add(stock_row)
    else:
        stock_row.stock = stock
    session.flush()
    return stock_row


def get_reserved_stock_for_office(
    session: Session, office_id: int, appliance_id: int, *, exclude_ticket_id: int | None = None
) -> int:
    query = """
        SELECT COALESCE(SUM(ta.quantity), 0)
        FROM ticket_appliances ta
        JOIN tickets t ON t.id = ta.ticket_id
        WHERE ta.office_id = :office_id
          AND ta.appliance_id = :appliance_id
          AND t.status IN ('planned', 'in_progress')
    """
    params: dict[str, Any] = {"office_id": office_id, "appliance_id": appliance_id}
    if exclude_ticket_id is not None:
        query += " AND ta.ticket_id <> :exclude_ticket_id"
        params["exclude_ticket_id"] = exclude_ticket_id
    result = session.execute(text(query), params).scalar_one()
    return int(result)


def list_office_stocks(session: Session, office_id: int) -> list[dict[str, Any]]:
    query = """
        SELECT
            a.id AS appliance_id,
            a.name,
            a.description,
            a.type,
            a.unit,
            COALESCE(s.stock, 0) AS stock,
            COALESCE(r.reserved, 0) AS reserved,
            (COALESCE(s.stock, 0) - COALESCE(r.reserved, 0)) AS available
        FROM appliances a
        LEFT JOIN appliance_stocks s
            ON s.appliance_id = a.id AND s.office_id = :office_id
        LEFT JOIN (
            SELECT ta.appliance_id, SUM(ta.quantity) AS reserved
            FROM ticket_appliances ta
            JOIN tickets t ON t.id = ta.ticket_id
            WHERE ta.office_id = :office_id
              AND t.status IN ('planned', 'in_progress')
            GROUP BY ta.appliance_id
        ) r ON r.appliance_id = a.id
        WHERE a.is_active = TRUE
        ORDER BY a.name
    """
    rows = session.execute(text(query), {"office_id": office_id}).mappings().all()
    return [
        {
            "office_id": office_id,
            "appliance_id": row["appliance_id"],
            "name": row["name"],
            "description": row["description"],
            "type": row["type"],
            "unit": row["unit"],
            "stock": int(row["stock"]),
            "reserved": int(row["reserved"]),
            "available": int(row["available"]),
        }
        for row in rows
    ]


def get_ticket_appliance(
    session: Session, ticket_id: int, appliance_id: int
) -> TicketAppliance | None:
    statement = select(TicketAppliance).where(
        TicketAppliance.ticket_id == ticket_id,
        TicketAppliance.appliance_id == appliance_id,
    )
    return session.scalars(statement).first()


def list_ticket_appliances(session: Session, ticket_id: int) -> list[dict[str, Any]]:
    query = """
        SELECT
            ta.ticket_id,
            ta.appliance_id,
            a.name AS appliance_name,
            a.type AS appliance_type,
            a.unit,
            ta.office_id,
            ta.quantity,
            ta.created_at
        FROM ticket_appliances ta
        JOIN appliances a ON a.id = ta.appliance_id
        WHERE ta.ticket_id = :ticket_id
        ORDER BY ta.created_at
    """
    rows = session.execute(text(query), {"ticket_id": ticket_id}).mappings().all()
    return [
        {
            "ticket_id": row["ticket_id"],
            "appliance_id": row["appliance_id"],
            "appliance_name": row["appliance_name"],
            "appliance_type": row["appliance_type"],
            "unit": row["unit"],
            "office_id": row["office_id"],
            "quantity": int(row["quantity"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def create_ticket_appliance(
    session: Session, ticket_id: int, appliance_id: int, office_id: int, quantity: int
) -> TicketAppliance:
    ticket_appliance = TicketAppliance(
        ticket_id=ticket_id,
        appliance_id=appliance_id,
        office_id=office_id,
        quantity=quantity,
    )
    session.add(ticket_appliance)
    session.flush()
    return ticket_appliance


def update_ticket_appliance_quantity(
    session: Session, ticket_appliance: TicketAppliance, quantity: int
) -> TicketAppliance:
    ticket_appliance.quantity = quantity
    session.flush()
    return ticket_appliance


def delete_ticket_appliance(session: Session, ticket_appliance: TicketAppliance) -> None:
    session.delete(ticket_appliance)
    session.flush()


def find_ticket_default_office_id(session: Session, ticket_id: int) -> int | None:
    query = """
        SELECT b.office_id
        FROM ticket_assignments ta
        JOIN brigade_members bm ON bm.worker_id = ta.worker_id
        JOIN brigades b ON b.id = bm.brigade_id
        WHERE ta.ticket_id = :ticket_id
        LIMIT 1
    """
    row = session.execute(text(query), {"ticket_id": ticket_id}).scalar_one_or_none()
    if row is not None:
        return int(row)

    # If not assigned yet, fallback to first existing office
    fallback_query = "SELECT id FROM offices ORDER BY id LIMIT 1"
    fallback_id = session.execute(text(fallback_query)).scalar_one_or_none()
    return int(fallback_id) if fallback_id is not None else None


def consume_ticket_appliances_on_completed(session: Session, ticket_id: int) -> None:
    """Deduct consumables (all except TOOL) from physical stock upon ticket completion."""
    query = """
        SELECT ta.office_id, ta.appliance_id, ta.quantity, a.type
        FROM ticket_appliances ta
        JOIN appliances a ON a.id = ta.appliance_id
        WHERE ta.ticket_id = :ticket_id
    """
    rows = session.execute(text(query), {"ticket_id": ticket_id}).mappings().all()
    for row in rows:
        if row["type"] != ApplianceType.TOOL.value:
            # Atomic decrement of stock
            update_query = """
                UPDATE appliance_stocks
                SET stock = GREATEST(0, stock - :quantity)
                WHERE office_id = :office_id AND appliance_id = :appliance_id
            """
            session.execute(
                text(update_query),
                {
                    "office_id": row["office_id"],
                    "appliance_id": row["appliance_id"],
                    "quantity": row["quantity"],
                },
            )
    session.flush()
