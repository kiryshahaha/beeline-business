"""Verify committed exchange packages using the real parser; never mutate the datasets."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.modules.data_exchange.formats import parse_file
from app.modules.planning.case_policy import (
    ObjectiveMetrics,
    case_policy,
    objective_key,
    policy_scenarios,
)

ROOT = Path(__file__).resolve().parents[1]


def verify_auxiliary_files(directory: Path, manifest: dict) -> int:
    """Check non-import files that belong to a synthetic acceptance package."""
    for name, metadata in manifest.get("auxiliary_files", {}).items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Invalid auxiliary path: {name}")
        path = directory / relative
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
            raise ValueError(f"Checksum mismatch: {path}")
        if len(content) != metadata["bytes"]:
            raise ValueError(f"Size mismatch: {path}")
    return len(manifest.get("auxiliary_files", {}))


def verify_packages(root: Path = ROOT) -> dict:
    report = {
        "files": 0,
        "format_pairs": 0,
        "rows_per_pair": {},
        "policy_comparisons": 0,
        "dynamic_replanning_cases": 0,
        "auxiliary_files": 0,
    }
    required = {
        root / "data/planning/manifest.json",
        root / "data/synthetic/standard/manifest.json",
        root / "data/synthetic/acceptance/manifest.json",
        root / "data/synthetic/large/manifest.json",
        root / "backend/bruno/fixtures/manifest.json",
    }
    manifests = sorted(set((root / "data").rglob("manifest.json")) | required)
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        report["auxiliary_files"] += verify_auxiliary_files(path.parent, manifest)
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
    dynamic = json.loads(
        (root / "data/planning/dynamic_replanning_scenarios.json").read_text(encoding="utf-8")
    )
    if dynamic.get("schema_version") != 1 or dynamic.get("timezone") != "Europe/Moscow":
        raise ValueError("Unsupported dynamic replanning scenario contract")
    for field, minimum in (
        ("active_stage_cases", 3),
        ("ordinary_insert_cases", 2),
        ("response_cases", 3),
    ):
        cases = dynamic.get(field)
        if not isinstance(cases, list) or len(cases) < minimum:
            raise ValueError(f"Dynamic replanning scenarios need at least {minimum} {field}")
        ids = [case.get("id") for case in cases]
        if any(not item for item in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"Dynamic replanning {field} require unique non-empty ids")
        for case in cases:
            timestamps = [
                value
                for name, value in case.items()
                if name.endswith(("_at", "received_at", "actual_completed_at"))
            ]
            if field == "ordinary_insert_cases":
                timestamps.extend(case.get("published_service_starts", []))
                timestamps.extend(case.get("new_visit_window", []))
            if not timestamps:
                raise ValueError(f"Dynamic replanning case has no timestamps: {case['id']}")
            for value in timestamps:
                if not isinstance(value, str):
                    raise ValueError(f"Dynamic replanning timestamp must be a string: {case['id']}")
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError(
                        f"Dynamic replanning timestamp must include timezone: {case['id']}"
                    )
            report["dynamic_replanning_cases"] += 1
    return report


if __name__ == "__main__":
    print(json.dumps(verify_packages(), ensure_ascii=False, indent=2))
