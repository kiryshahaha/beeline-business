"""Benchmark the assistant on the eval set through the same code path as the service.

Questions about the user's day are answered from data; the rest go to the model.
Run from the assistant directory; the model runs need Ollama on OLLAMA_URL:

    python -m eval.run_bench --retrieval-only
    python -m eval.run_bench --facts-only
    python -m eval.run_bench --models qwen3.5:0.8b qwen3.5:2b
"""

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from app.core.config import get_settings
from app.modules.chat.facts import answer_from_facts
from app.modules.chat.knowledge import KnowledgeBase
from app.modules.chat.llm import OllamaClient
from app.modules.chat.schemas import ChatContext, ChatRequest
from app.modules.chat.service import generate, retrieve

EVAL_DIR = Path(__file__).resolve().parent


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def score_answer(answer: str, must: list[list[str]], must_not: list[str]) -> dict:
    text = normalize(answer)
    matched = [any(normalize(str(option)) in text for option in group) for group in must]
    violations = [phrase for phrase in must_not if normalize(phrase) in text]
    return {
        "score": sum(matched) / len(matched) if matched else 1.0,
        "missed": [group for group, ok in zip(must, matched, strict=True) if not ok],
        "violations": violations,
    }


def load_cases() -> list[dict]:
    contexts = yaml.safe_load((EVAL_DIR / "contexts.yaml").read_text(encoding="utf-8"))
    cases = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    for case in cases:
        context = (
            ChatContext.model_validate(contexts[case["context"]]) if "context" in case else None
        )
        case["request"] = ChatRequest(role=case["role"], message=case["question"], context=context)
    return cases


def retrieval_report(cases: list[dict], knowledge: KnowledgeBase, top_k: int) -> tuple[float, list]:
    rows = []
    for case in cases:
        expected = case.get("sources")
        if not expected:
            continue
        found = [chunk.path for chunk in retrieve(case["request"], knowledge, top_k)]
        rows.append((case["id"], any(path in expected for path in found), found, expected))
    hit_rate = sum(hit for _, hit, _, _ in rows) / len(rows)
    return hit_rate, rows


def facts_report(cases: list[dict]) -> list[dict]:
    """Every data question must be answered from data, and correctly."""
    rows = []
    for case in cases:
        fact = answer_from_facts(case["request"])
        if case.get("answered_by") != "facts" and fact is None:
            continue
        row = {"id": case["id"], "expected_facts": case.get("answered_by") == "facts"}
        if fact is None:
            row.update(answer=None, score=0.0, missed=case.get("must", []), violations=[])
        else:
            row.update(
                answer=fact.text,
                **score_answer(fact.text, case.get("must", []), case.get("must_not", [])),
            )
        rows.append(row)
    return rows


def loaded_model_bytes(ollama_url: str, model: str) -> int | None:
    response = httpx.get(f"{ollama_url}/api/ps", timeout=10)
    for item in response.json().get("models", []):
        if item["name"] == model or item["model"] == model:
            return item["size"]
    return None


def unload_all_models(ollama_url: str) -> None:
    """Each model runs alone: several loaded models can exhaust Docker Desktop memory."""
    for item in httpx.get(f"{ollama_url}/api/ps", timeout=10).json().get("models", []):
        httpx.post(
            f"{ollama_url}/api/generate",
            json={"model": item["name"], "keep_alive": 0},
            timeout=60,
        ).raise_for_status()


def run_model(model: str, cases: list[dict], knowledge, client, settings) -> dict:
    warmup = ChatRequest(role="worker", message="Как закрыть заявку?")
    started = time.perf_counter()
    generate(warmup, knowledge, client, settings, model=model)
    warmup_seconds = time.perf_counter() - started
    memory = loaded_model_bytes(settings.ollama_url, model)

    results = []
    for case in cases:
        request = case["request"]
        fact = answer_from_facts(request)
        row = {
            "id": case["id"],
            "role": case["role"],
            "category": case["category"],
            "question": case["question"],
        }
        if fact is not None:
            row.update(
                answer=fact.text,
                source_type="facts",
                sources=[s.section for s in fact.sources],
                total_seconds=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                tokens_per_second=None,
            )
        else:
            reply, chunks = generate(request, knowledge, client, settings, model=model)
            row.update(
                answer=reply.text,
                source_type="knowledge" if chunks else "model",
                sources=[f"{chunk.path} / {chunk.section}" for chunk in chunks],
                total_seconds=reply.total_seconds,
                prompt_tokens=reply.prompt_tokens,
                completion_tokens=reply.completion_tokens,
                tokens_per_second=reply.tokens_per_second,
            )
        row.update(score_answer(row["answer"], case.get("must", []), case.get("must_not", [])))
        results.append(row)
        print(
            f"  {case['id']:<18} {row['source_type']:<9} score={row['score']:.2f} "
            f"{row['total_seconds']:5.1f}s"
        )

    model_rows = [r for r in results if r["source_type"] != "facts"]
    latencies = sorted(r["total_seconds"] for r in model_rows) or [0.0]
    return {
        "model": model,
        "warmup_seconds": warmup_seconds,
        "memory_bytes": memory,
        "avg_score": statistics.mean(r["score"] for r in results),
        "full_marks": sum(r["score"] == 1.0 for r in results),
        "violations": sum(bool(r["violations"]) for r in results),
        "facts_answers": len(results) - len(model_rows),
        "model_answers": len(model_rows),
        "model_avg_score": statistics.mean(r["score"] for r in model_rows) if model_rows else None,
        "avg_seconds": statistics.mean(latencies),
        "p95_seconds": latencies[max(0, round(0.95 * len(latencies)) - 1)],
        "avg_generation_tps": statistics.mean(
            r["tokens_per_second"] for r in model_rows if r["tokens_per_second"]
        )
        if model_rows
        else None,
        "by_category": {
            category: statistics.mean(r["score"] for r in results if r["category"] == category)
            for category in dict.fromkeys(r["category"] for r in results)
        },
        "results": results,
    }


def write_report(out_dir: Path, hit_rate: float, runs: list[dict], top_k: int) -> Path:
    lines = [
        "# Прогон ассистента",
        "",
        f"Поиск по базе знаний: hit@{top_k} = {hit_rate:.0%}",
        "",
        "| Модель | Память | Балл (всё) | Полностью верно | Из данных | Модель"
        " | Балл ответов модели | Ответ модели, с | p95, с | Генерация, ток/с |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        memory = f"{run['memory_bytes'] / 2**30:.2f} ГБ" if run["memory_bytes"] else "?"
        model_score = f"{run['model_avg_score']:.2f}" if run["model_avg_score"] is not None else "—"
        tps = f"{run['avg_generation_tps']:.0f}" if run["avg_generation_tps"] else "—"
        lines.append(
            f"| `{run['model']}` | {memory} | {run['avg_score']:.2f} "
            f"| {run['full_marks']}/{len(run['results'])} | {run['facts_answers']} "
            f"| {run['model_answers']} | {model_score} | {run['avg_seconds']:.1f} "
            f"| {run['p95_seconds']:.1f} | {tps} |"
        )
    categories = list(runs[0]["by_category"]) if runs else []
    if categories:
        lines += ["", "| Модель | " + " | ".join(categories) + " |"]
        lines.append("| --- |" + " --- |" * len(categories))
        for run in runs:
            scores = " | ".join(f"{run['by_category'][c]:.2f}" for c in categories)
            lines.append(f"| `{run['model']}` | {scores} |")
    for run in runs:
        lines += ["", f"## {run['model']}", ""]
        for result in run["results"]:
            flag = " ⚠️ " + ", ".join(result["violations"]) if result["violations"] else ""
            lines += [
                f"### {result['id']} — {result['score']:.2f} ({result['source_type']}){flag}",
                f"**{result['role']}:** {result['question']}",
                "",
                result["answer"],
                "",
            ]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="*", default=[])
    parser.add_argument("--only", help="Comma-separated question ids")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--facts-only", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    knowledge = KnowledgeBase.from_dir(settings.knowledge_dir)
    cases = load_cases()
    if args.only:
        wanted = set(args.only.split(","))
        cases = [case for case in cases if case["id"] in wanted]

    hit_rate, rows = retrieval_report(cases, knowledge, settings.retrieval_top_k)
    print(f"retrieval hit@{settings.retrieval_top_k}: {hit_rate:.0%}")
    for case_id, hit, found, expected in rows:
        if not hit:
            print(f"  MISS {case_id}: expected {expected}, found {found}")

    facts = facts_report(cases)
    expected = [row for row in facts if row["expected_facts"]]
    exact = sum(row["score"] == 1.0 for row in expected)
    print(f"facts: {exact}/{len(expected)} вопросов о данных отвечены из данных полностью верно")
    for row in facts:
        if not row["expected_facts"]:
            print(f"  ЛИШНИЙ ответ из данных {row['id']}: {row['answer']}")
        elif row["score"] < 1.0:
            print(f"  ✗ {row['id']}: не хватает {row['missed']} — {row['answer']}")
    if args.retrieval_only or args.facts_only:
        return

    out_dir = EVAL_DIR / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    client = OllamaClient(settings.ollama_url, settings.llm_timeout_seconds)
    runs = []
    try:
        for model in args.models:
            print(f"model {model}")
            unload_all_models(settings.ollama_url)
            run = run_model(model, cases, knowledge, client, settings)
            runs.append(run)
            safe_name = model.replace("/", "_").replace(":", "_")
            (out_dir / f"{safe_name}.json").write_text(
                json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        client.close()
    print(write_report(out_dir, hit_rate, runs, settings.retrieval_top_k))


if __name__ == "__main__":
    main()
