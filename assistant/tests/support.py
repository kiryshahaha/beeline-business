"""Shared fixtures: the eval contexts double as realistic backend payloads."""

import json
from pathlib import Path

import yaml

CONTEXTS = Path(__file__).resolve().parents[1] / "eval" / "contexts.yaml"


def context_payload(name: str) -> dict:
    """A context exactly as the backend would send it, as JSON-ready data."""
    data = yaml.safe_load(CONTEXTS.read_text(encoding="utf-8"))[name]
    return json.loads(json.dumps(data, default=str))
