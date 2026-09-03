#!/usr/bin/env python3
"""
PR Contract Validator Script

Validates changed YAML contract files in a pull request using scyvera.validate_contract()
and outputs structured markdown results for PR commenting and GitHub Actions step summaries.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from scyvera import validate_contract

AGENT_CONTRACT_PATH = ".github/agents/contract-validator/contract.yaml"


def validate_files(files: list[str | Path]) -> tuple[int, int, str]:
    ROOT = Path.cwd()
    passed = 0
    failed = 0
    details: list[str] = []

    for f in files:
        p = Path(f)
        if not p.is_file():
            continue

        try:
            rel_path = p.relative_to(ROOT) if (p.is_absolute() and p.is_relative_to(ROOT)) else p
        except AttributeError:
            # Python < 3.9 compatibility fallback
            try:
                rel_path = p.relative_to(ROOT) if p.is_absolute() else p
            except ValueError:
                rel_path = p
        except ValueError:
            rel_path = p

        try:
            res = validate_contract(p)
            if res.valid:
                passed += 1
                details.append(f"- `PASS` **`{rel_path}`**")
            else:
                failed += 1
                error_list = "\n".join(
                    f"  - `{e.path}`: {e.message}" if e.path else f"  - {e.message}"
                    for e in res.errors
                )
                details.append(f"- `FAIL` **`{rel_path}`**\n{error_list}")
        except (OSError, yaml.YAMLError, Exception) as exc:
            failed += 1
            details.append(f"- `FAIL` **`{rel_path}`**\n  - Error: {exc}")

    status_icon = "PASS" if failed == 0 else "WARNING"
    summary_header = f"### Contract Governance Report ({status_icon})\n\n"
    summary_body = (
        f"**Governed Agent**: [`contract-validator`]({AGENT_CONTRACT_PATH})\n\n"
        f"**Results Summary**:\n"
        f"- Total contracts evaluated: `{passed + failed}`\n"
        f"- Valid contracts: `{passed}`\n"
        f"- Violations / errors: `{failed}`\n\n"
    )

    if details:
        summary_body += "**File Details**:\n" + "\n".join(details) + "\n\n"
    else:
        summary_body += "No YAML contracts found to evaluate in this PR diff.\n\n"

    summary_body += (
        "> *Note: This check is advisory and enforces self-governance under the Agent Contract specification.*"
    )

    markdown_report = summary_header + summary_body
    return passed, failed, markdown_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PR Contract YAML files")
    parser.add_argument(
        "--files",
        nargs="*",
        default=[],
        help="List of changed YAML file paths to validate",
    )
    parser.add_argument(
        "--output-md",
        default="",
        help="Path to write the markdown summary output",
    )

    args = parser.parse_args()

    files = [Path(f) for f in args.files if f.endswith((".yaml", ".yml"))]
    passed, failed, report = validate_files(files)

    print(report)

    if args.output_md:
        out_path = Path(args.output_md)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
