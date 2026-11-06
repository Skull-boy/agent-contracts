"""Build the RFC 0003 §C6 release attestation bundle (roadmap M3.3).

The bundle binds the three facts a consumer needs to decide whether an
installed wheel is the artifact the project intended to ship:

- ``wheel_hash`` — SHA-256 of the exact wheel bytes already published to PyPI;
- ``schema_version`` — the supported contract schema version (``"1.1"``);
- ``adapter_floors`` — the current library-scope adapter floors. ``n8n`` and
  ``langgraph`` both ship at ``"1.0"``; these are floors for the adapters that
  live in this repository today, not a promise about future optional adapters;
- ``self_check_manifest`` — the M3.4 self-check manifest embedded by value, so
  verification material travels with the attestation.

The output is deterministic (sorted keys, compact provenance, no timestamps):
the release attestation itself carries the signed time, and embedding a wall
clock here would make otherwise-identical bundles byte-different.

Usage::

    python tools/build_release_manifest.py --wheel dist/scyvera-1.3.0-py3-none-any.whl \\
        --self-manifest dist/installed/scyvera/_self_manifest.json \\
        --output dist/release-manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

__all__ = ["ADAPTER_FLOORS", "RELEASE_MANIFEST_VERSION", "SUPPORTED_SCHEMA_VERSION", "build_release_manifest", "main"]

#: Schema version of the release-manifest document itself.
RELEASE_MANIFEST_VERSION: str = "1"

#: Supported contract schema version bound into the bundle (RFC 0003 §C6).
SUPPORTED_SCHEMA_VERSION: str = "1.1"

#: Current library-scope adapter floors (see module docstring).
ADAPTER_FLOORS: dict[str, str] = {
    "langgraph": "1.0",
    "n8n": "1.0",
}


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_manifest(
    wheel: Path,
    self_manifest: Path,
    *,
    schema_version: str = SUPPORTED_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build the deterministic release manifest for ``wheel``.

    Args:
        wheel: The exact built wheel being attested.
        self_manifest: The M3.4 manifest generated from the installed wheel.
        schema_version: Supported contract schema version string.

    Returns:
        A JSON-serializable attestation bundle with the self-check manifest
        embedded by value.
    """
    if not wheel.is_file():
        raise FileNotFoundError(f"wheel not found: {wheel}")
    if not self_manifest.is_file():
        raise FileNotFoundError(f"self manifest not found: {self_manifest}")

    try:
        manifest_object = json.loads(self_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"self manifest '{self_manifest}' is not valid JSON: {error}"
        ) from error
    if not isinstance(manifest_object, dict):
        raise ValueError("self manifest root must be a JSON object")

    return {
        "release_manifest_version": RELEASE_MANIFEST_VERSION,
        "wheel_filename": wheel.name,
        "wheel_hash": _sha256_file(wheel),
        "schema_version": schema_version,
        "adapter_floors": dict(sorted(ADAPTER_FLOORS.items())),
        "self_check_manifest": manifest_object,
    }


def main(argv: list[str] | None = None) -> int:
    """Generate the release manifest and return a process exit code."""
    parser = argparse.ArgumentParser(
        prog="python tools/build_release_manifest.py",
        description=(
            "Build the RFC 0003 §C6 release attestation bundle binding the "
            "wheel hash, schema version, adapter floors, and self-check "
            "manifest."
        ),
    )
    parser.add_argument("--wheel", type=Path, required=True, help="Built wheel")
    parser.add_argument(
        "--self-manifest",
        type=Path,
        required=True,
        help="Self-check manifest generated from the installed wheel",
    )
    parser.add_argument(
        "--schema-version",
        default=SUPPORTED_SCHEMA_VERSION,
        help="Supported contract schema version (default: 1.1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/release-manifest.json"),
        help="Destination release-manifest JSON",
    )
    args = parser.parse_args(argv)

    try:
        payload = build_release_manifest(
            args.wheel,
            args.self_manifest,
            schema_version=args.schema_version,
        )
    except (OSError, ValueError) as error:
        print(
            f"error: cannot build release manifest: {error}",
            file=sys.stderr,
        )
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
