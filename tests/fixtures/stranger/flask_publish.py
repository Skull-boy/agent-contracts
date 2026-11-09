"""Stranger-test shape: a Flask-style app that fetches arbitrary URLs and
auto-publishes to GitHub.

The combined import on line 2 is the real-world style that the previous
single-library regex missed.
"""
import os, requests


def auto_publish(url: str, body: str) -> None:
    requests.post(url, json={"body": body}, timeout=5)
