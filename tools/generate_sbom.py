"""Generate a deterministic minimal CycloneDX 1.5 SBOM (RFC 0003 §C6, M3.3).

No third-party SBOM tool is involved. The component is the scyvera wheel
passed on the command line (name/version read from ``pyproject.toml`` via
:mod:`tomllib`; the wheel SHA-256 is computed here). Dependency components are
the declared runtime dependencies parsed from ``pyproject.toml`` with versions
read from the interpreter environment the wheel was installed into.

``pydantic`` is recorded when present because the optional qdrant gateway path
pulls it in transitively; it is *not* a direct ``project.dependencies`` entry.
Omitting absent optional packages keeps the SBOM a truthful snapshot of the
attested environment rather than a wish list.

Usage::

    python tools/generate_sbom.py --wheel dist/scyvera-1.3.0-py3-none-any.whl \
        --output dist/scyvera.cdx.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
from typing import Any

try:  # Python 3.11+; release tooling runs on the workflow's 3.12 interpreter.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 dev fallback
    tomllib = None  # type: ignore[assignment]

__all__ = ["build_sbom", "main"]

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"
_SPEC_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_PURL_SAFE = re.compile(r"[-_.]+")


def _load_project(pyproject: Path) -> dict[str, Any]:
    """Load ``[project]`` from pyproject.toml."""
    if tomllib is None:
        raise RuntimeError("generate_sbom.py requires Python 3.11+ (tomllib)")
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"{pyproject} has no [project] table")
    return project


def _normalized_purl_name(name: str) -> str:
    """Normalize a distribution name for a PyPI purl."""
    return _PURL_SAFE.sub("-", name).lower()


def _dependency_names(project: dict[str, Any]) -> list[str]:
    """Return direct dependency names declared in pyproject order."""
    raw = project.get("dependencies", [])
    if not isinstance(raw, list):
        raise ValueError("[project].dependencies must be a list")
    names: list[str] = []
    for spec in raw:
        if not isinstance(spec, str):
            raise ValueError("dependency specifications must be strings")
        match = _SPEC_NAME.match(spec)
        if match is None:
            raise ValueError(f"cannot parse dependency specification: {spec!r}")
        names.append(match.group(1))
    return names


def _installed_version(name: str) -> str | None:
    """Return the installed version for ``name``, or ``None`` when absent."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dependency_component(
    name: str,
    version: str,
    *,
    scope: str = "required",
) -> dict[str, Any]:
    """Build one CycloneDX library component."""
    purl = f"pkg:pypi/{_normalized_purl_name(name)}@{version}"
    return {
        "type": "library",
        "name": name,
        "version": version,
        "purl": purl,
        "bom-ref": purl,
        "scope": scope,
    }


def build_sbom(pyproject: Path, wheel: Path) -> dict[str, Any]:
    """Build the CycloneDX 1.5 document for ``wheel``.

    Args:
        pyproject: Path to the package's ``pyproject.toml``.
        wheel: Built wheel whose hash is bound into the SBOM.

    Returns:
        A JSON-serializable CycloneDX 1.5 dictionary (no timestamps, sorted
        components, deterministic bytes).
    """
    project = _load_project(pyproject)
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("[project].name and [project].version must be strings")
    if not wheel.is_file():
        raise FileNotFoundError(f"wheel not found: {wheel}")

    purl = f"pkg:pypi/{_normalized_purl_name(name)}@{version}"
    components: list[dict[str, Any]] = []

    for dependency in _dependency_names(project):
        installed = _installed_version(dependency)
        if installed is None:
            raise RuntimeError(
                f"declared runtime dependency '{dependency}' is not installed "
                "in the SBOM-generation environment"
            )
        components.append(_dependency_component(dependency, installed))

    pydantic_version = _installed_version("pydantic")
    if pydantic_version is not None:
        components.append(
            _dependency_component(
                "pydantic",
                pydantic_version,
                scope="optional",
            )
        )

    components.sort(key=lambda component: component["name"].lower())
    depends_on = [component["bom-ref"] for component in components]

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "scyvera-generate-sbom",
                        "version": "1",
                    }
                ]
            },
            "component": {
                "type": "library",
                "name": name,
                "version": version,
                "purl": purl,
                "bom-ref": purl,
                "licenses": [{"license": {"id": "MIT"}}],
                "hashes": [
                    {"alg": "SHA-256", "content": _sha256_file(wheel)}
                ],
            },
        },
        "components": components,
        "dependencies": [{"ref": purl, "dependsOn": depends_on}],
    }


def main(argv: list[str] | None = None) -> int:
    """Generate the SBOM and return a process exit code."""
    parser = argparse.ArgumentParser(
        prog="python tools/generate_sbom.py",
        description=(
            "Generate a deterministic minimal CycloneDX 1.5 SBOM for the "
            "scyvera wheel (RFC 0003 §C6)."
        ),
    )
    parser.add_argument("--wheel", type=Path, required=True, help="Built wheel")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=DEFAULT_PYPROJECT,
        help="pyproject.toml to read name/version/dependencies from",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/scyvera.cdx.json"),
        help="Destination SBOM JSON",
    )
    args = parser.parse_args(argv)

    try:
        payload = build_sbom(args.pyproject, args.wheel)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: cannot build SBOM: {error}", file=sys.stderr)
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
