"""Verify committed exchange packages using the real parser; never mutate the datasets."""

import hashlib
import json
from pathlib import Path

from app.modules.data_exchange.formats import parse_file
from app.modules.planning.case_policy import (
    ObjectiveMetrics,
    case_policy,
    objective_key,
    policy_scenarios,
)

ROOT = Path(__file__).resolve().parents[1]


def verify_packages(root: Path = ROOT) -> dict:
    report = {"files": 0, "format_pairs": 0, "rows_per_pair": {}, "policy_comparisons": 0}
    required = {
        root / "data/planning/manifest.json",
        root / "data/synthetic/standard/manifest.json",
        root / "data/synthetic/large/manifest.json",
        root / "backend/bruno/fixtures/manifest.json",
    }
    manifests = sorted(set((root / "data").rglob("manifest.json")) | required)
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        by_stem = {}
        for name, metadata in manifest["files"].items():
            package = path.parent / name
            content = package.read_bytes()
            if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
                raise ValueError(f"Checksum mismatch: {package}")
            parsed = parse_file(content, name)
            counts = {k: len(v) for k, v in parsed.items()}
            expected = metadata.get("rows", manifest.get("counts"))
            if expected != counts:
                raise ValueError(f"Row counts mismatch: {package}")
            if package.stem in by_stem:
                if parsed != by_stem.pop(package.stem):
                    raise ValueError(f"CSV/XLSX semantic mismatch: {package}")
                report["format_pairs"] += 1
                report["rows_per_pair"][str(package.relative_to(root).with_suffix(""))] = sum(
                    counts.values()
                )
            else:
                by_stem[package.stem] = parsed
            report["files"] += 1
        if by_stem:
            raise ValueError(f"Missing CSV/XLSX counterpart: {path}")
    if (root / "backend/bruno/fixtures/planning-mixed.zip").read_bytes() != (
        root / "data/planning/mixed.zip"
    ).read_bytes():
        raise ValueError("Bruno planning fixture differs from the verified planning package")
    case_policy()
    for example in policy_scenarios(root / "data/planning/policy_objective_cases.json"):
        left, right = [
            objective_key(ObjectiveMetrics.model_validate(x)) for x in example["candidates"]
        ]
        actual = None if left == right else int(right < left)
        if actual != example["winner"]:
            raise ValueError(f"Policy comparison mismatch: {example['id']}")
        report["policy_comparisons"] += 1
    return report


if __name__ == "__main__":
    print(json.dumps(verify_packages(), ensure_ascii=False, indent=2))
