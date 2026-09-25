"""Organizer file profile, address splitting and classifier mapping, without a database."""

import io
import unittest
from datetime import datetime

from openpyxl import Workbook

from app.modules.source_import import classify
from app.modules.source_import.addresses import parse_address
from app.modules.source_import.profile import (
    MOSCOW,
    SourceFormatError,
    dataset_from_filename,
    parse_moment,
    read_source,
)
from tests.source_fixtures import DEMAND_HEADER, OFFICE, _csv, control_csv, demand_csv, demand_rows


class SourceProfileTests(unittest.TestCase):
    def test_cp1251_semicolon_file_with_office_below_the_table(self):
        source = read_source(demand_csv(), "Центр Синтетические данные.csv")
        self.assertEqual((source.encoding, source.delimiter), ("cp1251", ";"))
        self.assertEqual(len(source.rows), 6)
        self.assertEqual(source.office_address, OFFICE)
        self.assertEqual(source.office_row, 10)
        self.assertFalse(source.is_control)
        first = source.rows[0]
        self.assertEqual(first.number, 2)
        self.assertEqual(first.values["external_id"], "101")
        self.assertEqual(first.values["bk_type"], "Подключение")
        self.assertEqual(first.raw["Гигабитное подключение"], "Нет")
        self.assertEqual(source.columns["gigabit"], "Гигабитное подключение")

    def test_utf8_comma_file_and_control_columns(self):
        source = read_source(
            _csv([DEMAND_HEADER, *demand_rows()], encoding="utf-8-sig", delimiter=","), "x.csv"
        )
        self.assertEqual((source.encoding, source.delimiter), ("utf-8-sig", ","))
        self.assertIsNone(source.office_address)
        control = read_source(control_csv(), "x.csv")
        self.assertTrue(control.is_control)
        self.assertEqual(control.rows[0].values["bk_status"], "Выполнена")
        self.assertEqual(control.rows[4].values["brigade"], "")

    def test_xlsx_sheets_header_aliases_and_date_cells(self):
        workbook = Workbook()
        workbook.active.title = "Справка"
        workbook.active.append(["Выгрузка за день"])
        sheet = workbook.create_sheet("Заявки")
        sheet.append(
            ["№ заявки", "Тип заявки ВК", "Тип HD", "Начало окна", "Конец окна", "Район", "Адрес"]
        )
        sheet.append(
            [
                "201",
                "Дозаказ",
                "Дозаказ оборудования",
                datetime(2026, 9, 10, 9, 30),
                "10.09.2026 11:00",
                "Южный",
                "Домодедово, ул.Опытная, д. 3",
            ]
        )
        sheet.append([None] * 7)
        sheet.append(["Адрес офиса", "г.Москва проезд Учебный, д.7"])
        output = io.BytesIO()
        workbook.save(output)
        source = read_source(output.getvalue(), "day.xlsx")
        self.assertEqual(source.sheets, ["Заявки"])
        self.assertEqual(source.warnings[0]["sheet"], "Справка")
        [row] = source.rows
        self.assertEqual((row.sheet, row.number), ("Заявки", 2))
        self.assertEqual(row.values["window_start"], "10.09.2026 09:30")
        self.assertEqual(row.values["external_id"], "201")
        self.assertEqual(source.office_address, "г.Москва проезд Учебный, д.7")

    def test_structural_errors_name_the_place(self):
        cases = [
            (_csv([["Заявка", "Адрес"], ["1", "x"]]), "x.csv", "Нет столбцов"),
            (b"", "x.csv", "Пустой файл"),
            (b"not a workbook", "x.xlsx", "Повреждённый XLSX"),
            (demand_csv(), "x.json", "Поддерживаются"),
            (demand_csv() + _csv([["Адрес офиса", "другой адрес"]]), "x.csv", "два разных"),
        ]
        for content, name, message in cases:
            with self.subTest(message=message), self.assertRaises(SourceFormatError) as caught:
                read_source(content, name)
            self.assertIn(message, str(caught.exception))
        missing = read_source(_csv([DEMAND_HEADER, *demand_rows()]), "x.csv")
        self.assertIsNone(missing.office_address)
        tail = read_source(demand_csv() + _csv([["лишняя", "строка"]]), "x.csv")
        self.assertEqual(tail.warnings[-1]["message"], "Строка после адреса офиса пропущена")

    def test_moscow_time_and_dataset_names(self):
        self.assertEqual(
            parse_moment("17.08.2026 0:01"), datetime(2026, 8, 17, 0, 1, tzinfo=MOSCOW)
        )
        self.assertEqual(parse_moment("2026-08-17 23:59").hour, 23)
        with self.assertRaises(ValueError):
            parse_moment("17.08.2026")
        self.assertEqual(dataset_from_filename("Восток Синтетические данные.csv"), "Восток")
        self.assertEqual(
            dataset_from_filename("Югоцентр Контрольное распределение..csv"), "Югоцентр"
        )
        self.assertEqual(dataset_from_filename("uploads/Юго-восток.xlsx"), "Юго-восток")


class AddressTests(unittest.TestCase):
    def test_source_spellings_become_directory_levels(self):
        # Fictional addresses in the spellings met in the organizer files.
        cases = {
            "Город Москва, пр-кт.Учебный, д. 12 к 3, кв. 7": (
                "Москва",
                "пр-кт Учебный",
                "12",
                "корп. 3",
                "7",
            ),
            "г.Город Москва, наб.Тестовая, д. 4/2к1": (
                "Москва",
                "наб. Тестовая",
                "4/2",
                "корп. 1",
                None,
            ),
            "МО, г. Учебногорск Опытного ул. д. 6/1": (
                "Учебногорск",
                "ул. Опытного",
                "6/1",
                None,
                None,
            ),
            "Москва Пробный пр-зд. д. 8к2": ("Москва", "проезд Пробный", "8", "корп. 2", None),
            "г. Москва, ул Учебная, д 5с 1": ("Москва", "ул. Учебная", "5", "стр. 1", None),
            "г.Москва проезд Тестовый, д.9": ("Москва", "проезд Тестовый", "9", None, None),
            "Домодедово, проезд.Опытный 1-й, д. 2А, кв. 11": (
                "Домодедово",
                "проезд Опытный 1-й",
                "2А",
                None,
                "11",
            ),
            "Город Москва, б-р.Тестовый Квартал 12а, д. к3, кв. 4": (
                "Москва",
                "б-р Тестовый",
                "квартал 12а",
                "корп. 3",
                "4",
            ),
            "обл.Московская область, г.Домодедово, пгт.Учебный-1, ул.Опытная, д. 3/5": (
                "Домодедово",
                "пгт. Учебный-1, ул. Опытная",
                "3/5",
                None,
                None,
            ),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                parsed = parse_address(text)
                self.assertEqual(
                    (
                        parsed.city,
                        parsed.street,
                        parsed.building_number,
                        parsed.block,
                        parsed.apartment,
                    ),
                    expected,
                )

    def test_unknown_forms_are_not_guessed(self):
        for text in ("", "Москва", "Город Москва, ул.Тверская", "где-то рядом, д. 5"):
            with self.subTest(text=text):
                self.assertIsNone(parse_address(text))


class ClassifierTests(unittest.TestCase):
    def test_bk_types_map_to_norms_and_statuses_to_outcomes(self):
        self.assertEqual(
            {
                bk: classify.work_type_code(bk)
                for bk in (
                    "Подключение",
                    "Дозаказ",
                    "Локальная заявка",
                    " глобальная  проблема ",
                    "Авария",
                )
            },
            {
                "Подключение": "connection",
                "Дозаказ": "additional",
                "Локальная заявка": "repair",
                " глобальная  проблема ": "emergency",
                "Авария": None,
            },
        )
        self.assertEqual(classify.source_status("Выполнена"), "completed")
        self.assertEqual(classify.source_status("Не отправлена"), "not_dispatched")
        self.assertIsNone(classify.source_status("Потеряна"))
        self.assertEqual(
            set(classify.SKILL_BY_CATEGORY.values()),
            {"Локальные работы", "Работы на подключение и дозаказы", "Аварийные работы"},
        )
