"""Save already computed routes without changing tickets or invoking the solver."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.db.models import Brigade, BrigadeMember, Location, Ticket, Worker
from app.modules.routing.models import Route
from app.modules.routing.schemas import RouteCreate, RouteGeoJSON, RouteRead
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead


class RouteValidationError(ValueError):
    pass


def visible_routes(viewer: UserRead):
    query = select(Route)
    if viewer.role == UserRole.WORKER:
        query = query.where(Route.worker_id == viewer.id)
    elif viewer.role == UserRole.FOREMAN:
        query = query.where(
            Route.worker_id.in_(
                select(BrigadeMember.worker_id)
                .join(Brigade, Brigade.id == BrigadeMember.brigade_id)
                .where(Brigade.foreman_id == viewer.id)
            )
        )
    return query


def list_routes(
    session: Session,
    viewer: UserRead,
    worker_id: int | None,
    route_date: date | None,
    limit: int,
    offset: int,
) -> list[RouteRead]:
    query = visible_routes(viewer)
    if worker_id is not None:
        query = query.where(Route.worker_id == worker_id)
    if route_date is not None:
        query = query.where(Route.route_date == route_date)
    query = query.order_by(Route.route_date, Route.worker_id, Route.route_number)
    return [
        RouteRead.model_validate(row) for row in session.scalars(query.limit(limit).offset(offset))
    ]


def get_route(session: Session, viewer: UserRead, route_id: int) -> RouteRead | None:
    route = session.scalar(visible_routes(viewer).where(Route.id == route_id))
    return RouteRead.model_validate(route) if route is not None else None


def build_geojson(session: Session, data: RouteCreate, number: int) -> dict:
    locations = {
        loc.id: loc
        for loc in session.scalars(
            select(Location).where(Location.id.in_({s.location_id for s in data.stops}))
        )
    }
    tickets = {
        ticket.id: ticket
        for ticket in session.scalars(
            select(Ticket).where(Ticket.id.in_({s.ticket_id for s in data.stops if s.ticket_id}))
        )
    }
    features = []
    positions = []
    for sequence, stop in enumerate(data.stops, 1):
        location = locations.get(stop.location_id)
        if location is None or location.longitude is None or location.latitude is None:
            raise RouteValidationError(f"Точка {sequence}: место не найдено или не имеет координат")
        if stop.ticket_id is not None:
            ticket = tickets.get(stop.ticket_id)
            if ticket is None or ticket.location_id != stop.location_id:
                raise RouteValidationError(f"Точка {sequence}: заявка не соответствует месту")
        position = [float(location.longitude), float(location.latitude)]
        positions.append(position)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": position},
                "properties": {**stop.model_dump(mode="json"), "sequence": sequence},
            }
        )
    if data.geometry is not None or len(positions) > 1:
        features.append(
            {
                "type": "Feature",
                "geometry": data.geometry.model_dump(mode="json")
                if data.geometry
                else {
                    "type": "LineString",
                    "coordinates": positions,
                },
                "properties": data.path_properties.model_dump(mode="json")
                if data.path_properties
                else {
                    "kind": "path",
                    "source": "provided" if data.geometry else "straight_lines",
                },
            }
        )
    return RouteGeoJSON.model_validate(
        {
            "type": "FeatureCollection",
            "properties": {
                "worker_id": data.worker_id,
                "route_date": data.route_date,
                "route_number": number,
            },
            "features": features,
        }
    ).model_dump(mode="json")


def save_routes(session: Session, data: list[RouteCreate]) -> list[RouteRead]:
    with session.begin():
        lock_planning_mutation(session)
        return save_routes_in_transaction(session, data)


def save_routes_in_transaction(session: Session, data: list[RouteCreate]) -> list[RouteRead]:
    # Lock workers in a stable order: prevents duplicate numbers and batch deadlocks.
    ids = sorted({route.worker_id for route in data})
    workers = list(
        session.scalars(
            select(Worker.user_id)
            .where(Worker.user_id.in_(ids))
            .order_by(Worker.user_id)
            .with_for_update()
        )
    )
    if workers != ids:
        raise RouteValidationError("Исполнитель не найден")
    result = []
    for item in data:
        number = (
            session.scalar(
                select(func.max(Route.route_number)).where(
                    Route.worker_id == item.worker_id, Route.route_date == item.route_date
                )
            )
            or 0
        ) + 1
        route = Route(
            worker_id=item.worker_id,
            route_date=item.route_date,
            route_number=number,
            geojson=build_geojson(session, item, number),
        )
        session.add(route)
        session.flush()
        result.append(RouteRead.model_validate(route))
    return result
