"""Positive fixture: AU-NET-002 (outbound HTTP client)."""
import requests


def fetch_status(url: str) -> int:
    return requests.get(url, timeout=5).status_code
