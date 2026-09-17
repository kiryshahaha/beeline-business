import unittest

from app.core.config import get_settings
from app.modules.chat.knowledge import KnowledgeBase, tokenize
from eval.run_bench import load_cases, retrieval_report


class KnowledgeBaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge = KnowledgeBase.from_dir(get_settings().knowledge_dir)

    def test_every_document_has_sections_and_known_roles(self):
        self.assertTrue(self.knowledge.chunks)
        for chunk in self.knowledge.chunks:
            self.assertTrue(chunk.text, chunk.path)
            self.assertLessEqual(chunk.roles, {"worker", "foreman", "observer"}, chunk.path)

    def test_role_only_sees_its_documents(self):
        found = self.knowledge.search("как назначить исполнителей на заявку", "worker", k=10)
        self.assertTrue(found)
        self.assertNotIn("system/observer.md", {chunk.path for chunk in found})

    def test_open_ticket_work_type_ranks_its_sections_first(self):
        found = self.knowledge.search("что делать", "worker", k=2, work_type="Монтаж ВОЛС")
        self.assertEqual({chunk.work_type for chunk in found}, {"Монтаж ВОЛС"})

    def test_stemming_matches_word_forms(self):
        self.assertEqual(tokenize("заявки"), tokenize("заявку"))

    def test_eval_questions_find_expected_sections(self):
        hit_rate, rows = retrieval_report(
            load_cases(), self.knowledge, get_settings().retrieval_top_k
        )
        misses = [row[0] for row in rows if not row[1]]
        self.assertGreaterEqual(hit_rate, 0.9, misses)


if __name__ == "__main__":
    unittest.main()
