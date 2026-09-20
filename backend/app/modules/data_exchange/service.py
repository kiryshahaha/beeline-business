"""Transactional inserts, source-ID remapping, dry runs and consistent snapshots."""

import copy
import hashlib
import json
import secrets
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.core.security import hash_password
from app.modules.data_exchange.formats import ExchangeError, json_default
from app.modules.data_exchange.models import DataImport
from app.modules.data_exchange.registry import TABLES, columns_for
from app.modules.routing.schemas import RouteGeoJSON, StopFeature


def export_data(session: Session) -> dict[str, list[dict]]:
    with session.begin():
        # One snapshot for all tables, even if other requests commit during the export.
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        return {
            name: [
                dict(row)
                for row in session.execute(
                    select(*columns_for(name)).order_by(*table.primary_key.columns)
                ).mappings()
            ]
            for name, table in TABLES.items()
        }


def _remap(name: str, value, tables: dict, ids: dict):
    if value is None or name not in tables:
        return value
    if value not in ids.get(name, {}):
        raise ValueError(f"Ссылка {name}:{value} отсутствует в пакете")
    return ids[name][value]


def _validate_route(session: Session, values: dict, tables: dict, ids: dict) -> None:
    geo = RouteGeoJSON.model_validate(values["geojson"])
    geo.properties.worker_id = _remap("workers", geo.properties.worker_id, tables, ids)
    if (
        geo.properties.worker_id != values["worker_id"]
        or geo.properties.route_date != values["route_date"]
        or geo.properties.route_number != values["route_number"]
    ):
        raise ValueError("Метаданные GeoJSON не совпадают с маршрутом")
    for feature in geo.features:
        if not isinstance(feature, StopFeature):
            continue
        props = feature.properties
        props.location_id = _remap("locations", props.location_id, tables, ids)
        props.ticket_id = _remap("tickets", props.ticket_id, tables, ids)
        location = (
            session.execute(
                select(TABLES["locations"]).where(TABLES["locations"].c.id == props.location_id)
            )
            .mappings()
            .one_or_none()
        )
        if location is None:
            raise ValueError("Место из GeoJSON не найдено")
        if props.ticket_id is not None:
            location_id = session.scalar(
                select(TABLES["tickets"].c.location_id).where(
                    TABLES["tickets"].c.id == props.ticket_id
                )
            )
            if location_id != props.location_id:
                raise ValueError("Заявка из GeoJSON не соответствует месту")
    # Coordinates are historical snapshots: they need not match today's location coordinates.
    values["geojson"] = geo.model_dump(mode="json")


def _validate_business_rules(session: Session, tables: dict, ids: dict, inserted: dict) -> None:
    users = TABLES["users"]
    for worker in inserted.get("workers", []):
        if session.scalar(select(users.c.role).where(users.c.id == worker["user_id"])) != "worker":
            raise ExchangeError("Профиль исполнителя допустим только для роли worker", "workers")
    for brigade in inserted.get("brigades", []):
        if (
            session.scalar(select(users.c.role).where(users.c.id == brigade["foreman_id"]))
            != "foreman"
        ):
            raise ExchangeError("Бригадир должен иметь роль foreman", "brigades")
    for user in inserted.get("users", []):
        if user["role"] == "worker" and not session.scalar(
            select(TABLES["workers"].c.user_id).where(TABLES["workers"].c.user_id == user["id"])
        ):
            raise ExchangeError("Для worker требуется профиль workers в том же пакете", "users")
    # Lock stock rows in the same order in all imports before checking reservations.
    pairs = sorted(
        {(row["office_id"], row["appliance_id"]) for row in inserted.get("ticket_appliances", [])}
    )
    for office_id, appliance_id in pairs:
        available = session.execute(
            text(
                "SELECT stock FROM appliance_stocks WHERE office_id=:office "
                "AND appliance_id=:appliance FOR UPDATE"
            ),
            {"office": office_id, "appliance": appliance_id},
        ).scalar_one_or_none()
        reserved = session.execute(
            text(
                "SELECT COALESCE(sum(a.quantity), 0) FROM ticket_appliances a "
                "JOIN tickets t ON t.id=a.ticket_id WHERE a.office_id=:office "
                "AND a.appliance_id=:appliance AND t.status IN ('planned', 'in_progress')"
            ),
            {"office": office_id, "appliance": appliance_id},
        ).scalar_one()
        if reserved > (available or 0):
            raise ExchangeError(
                "Резерв оборудования превышает складской остаток", "ticket_appliances"
            )


def import_data(session: Session, tables: dict[str, list[dict]], *, dry_run: bool = False) -> dict:
    fingerprint = hashlib.sha256(
        json.dumps(
            tables,
            sort_keys=True,
            ensure_ascii=False,
            default=json_default,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    name, row_number = None, None
    try:
        with session.begin():
            lock_planning_mutation(session)
            # Serialize identical packages, including concurrent HTTP uploads.
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {
                    "key": int(fingerprint[:15], 16),
                },
            )
            previous = session.get(DataImport, fingerprint)
            if previous:
                return {**previous.result, "duplicate": True, "dry_run": dry_run}
            # A SAVEPOINT allows a full database validation without persisting a dry run.
            with session.begin_nested() as transaction:
                ids = {}
                inserted = {}
                for name, table in TABLES.items():
                    if name not in tables:
                        continue
                    ids[name], inserted[name] = {}, []
                    if name == "routes":
                        worker_ids = sorted(
                            {
                                _remap("workers", row["worker_id"], tables, ids)
                                for row in tables[name]
                            }
                        )
                        workers = TABLES["workers"]
                        session.execute(
                            select(workers.c.user_id)
                            .where(workers.c.user_id.in_(worker_ids))
                            .order_by(workers.c.user_id)
                            .with_for_update()
                        ).all()
                    for row_number, source in enumerate(tables[name], 2):
                        row_number = getattr(source, "row_number", row_number)
                        values = copy.deepcopy(source)
                        # city_id participates in two composite FKs, neither targets cities.id.
                        if name == "buildings":
                            values["city_id"] = _remap("cities", values["city_id"], tables, ids)
                        for column in table.columns:
                            for foreign in column.foreign_keys:
                                if foreign.column.name == "id" or (
                                    foreign.column.table.name
                                    in ("workers", "work_type_planning_rules")
                                    and foreign.column.name in ("user_id", "work_type_id")
                                ):
                                    if column.name in values:
                                        values[column.name] = _remap(
                                            foreign.column.table.name,
                                            values[column.name],
                                            tables,
                                            ids,
                                        )
                        source_id = values.pop("id", None)
                        if name == "work_types":
                            norm = values.pop("norm_minutes", None)
                            if norm is not None and norm != sum(
                                values[k]
                                for k in ("travel_minutes", "work_minutes", "documents_minutes")
                            ):
                                raise ValueError("Computed work norm does not match its parts")
                            existing = (
                                session.execute(
                                    select(table).where(
                                        func.lower(table.c.name) == values["name"].lower()
                                    )
                                )
                                .mappings()
                                .one_or_none()
                            )
                            if existing is not None:
                                if any(
                                    existing[k] != values[k]
                                    for k in ("travel_minutes", "work_minutes", "documents_minutes")
                                ):
                                    raise ValueError("Existing work type has different norms")
                                ids[name][source_id] = existing["id"]
                                inserted[name].append(dict(existing))
                                continue
                        if name == "users":
                            # Imported accounts need a dispatcher to set a known password.
                            values["password_hash"] = hash_password(secrets.token_urlsafe(48))
                        if name == "routes":
                            _validate_route(session, values, tables, ids)
                        if name == "notification_events":
                            # Importing history must not trigger fresh push/websocket delivery.
                            delivered = datetime.now(UTC)
                            values["websocket_delivered_at"] = (
                                values.get("websocket_delivered_at") or delivered
                            )
                            values["push_delivered_at"] = (
                                values.get("push_delivered_at") or delivered
                            )
                            for key, target in (
                                ("ticket_id", "tickets"),
                                ("worker_id", "workers"),
                                ("actor_id", "users"),
                            ):
                                if key in values.get("data", {}):
                                    values["data"][key] = _remap(
                                        target, values["data"][key], tables, ids
                                    )
                        record = dict(
                            session.execute(table.insert().values(**values).returning(table))
                            .mappings()
                            .one()
                        )
                        inserted[name].append(record)
                        if source_id is not None:
                            ids[name][source_id] = record["id"]
                        elif name == "work_type_planning_rules":
                            ids[name][source["work_type_id"]] = record["work_type_id"]
                        elif name == "workers":
                            ids[name][source["user_id"]] = record["user_id"]
                _validate_business_rules(session, tables, ids, inserted)
                result = {
                    "fingerprint": fingerprint,
                    "dry_run": dry_run,
                    "duplicate": False,
                    "counts": {name: len(rows) for name, rows in tables.items()},
                    "id_map": {
                        name: {str(old): new for old, new in values.items()}
                        for name, values in ids.items()
                    },
                }
                if dry_run:
                    transaction.rollback()
                else:
                    session.add(DataImport(fingerprint=fingerprint, result=result))
            return result
    except ExchangeError:
        raise
    except (IntegrityError, DataError) as error:
        # Do not include SQL parameters or database diagnostics containing imported personal data.
        raise ExchangeError(
            "Нарушена уникальность, связь или ограничение данных; пакет отменён", name, row_number
        ) from error
    except (ValueError, TypeError, KeyError) as error:
        raise ExchangeError(str(error), name, row_number) from error
