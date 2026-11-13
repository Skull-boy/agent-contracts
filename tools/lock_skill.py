"""Hash-lock the M3.1 harness skill (roadmap M3.1).

Walks ``skills/scyvera-governance/``, hashes every file with SHA-256 in sorted
path order, and writes the skill's entry to ``skills-registry.json``. The
registry follows the ecosystem lock format already used by ``skills-lock.json``
(top-level ``version`` plus a ``skills`` map keyed by skill name), extended
additively with a per-file ``files`` map so drift can be localized.

Determinism is a hard requirement: sorted keys, no timestamps, no hostnames,
no absolute paths, and a trailing newline. Running the script twice produces
byte-identical output.

Usage::

    python -m tools.lock_skill            # write / update the registry
    python -m tools.lock_skill --verify   # recompute every hash, fail closed

Exit codes: ``0`` clean, ``1`` drift detected (verify), ``2`` usage or a
missing/corrupt registry.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "scyvera-governance"
SKILL_DIR = REPO_ROOT / "skills" / SKILL_NAME
REGISTRY_PATH = REPO_ROOT / "skills-registry.json"
SOURCE = "Skull-boy/agent-contracts"
SOURCE_TYPE = "github"
REGISTRY_VERSION = 1


def _sha256(path: Path) -> str:
    """Return the lowercase SHA-256 of ``path`` read as bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    """Return a POSIX repo-relative path, independent of the host separator."""
    return path.relative_to(REPO_ROOT).as_posix()


def installed_version() -> str:
    """Return the installed scyvera release, or ``"unknown"`` off-wheel."""
    try:
        return importlib.metadata.version("scyvera")
    except Exception:
        return "unknown"


def skill_files(skill_dir: Path = SKILL_DIR) -> dict[str, str]:
    """Map every file under ``skill_dir`` to its SHA-256, sorted by path."""
    files: dict[str, str] = {}
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        files[_repo_relative(path)] = _sha256(path)
    return dict(sorted(files.items()))


def build_entry(
    name: str = SKILL_NAME,
    skill_dir: Path = SKILL_DIR,
    version: str | None = None,
) -> dict[str, Any]:
    """Build one deterministic registry entry for the skill."""
    files = skill_files(skill_dir)
    skill_path = _repo_relative(skill_dir / "SKILL.md")
    if skill_path not in files:
        raise FileNotFoundError(f"SKILL.md not found under {skill_dir}")
    return {
        "source": SOURCE,
        "sourceType": SOURCE_TYPE,
        "skillPath": skill_path,
        # Ecosystem field: one hash for the skill entry point.
        "computedHash": files[skill_path],
        "version": installed_version() if version is None else version,
        "locked_at_version": installed_version() if version is None else version,
        "files": files,
    }


def build_registry(
    name: str = SKILL_NAME,
    skill_dir: Path = SKILL_DIR,
    version: str | None = None,
) -> dict[str, Any]:
    """Build the whole registry envelope from disk."""
    return {
        "version": REGISTRY_VERSION,
        "skills": {name: build_entry(name=name, skill_dir=skill_dir, version=version)},
    }


def render_registry(registry: Mapping[str, Any]) -> str:
    """Serialize a registry deterministically (sorted keys, 2-space indent)."""
    return json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_registry(
    registry_path: Path = REGISTRY_PATH,
    name: str = SKILL_NAME,
    skill_dir: Path = SKILL_DIR,
    version: str | None = None,
) -> dict[str, Any]:
    """Write or update one skill entry, preserving any other skills."""
    existing: dict[str, Any] = {"version": REGISTRY_VERSION, "skills": {}}
    if registry_path.exists():
        existing = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise ValueError("registry root must be an object")
        existing.setdefault("version", REGISTRY_VERSION)
        existing.setdefault("skills", {})
        if not isinstance(existing["skills"], dict):
            raise ValueError("registry 'skills' must be an object")

    existing["skills"][name] = build_entry(
        name=name, skill_dir=skill_dir, version=version
    )
    registry_path.write_text(render_registry(existing), encoding="utf-8", newline="\n")
    return existing


def verify_registry(
    registry_path: Path = REGISTRY_PATH,
    name: str = SKILL_NAME,
    skill_dir: Path = SKILL_DIR,
) -> list[str]:
    """Recompute every locked hash; return a list of human-readable problems."""
    if not registry_path.is_file():
        return [f"registry not found: {registry_path}"]
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read registry: {error}"]

    if not isinstance(registry, dict) or registry.get("version") != REGISTRY_VERSION:
        return [f"unsupported registry version: {registry!r}"]
    skills = registry.get("skills")
    if not isinstance(skills, dict) or name not in skills:
        return [f"skill not locked: {name}"]

    entry = skills[name]
    locked = entry.get("files") if isinstance(entry, dict) else None
    if not isinstance(locked, dict) or not locked:
        return [f"skill entry has no file map: {name}"]

    problems: list[str] = []
    for relative, expected in sorted(locked.items()):
        path = REPO_ROOT / relative
        if not path.is_file():
            problems.append(f"missing: {relative}")
            continue
        actual = _sha256(path)
        if actual != expected:
            problems.append(f"modified: {relative} (expected {expected}, actual {actual})")

    on_disk = set(skill_files(skill_dir))
    for extra in sorted(on_disk - set(locked)):
        problems.append(f"unlisted: {extra}")

    skill_path = entry.get("skillPath")
    computed = entry.get("computedHash")
    if isinstance(skill_path, str):
        path = REPO_ROOT / skill_path
        if path.is_file() and _sha256(path) != computed:
            problems.append(f"computedHash mismatch: {skill_path}")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.lock_skill",
        description="Hash-lock the scyvera-governance skill.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Recompute every locked hash and fail closed on drift.",
    )
    args = parser.parse_args(argv)

    if args.verify:
        problems = verify_registry()
        if problems:
            print("lock_skill: drift detected", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        entry = build_entry()
        print(
            f"lock_skill: {len(entry['files'])} files match "
            f"{REGISTRY_PATH.name} (scyvera {entry['locked_at_version']})"
        )
        return 0

    try:
        registry = write_registry()
    except (OSError, ValueError, FileNotFoundError, json.JSONDecodeError) as error:
        print(f"lock_skill: error: {error}", file=sys.stderr)
        return 2

    entry = registry["skills"][SKILL_NAME]
    print(
        f"lock_skill: wrote {REGISTRY_PATH.name} "
        f"({len(entry['files'])} files, scyvera {entry['locked_at_version']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
