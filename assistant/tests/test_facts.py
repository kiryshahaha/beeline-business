import unittest
from datetime import UTC, datetime

from app.modules.chat.facts import answer_from_facts, detect_intents, plural, when
from app.modules.chat.schemas import ChatContext, ChatRequest
from eval.run_bench import facts_report, load_cases
from eval.run_intents import evaluate, load_splits
from tests.support import context_payload


def ask(message: str, context: str | None = None, role: str = "worker"):
    payload = ChatContext.model_validate(context_payload(context)) if context else None
    return answer_from_facts(ChatRequest(role=role, message=message, context=payload))


class IntentRoutingTests(unittest.TestCase):
    def test_routing_quality_on_the_eval_phrasings(self):
        splits = load_splits()
        dev, test = evaluate(splits["dev"]), evaluate(splits["test"])

        self.assertGreaterEqual(dev["accuracy"], 0.95, dev["errors"])
        self.assertGreaterEqual(test["accuracy"], 0.9, test["errors"])
        # A how-to question answered with the user's data would be a confident wrong answer.
        self.assertEqual(dev["false_positive"] + test["false_positive"], 0)

    def test_how_to_questions_are_not_about_data(self):
        for question in (
            "Как закрыть заявку?",
            "Какой статус поставить, когда приехал?",
            "Как поменять смену на ночную?",
            "Где взять оборудование?",
        ):
            with self.subTest(question):
                self.assertEqual(detect_intents(question), [])

    def test_compound_question_gets_an_answer_per_part(self):
        self.assertEqual(
            detect_intents("Какая у меня смена и сколько заявок?"), ["shift", "day_count"]
        )


class FactAnswerTests(unittest.TestCase):
    def test_every_data_question_of_the_eval_set_is_answered_correctly(self):
        rows = facts_report(load_cases())
        wrong = [row for row in rows if row["expected_facts"] and row["score"] < 1.0]
        unexpected = [row["id"] for row in rows if not row["expected_facts"]]

        self.assertEqual(wrong, [])
        self.assertEqual(unexpected, [])

    def test_next_ticket_skips_finished_and_current_ones(self):
        answer = ask("Какая следующая заявка?", "worker_day")

        self.assertIn("№95", answer.text)
        self.assertIn("13:30–15:00", answer.text)

    def test_removed_ticket_reason_is_given_without_the_new_worker(self):
        answer = ask("Почему у меня забрали заявку?", "worker_day")

        self.assertIn("№93", answer.text)
        self.assertIn("в 09:10", answer.text)

    def test_move_to_another_day_says_tomorrow(self):
        answer = ask("Почему мою заявку перенесли?", "ticket_rescheduled")

        self.assertIn("с 11:00 на завтра в 15:00", answer.text)

    def test_day_plan_diff_field_names_are_understood(self):
        payload = context_payload("ticket_rescheduled")
        payload["ticket"]["changes"][-1]["fields"] = {
            "service_start_at": {
                "from": "2026-09-29T11:00:00+03:00",
                "to": "2026-09-29T12:30:00+03:00",
            },
            "sequence": {"from": 2, "to": 3},
        }
        request = ChatRequest(
            role="worker",
            message="Почему перенесли заявку?",
            context=ChatContext.model_validate(payload),
        )

        self.assertIn("перенесли с 11:00 на 12:30", answer_from_facts(request).text)

    def test_unknown_reason_is_admitted(self):
        payload = context_payload("ticket_rescheduled")
        payload["ticket"]["changes"][-1]["reason_text"] = None
        request = ChatRequest(
            role="worker",
            message="Почему перенесли заявку?",
            context=ChatContext.model_validate(payload),
        )

        self.assertIn("причина в системе не указана", answer_from_facts(request).text)

    def test_day_questions_without_day_data_go_to_the_model(self):
        self.assertIsNone(ask("Сколько у меня заявок?"))
        self.assertIsNone(ask("Какая у меня смена?", role="foreman"))

    def test_question_without_intent_goes_to_the_model(self):
        self.assertIsNone(ask("Как настроить приставку?", "worker_day"))

    def test_open_ticket_questions_work_for_foreman_without_day(self):
        answer = ask("Почему заявку отменили?", "ticket_cancelled", role="foreman")

        self.assertIn("клиент отказался", answer.text)


class FormattingTests(unittest.TestCase):
    def test_times_are_shown_in_moscow_time(self):
        moment = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)

        self.assertEqual(when(moment, moment.date()), "11:00")

    def test_russian_plural_forms(self):
        self.assertEqual(plural(1, "заявка", "заявки", "заявок"), "1 заявка")
        self.assertEqual(plural(3, "заявка", "заявки", "заявок"), "3 заявки")
        self.assertEqual(plural(11, "заявка", "заявки", "заявок"), "11 заявок")
        self.assertEqual(plural(21, "заявка", "заявки", "заявок"), "21 заявка")


if __name__ == "__main__":
    unittest.main()
