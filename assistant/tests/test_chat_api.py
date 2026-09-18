import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.modules.chat.llm import LlmReply, LlmUnavailableError
from app.modules.chat.prompts import build_messages
from app.modules.chat.schemas import ChatRequest
from eval.run_bench import load_cases, score_answer

REPLY = LlmReply(
    text="Переведите заявку в статус «В работе».",
    prompt_tokens=100,
    completion_tokens=10,
    load_seconds=0.0,
    prompt_seconds=0.1,
    generation_seconds=0.2,
    total_seconds=0.3,
)


class ChatApiTests(unittest.TestCase):
    def test_answer_returns_model_text_and_sources(self):
        with (
            TestClient(app) as client,
            patch.object(app.state.llm, "chat", return_value=REPLY) as chat,
        ):
            response = client.post(
                "/api/v1/chat",
                json={"role": "worker", "message": "Я приехал к клиенту, какой статус ставить?"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["answer"], REPLY.text)
        self.assertTrue(body["sources"])
        messages = chat.call_args.args[1]
        self.assertIn("исполнитель", messages[0]["content"])
        self.assertTrue(messages[-1]["content"].endswith("какой статус ставить?"))

    def test_model_outage_returns_503(self):
        with (
            TestClient(app) as client,
            patch.object(app.state.llm, "chat", side_effect=LlmUnavailableError("down")),
        ):
            response = client.post("/api/v1/chat", json={"role": "observer", "message": "Привет"})

        self.assertEqual(response.status_code, 503)

    def test_unknown_role_is_rejected(self):
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json={"role": "admin", "message": "Привет"})

        self.assertEqual(response.status_code, 422)


class PromptTests(unittest.TestCase):
    def test_context_is_rendered_with_local_times_and_comments(self):
        case = next(case for case in load_cases() if case["id"] == "t-why-moved")
        prompt = build_messages(case["request"], chunks=[])[-1]["content"]

        self.assertIn("Плановое время: 18.09 15:00–16:00", prompt)
        self.assertIn("Система: Заявка перенесена", prompt)

    def test_history_is_kept_between_system_and_question(self):
        request = ChatRequest.model_validate(
            {
                "role": "foreman",
                "message": "А кто это делает?",
                "history": [
                    {"role": "user", "content": "Как поменять статус?"},
                    {"role": "assistant", "content": "Начальник бригады статусы не меняет."},
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
