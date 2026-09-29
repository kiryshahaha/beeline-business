"""Measure how questions are routed to data answers; needs no model.

python -m eval.run_intents
"""

from pathlib import Path

import yaml

from app.modules.chat.facts import detect_intents

EVAL_DIR = Path(__file__).resolve().parent


def expected_intents(case: dict) -> list[str]:
    value = case["intent"]
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def evaluate(cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        expected = expected_intents(case)
        got = detect_intents(case["text"])
        rows.append({"text": case["text"], "expected": expected, "got": got, "ok": got == expected})
    about_data = [r for r in rows if r["expected"]]
    not_data = [r for r in rows if not r["expected"]]
    return {
        "total": len(rows),
        "accuracy": sum(r["ok"] for r in rows) / len(rows),
        "data_recall": sum(r["ok"] for r in about_data) / max(len(about_data), 1),
        "wrong_data_answer": sum(bool(r["got"]) and not r["ok"] for r in about_data),
        "false_positive": sum(bool(r["got"]) for r in not_data),
        "not_data_total": len(not_data),
        "data_total": len(about_data),
        "errors": [r for r in rows if not r["ok"]],
    }


def load_splits() -> dict[str, list[dict]]:
    return yaml.safe_load((EVAL_DIR / "intents.yaml").read_text(encoding="utf-8"))


def main() -> None:
    for split, cases in load_splits().items():
        result = evaluate(cases)
        print(
            f"{split}: верно {result['accuracy']:.0%} из {result['total']}; "
            f"вопросы о данных распознаны {result['data_recall']:.0%} из {result['data_total']}, "
            f"из них не тот вопрос: {result['wrong_data_answer']}; "
            f"вопросы не о данных ушли в данные: {result['false_positive']} "
            f"из {result['not_data_total']}"
        )
        for row in result["errors"]:
            expected, got = row["expected"] or "—", row["got"] or "—"
            print(f"   ✗ {row['text']!r}: ждали {expected}, получили {got}")


if __name__ == "__main__":
    main()
