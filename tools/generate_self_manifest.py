"""Generate the M3.4 package self-manifest (RFC 0003 §C2, roadmap M3.3/M3.4).

The canonical manifest lives at ``src/scyvera/_self_manifest.json`` and is
packaged into the wheel. Release attestation regenerates it from the *installed
wheel tree* (RFC 0003 §C6) so the manifest always describes the exact bytes
being attested, not the source checkout.

Usage::

    python -m tools.generate_self_manifest
    python -m tools.generate_self_manifest --installed /path/to/site-packages

The second form writes the manifest back into the installed ``scyvera`` package
directory, which is what the release-attest workflow records and verifies.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from scyvera.selfcheck import SELF_MANIFEST_FILENAME, generate_manifest

__all__ = ["main"]

#: Repository root (``tools/`` lives directly under it).
ROOT = Path(__file__).resolve().parent.parent

#: Source-layout package directory used by default.
DEFAULT_PACKAGE_PATH = ROOT / "src" / "scyvera"


def _resolve_package_path(installed: Path | None) -> Path | None:
    """Return the package directory to walk, or ``None`` when unusable.

    ``--installed`` accepts either a ``site-packages`` directory that contains
    ``scyvera/`` or the package directory itself. Nothing else is accepted: a
    silent fallback to walking the caller's directory would hash unrelated
    files into a manifest that is then signed.
    """
    if installed is None:
        return DEFAULT_PACKAGE_PATH
    candidate = installed / "scyvera"
    if candidate.is_dir():
        return candidate
    if (installed / "__init__.py").is_file():
        return installed
    return None


def main(argv: list[str] | None = None) -> int:
    """Write the canonical self manifest and return a process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.generate_self_manifest",
        description=(
            "Generate scyvera/_self_manifest.json (RFC 0003 §C2) with "
            "deterministic, sorted SHA-256 entries."
        ),
    )
    parser.add_argument(
        "--installed",
        type=Path,
        default=None,
        metavar="SITE_PACKAGES",
        help=(
            "Walk an installed site-packages directory (or the scyvera "
            "package directory) instead of src/scyvera; the manifest is "
            "written back into that package for release attestation."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Explicit manifest path; defaults to "
            "<package>/_self_manifest.json"
        ),
    )
    args = parser.parse_args(argv)

    package_path = _resolve_package_path(args.installed)
    if package_path is None or not package_path.is_dir():
        target = args.installed if args.installed is not None else DEFAULT_PACKAGE_PATH
        print(
            f"error: no scyvera package found under {target} "
            "(pass a site-packages directory containing scyvera/, or the "
            "package directory itself)",
            file=sys.stderr,
        )
        return 2

    output = args.output or (package_path / SELF_MANIFEST_FILENAME)
    try:
        manifest = generate_manifest(package_path)
    except Exception as error:  # fail closed with one actionable line
        print(f"error: cannot generate self manifest: {error}", file=sys.stderr)
        return 2

    try:
        output.write_bytes(manifest)
    except OSError as error:
        print(f"error: cannot write {output}: {error}", file=sys.stderr)
        return 2

    print(f"wrote {output} ({len(manifest)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
