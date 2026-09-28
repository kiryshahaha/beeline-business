"""Tests for T4-01: ticket classification contract and event timing."""

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.modules.source_import.classify import (
    ClassificationError,
    classify_demand,
)
from app.modules.tickets.enums import TicketCategory
from app.modules.tickets.schemas import TicketCreate

MOSCOW = ZoneInfo("Europe/Moscow")


class ClassificationRulesTests(unittest.TestCase):
    def test_positive_emergency_classification(self):
        for hd in ("авария", "Аварийная Заявка", "авария на сети", "инцидент", "emergency"):
            cat, is_emerg = classify_demand(hd, work_type_category="repair")
            self.assertTrue(is_emerg, f"Expected {hd} to be emergency")
            self.assertEqual(cat, "emergency")

    def test_negative_non_emergency_classification(self):
        cases = [
            ("подключение", "connection"),
            ("нет линка", "repair"),
            ("дозаказ оборудования", "additional"),
            ("диагностика", "repair"),
        ]
        for hd, expected_cat in cases:
            cat, is_emerg = classify_demand(hd, work_type_category=expected_cat)
            self.assertFalse(is_emerg, f"Expected {hd} to be non-emergency")
            self.assertEqual(cat, expected_cat)

    def test_empty_hd_type_is_never_silently_emergency(self):
        cat, is_emerg = classify_demand(None, work_type_category="connection")
        self.assertFalse(is_emerg)
        self.assertEqual(cat, "connection")

        cat2, is_emerg2 = classify_demand("", work_type_category="repair")
        self.assertFalse(is_emerg2)
        self.assertEqual(cat2, "repair")

    def test_unknown_hd_type_raises_error(self):
        with self.assertRaises(ClassificationError) as ctx:
            classify_demand("неизвестный_тип_abc", work_type_category="repair")
        self.assertEqual(ctx.exception.code, "unknown_hd_type")

    def test_conflicting_classification_raises_error(self):
        # HD says emergency, caller says repair
        with self.assertRaises(ClassificationError) as ctx:
            classify_demand("авария", explicit_category="repair")
        self.assertEqual(ctx.exception.code, "category_classification_conflict")

        # HD says repair/connection, caller says emergency
        with self.assertRaises(ClassificationError) as ctx:
            classify_demand("подключение", explicit_category="emergency")
        self.assertEqual(ctx.exception.code, "category_classification_conflict")

    def test_emergency_without_hd_type_rejected(self):
        with self.assertRaises(ClassificationError) as ctx:
            classify_demand(None, explicit_category="emergency")
        self.assertEqual(ctx.exception.code, "emergency_hd_type_required")


class TicketCreateValidationTests(unittest.TestCase):
    def base_payload(self, **overrides):
        data = {
            "location_id": 1,
            "title": "Проверка классификации",
            "work_type_id": 1,
            "visit_window_start": "2026-09-30T10:00:00+03:00",
            "visit_window_end": "2026-09-30T12:00:00+03:00",
            "estimated_duration_minutes": 30,
        }
        data.update(overrides)
        return data

    def test_ticket_create_accepts_valid_emergency_hd(self):
        ticket = TicketCreate(
            **self.base_payload(
                request_type_hd="авария",
                category="emergency",
            )
        )
        self.assertEqual(ticket.request_type_hd, "авария")
        self.assertEqual(ticket.category, TicketCategory.EMERGENCY)

    def test_ticket_create_rejects_unknown_hd(self):
        with self.assertRaises(ValidationError) as ctx:
            TicketCreate(
                **self.base_payload(
                    request_type_hd="неизвестная_категория",
                )
            )
        self.assertIn("unknown_hd_type", str(ctx.exception))

    def test_ticket_create_rejects_emergency_without_hd(self):
        with self.assertRaises(ValidationError) as ctx:
            TicketCreate(
                **self.base_payload(
                    category="emergency",
                )
            )
        self.assertIn("emergency_hd_type_required", str(ctx.exception))

    def test_ticket_create_rejects_classification_conflict(self):
        with self.assertRaises(ValidationError) as ctx:
            TicketCreate(
                **self.base_payload(
                    request_type_hd="подключение",
                    category="emergency",
                )
            )
        self.assertIn("category_classification_conflict", str(ctx.exception))

    def test_received_at_and_response_deadline_sla(self):
        received = datetime(2026, 9, 30, 9, 15, tzinfo=MOSCOW)
        deadline = received + timedelta(minutes=120)
        ticket = TicketCreate(
            **self.base_payload(
                request_type_hd="авария",
                category="emergency",
                received_at=received,
                response_deadline_at=deadline,
            )
        )
        self.assertEqual(ticket.received_at, received)
        self.assertEqual(ticket.response_deadline_at, deadline)
        # Reaction target window is 120 minutes from original received_at
        self.assertEqual(
            (ticket.response_deadline_at - ticket.received_at).total_seconds() / 60,
            120,
        )


if __name__ == "__main__":
    unittest.main()
