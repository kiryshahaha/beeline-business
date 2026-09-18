"""Benchmark chat models on the eval set through the same code path as the service.

Run from the assistant directory with Ollama listening on OLLAMA_URL:

    python -m eval.run_bench --retrieval-only
    python -m eval.run_bench --models qwen3.5:0.8b qwen3:0.6b
"""

import argparse
import json
import statistics
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from app.core.config import get_settings
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
    warmup = ChatRequest(role="worker", message="Привет")
    started = time.perf_counter()
    reply, _ = generate(warmup, knowledge, client, settings, model=model)
    warmup_seconds = time.perf_counter() - started
    memory = loaded_model_bytes(settings.ollama_url, model)

    results = []
    for case in cases:
        reply, chunks = generate(case["request"], knowledge, client, settings, model=model)
        results.append(
            {
                "id": case["id"],
                "role": case["role"],
                "category": case["category"],
                "question": case["question"],
                "answer": reply.text,
                "sources": [f"{chunk.path} / {chunk.section}" for chunk in chunks],
                **score_answer(reply.text, case.get("must", []), case.get("must_not", [])),
                **{key: value for key, value in asdict(reply).items() if key != "text"},
                "tokens_per_second": reply.tokens_per_second,
            }
        )
        print(f"  {case['id']:<18} score={results[-1]['score']:.2f} {reply.total_seconds:5.1f}s")

    latencies = sorted(result["total_seconds"] for result in results)
    return {
        "model": model,
        "warmup_seconds": warmup_seconds,
        "memory_bytes": memory,
        "avg_score": statistics.mean(result["score"] for result in results),
        "full_marks": sum(result["score"] == 1.0 for result in results),
        "violations": sum(bool(result["violations"]) for result in results),
        "avg_seconds": statistics.mean(latencies),
        "p95_seconds": latencies[max(0, round(0.95 * len(latencies)) - 1)],
        "avg_prompt_tokens": statistics.mean(result["prompt_tokens"] for result in results),
        "avg_prompt_tps": statistics.mean(
            r["prompt_tokens"] / r["prompt_seconds"] for r in results if r["prompt_seconds"]
        ),
        "avg_generation_tps": statistics.mean(result["tokens_per_second"] for result in results),
        "by_category": {
            category: statistics.mean(r["score"] for r in results if r["category"] == category)
            for category in dict.fromkeys(result["category"] for result in results)
        },
        "results": results,
    }


def write_report(out_dir: Path, hit_rate: float, runs: list[dict], top_k: int) -> Path:
    lines = [
        "# Прогон ассистента",
        "",
        f"Поиск по базе знаний: hit@{top_k} = {hit_rate:.0%}",
        "",
        "| Модель | Память | Средний балл | Полностью верно | Нарушения | Ср. время, с"
        " | p95, с | Промпт, ток/с | Генерация, ток/с |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        memory = f"{run['memory_bytes'] / 2**30:.2f} ГБ" if run["memory_bytes"] else "?"
        lines.append(
            f"| `{run['model']}` | {memory} | {run['avg_score']:.2f} "
            f"| {run['full_marks']}/{len(run['results'])} | {run['violations']} "
            f"| {run['avg_seconds']:.1f} | {run['p95_seconds']:.1f} "
            f"| {run['avg_prompt_tps']:.0f} | {run['avg_generation_tps']:.0f} |"
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
                f"### {result['id']} — {result['score']:.2f}{flag}",
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
    if args.retrieval_only:
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
