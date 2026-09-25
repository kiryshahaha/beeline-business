"""Literal SQL for source imports; the service owns the transaction and the planning lock."""

import json

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session


def find_service_area(session: Session, code: str) -> RowMapping | None:
    return (
        session.execute(
            text("SELECT id, code, name FROM service_areas WHERE lower(code) = lower(:code)"),
            {"code": code},
        )
        .mappings()
        .one_or_none()
    )


def add_service_area(session: Session, code: str, name: str) -> int:
    return session.execute(
        text("""
            INSERT INTO service_areas (code, name, description)
            VALUES (:code, :name, 'Участок исходной выгрузки организатора')
            RETURNING id
        """),
        {"code": code, "name": name},
    ).scalar_one()


def find_office(session: Session, name: str) -> RowMapping | None:
    return (
        session.execute(
            text("SELECT id, location_id FROM offices WHERE lower(name) = lower(:name)"),
            {"name": name},
        )
        .mappings()
        .one_or_none()
    )


def add_office(session: Session, name: str, location_id: int) -> int:
    return session.execute(
        text("INSERT INTO offices (name, location_id) VALUES (:name, :location_id) RETURNING id"),
        {"name": name, "location_id": location_id},
    ).scalar_one()


def work_types_by_code(session: Session) -> dict[str, RowMapping]:
    rows = session.execute(
        text("""
            SELECT id, code, name, category, default_priority, work_minutes, documents_minutes
            FROM work_types
        """)
    ).mappings()
    return {row["code"]: row for row in rows}


def unconfigured_work_types(session: Session, ids: list[int]) -> list[str]:
    return list(
        session.execute(
            text("""
                SELECT wt.name
                FROM work_types AS wt
                WHERE wt.id = ANY(:ids)
                  AND NOT EXISTS (
                      SELECT 1 FROM work_type_planning_rules AS r WHERE r.work_type_id = wt.id
                  )
                ORDER BY wt.name
            """),
            {"ids": ids},
        ).scalars()
    )


def find_addresses(session: Session, area_id: int, raws: list[str]) -> dict[str, RowMapping]:
    rows = session.execute(
        text("""
            SELECT a.id, a.raw_address, a.location_id, a.status, a.source, a.confidence,
                   a.candidate_latitude, a.candidate_longitude, l.latitude, l.longitude
            FROM source_addresses AS a
            JOIN locations AS l ON l.id = a.location_id
            WHERE a.service_area_id = :area_id AND a.raw_address = ANY(:raws)
        """),
        {"area_id": area_id, "raws": raws},
    ).mappings()
    return {row["raw_address"]: row for row in rows}


def upsert_address(session: Session, values: dict) -> int:
    return session.execute(
        text("""
            INSERT INTO source_addresses (
                service_area_id, raw_address, location_id, status, source, confidence,
                candidate_latitude, candidate_longitude
            ) VALUES (
                :service_area_id, :raw_address, :location_id, :status, :source, :confidence,
                :candidate_latitude, :candidate_longitude
            )
            ON CONFLICT (service_area_id, raw_address) DO UPDATE SET
                location_id = EXCLUDED.location_id,
                status = EXCLUDED.status,
                source = EXCLUDED.source,
                confidence = EXCLUDED.confidence,
                candidate_latitude = EXCLUDED.candidate_latitude,
                candidate_longitude = EXCLUDED.candidate_longitude,
                updated_at = now()
            RETURNING id
        """),
        values,
    ).scalar_one()


def location_coordinates(session: Session, location_id: int) -> RowMapping:
    return (
        session.execute(
            text("SELECT latitude, longitude FROM locations WHERE id = :id FOR UPDATE"),
            {"id": location_id},
        )
        .mappings()
        .one()
    )


def set_location_coordinates(session: Session, location_id: int, latitude, longitude) -> None:
    session.execute(
        text("UPDATE locations SET latitude = :lat, longitude = :lon WHERE id = :id"),
        {"id": location_id, "lat": latitude, "lon": longitude},
    )


def find_records(session: Session, area_id: int, kind: str) -> dict[str, RowMapping]:
    rows = session.execute(
        text("""
            SELECT id, external_id, row_number, raw, content_sha256, ticket_id, worker_id,
                   outcome
            FROM source_records
            WHERE service_area_id = :area_id AND kind = :kind
        """),
        {"area_id": area_id, "kind": kind},
    ).mappings()
    return {row["external_id"]: row for row in rows}


def save_record(session: Session, values: dict) -> None:
    session.execute(
        text("""
            INSERT INTO source_records (
                import_id, service_area_id, kind, external_id, sheet, row_number,
                bk_type, bk_status, hd_type, raw, content_sha256, ticket_id, worker_id,
                address_id, outcome, reason_code, reason
            ) VALUES (
                :import_id, :service_area_id, :kind, :external_id, :sheet, :row_number,
                :bk_type, :bk_status, :hd_type, CAST(:raw AS JSONB), :content_sha256,
                :ticket_id, :worker_id, :address_id, :outcome, :reason_code, :reason
            )
            ON CONFLICT (service_area_id, kind, external_id) DO UPDATE SET
                import_id = EXCLUDED.import_id,
                sheet = EXCLUDED.sheet,
                row_number = EXCLUDED.row_number,
                bk_type = EXCLUDED.bk_type,
                bk_status = EXCLUDED.bk_status,
                hd_type = EXCLUDED.hd_type,
                raw = EXCLUDED.raw,
                content_sha256 = EXCLUDED.content_sha256,
                ticket_id = COALESCE(EXCLUDED.ticket_id, source_records.ticket_id),
                worker_id = COALESCE(EXCLUDED.worker_id, source_records.worker_id),
                address_id = COALESCE(EXCLUDED.address_id, source_records.address_id),
                outcome = EXCLUDED.outcome,
                reason_code = EXCLUDED.reason_code,
                reason = EXCLUDED.reason,
                updated_at = now()
        """),
        {**values, "raw": json.dumps(values["raw"], ensure_ascii=False)},
    )


def ticket_state(session: Session, ticket_id: int) -> RowMapping:
    return (
        session.execute(
            text("""
                SELECT t.lifecycle_state, t.status, t.assigned_worker_id IS NOT NULL AS assigned
                FROM tickets AS t
                WHERE t.id = :id
                FOR UPDATE
            """),
            {"id": ticket_id},
        )
        .mappings()
        .one()
    )


def update_ticket(session: Session, ticket_id: int, values: dict) -> None:
    session.execute(
        text("""
            UPDATE tickets SET
                location_id = :location_id,
                title = :title,
                description = :description,
                work_type = :work_type,
                work_type_id = :work_type_id,
                category = :category,
                priority = :priority,
                received_at = :received_at,
                visit_window_start = :visit_window_start,
                visit_window_end = :visit_window_end,
                estimated_duration_minutes = :estimated_duration_minutes,
                revision = revision + 1,
                updated_at = now()
            WHERE id = :ticket_id
        """),
        {**values, "ticket_id": ticket_id},
    )


def latest_demand_import(session: Session, area_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT i.id, i.office_id, o.location_id
                FROM source_imports AS i
                JOIN offices AS o ON o.id = i.office_id
                WHERE i.service_area_id = :area_id AND i.kind = 'demand'
                ORDER BY i.id DESC
                LIMIT 1
            """),
            {"area_id": area_id},
        )
        .mappings()
        .one_or_none()
    )


def add_import(session: Session, values: dict) -> int:
    return session.execute(
        text("""
            INSERT INTO source_imports (
                service_area_id, kind, filename, file_sha256, mapping_version, work_date,
                office_id, report, created_by
            ) VALUES (
                :service_area_id, :kind, :filename, :file_sha256, :mapping_version, :work_date,
                :office_id, '{}'::jsonb, :created_by
            )
            RETURNING id
        """),
        values,
    ).scalar_one()


def finish_import(session: Session, import_id: int, report: dict, office_id: int | None) -> None:
    session.execute(
        text("""
            UPDATE source_imports
            SET report = CAST(:report AS JSONB), office_id = COALESCE(:office_id, office_id)
            WHERE id = :id
        """),
        {"id": import_id, "report": json.dumps(report, ensure_ascii=False), "office_id": office_id},
    )


def list_imports(session: Session, limit: int, offset: int) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                SELECT i.id, i.service_area_id, a.code AS service_area_code,
                       a.name AS dataset, i.kind, i.filename, i.file_sha256,
                       i.mapping_version, i.work_date, i.office_id, i.created_by, i.created_at,
                       i.report -> 'counts' AS counts
                FROM source_imports AS i
                JOIN service_areas AS a ON a.id = i.service_area_id
                ORDER BY i.id DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )


def find_import(session: Session, import_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("SELECT id, report FROM source_imports WHERE id = :id"), {"id": import_id}
        )
        .mappings()
        .one_or_none()
    )


def list_addresses(session: Session, area_id: int | None, status: str | None) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                SELECT a.id, a.service_area_id, a.raw_address, a.location_id, a.status,
                       a.source, a.confidence, a.candidate_latitude, a.candidate_longitude,
                       a.reviewed_by, a.updated_at, l.latitude, l.longitude
                FROM source_addresses AS a
                JOIN locations AS l ON l.id = a.location_id
                WHERE (CAST(:area_id AS integer) IS NULL OR a.service_area_id = :area_id)
                  AND (CAST(:status AS text) IS NULL OR a.status = :status)
                ORDER BY a.service_area_id, a.id
            """),
            {"area_id": area_id, "status": status},
        )
        .mappings()
        .all()
    )


def lock_address(session: Session, address_id: int) -> RowMapping | None:
    return (
        session.execute(
            text("SELECT id, location_id FROM source_addresses WHERE id = :id FOR UPDATE"),
            {"id": address_id},
        )
        .mappings()
        .one_or_none()
    )


def review_address(session: Session, address_id: int, reviewer_id: int) -> None:
    session.execute(
        text("""
            UPDATE source_addresses
            SET status = 'manual', source = 'manual', confidence = NULL,
                candidate_latitude = NULL, candidate_longitude = NULL,
                reviewed_by = :reviewer_id, updated_at = now()
            WHERE id = :id
        """),
        {"id": address_id, "reviewer_id": reviewer_id},
    )


def replay_rows(session: Session, area_id: int) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                SELECT r.external_id, r.row_number, r.ticket_id, r.worker_id, r.bk_status,
                       t.visit_window_start, t.visit_window_end
                FROM source_records AS r
                JOIN tickets AS t ON t.id = r.ticket_id
                WHERE r.service_area_id = :area_id
                  AND r.kind = 'control'
                  AND r.outcome <> 'rejected'
                ORDER BY t.visit_window_end, r.row_number
            """),
            {"area_id": area_id},
        )
        .mappings()
        .all()
    )
