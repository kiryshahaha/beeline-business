import unittest
from datetime import datetime

from pydantic import ValidationError

from app.modules.tickets.schemas import TicketCreate

BASE = {
    "location_id": 1,
    "title": "Проверка заявки",
    "visit_window_start": datetime.fromisoformat("2030-01-15T10:00:00+03:00"),
    "visit_window_end": datetime.fromisoformat("2030-01-15T12:00:00+03:00"),
    "estimated_duration_minutes": 60,
}


class TicketWorkTypeIdTests(unittest.TestCase):
    def test_ticket_create_requires_catalog_work_type_id(self):
        with self.assertRaises(ValidationError):
            TicketCreate(**BASE)

    def test_ticket_create_does_not_accept_legacy_work_type_as_business_key(self):
        with self.assertRaises(ValidationError):
            TicketCreate(**BASE, work_type_id=1, work_type="Подмена названия")
