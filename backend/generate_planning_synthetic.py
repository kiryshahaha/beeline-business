"""Export six reproducible planner scenarios and verify CSV/XLSX semantic equality."""

import argparse
import hashlib
import json
from pathlib import Path

from app.modules.data_exchange.formats import parse_file, serialize
from planning_scenarios import SCENARIOS, generate_planning_dataset


def generate(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"seed": 1900, "route_date": "2030-01-15", "files": {}}
    for scenario in SCENARIOS:
        data = generate_planning_dataset(scenario)
        canonical = None
        for fmt, ext in (("csv", "zip"), ("xlsx", "xlsx")):
            content = serialize(data, fmt)
            filename = f"{scenario}.{ext}"
            parsed = parse_file(content, filename)
            if canonical is not None and parsed != canonical:
                raise AssertionError(f"CSV/XLSX mismatch: {scenario}")
            canonical = parsed
            (output / filename).write_bytes(content)
            manifest["files"][filename] = {
                "sha256": hashlib.sha256(content).hexdigest(),
                "rows": {k: len(v) for k, v in parsed.items()},
            }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/planning-synthetic"))
    print(json.dumps(generate(parser.parse_args().output), indent=2))
