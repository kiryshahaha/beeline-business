"""Compare the base and fine-tuned model on the questions that reach the model.

Runs with MLX on the Mac, with the service's own retrieval and prompt code, so the base
and the adapter see identical prompts. Data questions answered by facts.py are skipped:
the model never sees them in production.

    python finetune/evaluate.py --model <base> [--adapter <adapters>] --out result.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

ASSISTANT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ASSISTANT))

import mlx.core as mx  # noqa: E402
from mlx_lm import generate, load  # noqa: E402
from mlx_lm.sample_utils import make_logits_processors, make_sampler  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.modules.chat.facts import answer_from_facts  # noqa: E402
from app.modules.chat.knowledge import KnowledgeBase  # noqa: E402
from app.modules.chat.prompts import build_messages  # noqa: E402
from app.modules.chat.service import retrieve  # noqa: E402
from eval.run_bench import load_cases, score_answer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    settings = get_settings()
    knowledge = KnowledgeBase.from_dir(settings.knowledge_dir)
    model, tokenizer = load(args.model, adapter_path=args.adapter)
    # Same sampling as the Ollama client in app/modules/chat/llm.py.
    sampler = make_sampler(temp=settings.llm_temperature, top_p=0.8, top_k=20)
    processors = make_logits_processors(repetition_penalty=1.1)

    results = []
    for case in load_cases():
        request = case["request"]
        if answer_from_facts(request) is not None:
            continue
        chunks = retrieve(request, knowledge, settings.retrieval_top_k)
        prompt = tokenizer.apply_chat_template(
            build_messages(request, chunks),
            add_generation_prompt=True,
            enable_thinking=False,
            tokenize=False,
        )
        mx.random.seed(0)
        started = time.perf_counter()
        answer = generate(
            model,
            tokenizer,
            prompt,
            max_tokens=settings.llm_max_tokens,
            sampler=sampler,
            logits_processors=processors,
        ).strip()
        row = {
            "id": case["id"],
            "role": case["role"],
            "category": case["category"],
            "question": case["question"],
            "answer": answer,
            "seconds": round(time.perf_counter() - started, 1),
            **score_answer(answer, case.get("must", []), case.get("must_not", [])),
        }
        results.append(row)
        print(f"{row['id']:<18} {row['score']:.2f} {row['seconds']:5.1f}s", flush=True)

    summary = {
        "model": args.model,
        "adapter": args.adapter,
        "questions": len(results),
        "avg_score": sum(r["score"] for r in results) / len(results),
        "full_marks": sum(r["score"] == 1.0 for r in results),
        "results": results,
    }
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"средний балл {summary['avg_score']:.2f}, полностью верно {summary['full_marks']}")


if __name__ == "__main__":
    main()
