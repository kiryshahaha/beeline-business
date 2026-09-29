import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.modules.chat.llm import LlmReply, LlmUnavailableError
from app.modules.chat.prompts import build_messages
from app.modules.chat.schemas import ChatRequest
from eval.run_bench import load_cases, score_answer
from tests.support import context_payload

REPLY = LlmReply(
    text="Нажмите «Начал работу», статус станет «В работе».",
    prompt_tokens=100,
    completion_tokens=10,
    load_seconds=0.0,
    prompt_seconds=0.1,
    generation_seconds=0.2,
    total_seconds=0.3,
)


class ChatApiTests(unittest.TestCase):
    def test_how_to_question_goes_to_the_model_with_knowledge(self):
        with (
            TestClient(app) as client,
            patch.object(app.state.llm, "chat", return_value=REPLY) as chat,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"role": "worker", "message": "Я приехал к клиенту, что нажать?"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer"], REPLY.text)
        self.assertEqual(body["source_type"], "knowledge")
        self.assertTrue(body["sources"])
        messages = chat.call_args.args[1]
        self.assertIn("исполнитель", messages[0]["content"])
        self.assertTrue(messages[-1]["content"].endswith("что нажать?"))

    def test_question_about_the_day_is_answered_from_data_without_the_model(self):
        with (
            TestClient(app) as client,
            patch.object(app.state.llm, "chat", side_effect=AssertionError("model called")),
        ):
            response = client.post(
                "/api/v1/chat",
                json={
                    "role": "worker",
                    "message": "Куда мне дальше?",
                    "context": context_payload("worker_day"),
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source_type"], "facts")
        self.assertIsNone(body["model"])
        self.assertEqual(body["intent"], "next_ticket")
        self.assertIn("№95", body["answer"])

    def test_backend_objects_with_extra_fields_are_accepted(self):
        payload = context_payload("ticket_rescheduled")
        payload["ticket"].update({"revision": 3, "is_pinned": False, "unknown_future_field": 1})
        with (
            TestClient(app) as client,
            patch.object(app.state.llm, "chat", side_effect=AssertionError("model called")),
        ):
            response = client.post(
                "/api/v1/chat",
                json={"role": "worker", "message": "Во сколько ехать?", "context": payload},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("15:00", response.json()["answer"])

    def test_model_outage_returns_503(self):
        with (
            TestClient(app) as client,
            patch.object(app.state.llm, "chat", side_effect=LlmUnavailableError("down")),
        ):
            response = client.post(
                "/api/v1/chat", json={"role": "observer", "message": "Как подтвердить завершение?"}
            )

        self.assertEqual(response.status_code, 503)

    def test_unknown_role_is_rejected(self):
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"role": "admin", "message": "Привет"})

        self.assertEqual(response.status_code, 422)


class PromptTests(unittest.TestCase):
    def test_day_and_open_ticket_are_rendered_for_the_model(self):
        case = next(case for case in load_cases() if case["id"] == "t-why-moved")
        prompt = build_messages(case["request"], chunks=[])[-1]["content"]

        self.assertIn("Плановое время работ: завтра 15:00–16:00", prompt)
        self.assertIn("перенесли с 11:00 на завтра в 15:00", prompt)
        self.assertIn("№95 «Протянуть оптику до кросса» — передана вам (следующая)", prompt)

    def test_history_is_kept_between_system_and_question(self):
        request = ChatRequest.model_validate(
            {
                "role": "foreman",
                "message": "А кто это делает?",
                "history": [
                    {"role": "user", "content": "Как поменять статус?"},
                    {"role": "assistant", "content": "Бригадир статусы не меняет."},
                ],
            }
        )
        roles = [message["role"] for message in build_messages(request, chunks=[])]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])


class ScoringTests(unittest.TestCase):
    def test_groups_violations_and_yo_normalization(self):
        result = score_answer("Статус «Завершён», руб.", [["завершен"], ["комментари"]], ["руб"])
        self.assertEqual(result["score"], 0.5)
        self.assertEqual(result["violations"], ["руб"])


if __name__ == "__main__":
    unittest.main()
