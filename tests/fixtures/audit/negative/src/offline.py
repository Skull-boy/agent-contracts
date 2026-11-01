"""Negative fixture for AU-NET-002: stdlib-only local computation."""
import json


def render(payload: dict) -> str:
    return json.dumps(payload)
