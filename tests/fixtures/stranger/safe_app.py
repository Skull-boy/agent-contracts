"""Negative stranger-test shape: stdlib-only code and a placeholder value."""
import json


def render(payload: dict) -> str:
    api_key = "test-super-secret-token"  # placeholder vocabulary, allowlisted
    return json.dumps({"payload": payload, "key": api_key})
