"""Write a small, secret-free description of the environment used by backend CI."""

import argparse
import json
import os
import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from sqlalchemy import create_engine, text

from seed_synthetic import validate_database_url


def command_version(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.strip() or result.stderr.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = validate_database_url(os.environ.get("TEST_DATABASE_URL", ""))
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            postgres_version = connection.execute(text("SHOW server_version")).scalar_one()
    finally:
        engine.dispose()

    packages = {}
    for package in ("alembic", "fastapi", "httpx", "ortools", "psycopg", "ruff", "sqlalchemy"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            continue

    try:
        sha = os.environ["GITHUB_SHA"]
    except KeyError:
        sha = command_version(["git", "rev-parse", "HEAD"])
    report = {
        "commit_sha": sha,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "node": command_version(["node", "--version"]),
        "bruno_cli": "4.1.0",
        "postgresql": postgres_version,
        "packages": packages,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Environment report written to {args.output}")


if __name__ == "__main__":
    main()
