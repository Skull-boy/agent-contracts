import argparse
import sys
from pathlib import Path

import yaml

from .linter import lint_contract
from .validator import validate_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-contract",
        description="Validate and manage Agent Contract files.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # validate subcommand
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an Agent Contract against its specification schema.",
    )

    validate_parser.add_argument(
        "contract",
        type=Path,
        help="Path to contract.yaml",
    )

    validate_parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to custom JSON Schema file",
    )

    # lint subcommand
    lint_parser = subparsers.add_parser(
        "lint",
        help="Perform Tier 2 semantic analysis on an Agent Contract.",
    )

    lint_parser.add_argument(
        "contract",
        type=Path,
        help="Path to contract.yaml",
    )

    # init subcommand
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize a new Agent Contract starter template.",
    )

    init_parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=Path("contract.yaml"),
        help="Target output path (default: contract.yaml)",
    )

    init_parser.add_argument(
        "--name",
        type=str,
        default="My System",
        help="System or agent name",
    )

    init_parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Operational domain (e.g. healthcare, finance, education, research, software, business)",
    )

    init_parser.add_argument(
        "--spec-version",
        type=str,
        choices=["1.1", "1"],
        default="1.1",
        help="Specification version (default: 1.1)",
    )

    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite target file if it already exists",
    )

    init_parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Prompt interactively for contract details",
    )

    return parser


def run_validate(contract_path: Path, schema_path: Path | None = None) -> int:
    try:
        result = validate_contract(contract_path, schema_path=schema_path)

    except FileNotFoundError:
        print(f"ERROR  {contract_path}")
        print("       file not found")
        return 2

    except PermissionError:
        print(f"ERROR  {contract_path}")
        print("       permission denied")
        return 2

    except yaml.YAMLError as error:
        print(f"FAIL  {contract_path}")
        print(f"      invalid YAML: {error}")
        return 1

    if result.valid:
        print(f"PASS  {contract_path}")
        return 0

    print(f"FAIL  {contract_path}")

    for error in result.errors:
        if error.path:
            print(f"      {error.path}: {error.message}")
        else:
            print(f"      {error.message}")

    return 1


def run_init(
    output_path: Path,
    name: str = "My System",
    domain: str | None = None,
    spec_version: str = "1.1",
    force: bool = False,
    interactive: bool = False,
) -> int:
    if output_path.exists() and not force:
        print(f"ERROR  {output_path} already exists. Use --force to overwrite.")
        return 1

    purpose = "Operational contract for intelligent/automated system"
    risk_level = "low"

    if interactive:
        try:
            user_name = input(f"System Name [{name}]: ").strip()
            if user_name:
                name = user_name
            user_domain = input("Domain (e.g. healthcare, finance, education, research, software, business): ").strip()
            if user_domain:
                domain = user_domain
            user_purpose = input("Purpose/Description: ").strip()
            if user_purpose:
                purpose = user_purpose
            user_risk = input("Risk Level (low/medium/high/critical) [low]: ").strip()
            if user_risk in ("low", "medium", "high", "critical"):
                risk_level = user_risk
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if spec_version == "1.1":
        contract_data: dict[str, Any] = {
            "version": 1.1,
            "system": {
                "name": name,
                "purpose": purpose,
                "version": "1.0.0",
            },
        }
        if domain:
            contract_data["domain"] = domain

        contract_data.update({
            "capabilities": [
                {"name": "example_capability", "description": "Example capability claim"}
            ],
            "resources": [
                {"name": "example_resource", "type": "dataset", "access": "read"}
            ],
            "inputs": [
                {"name": "example_input", "type": "string", "required": True}
            ],
            "outputs": [
                {"name": "example_output", "type": "document"}
            ],
            "permissions": [
                {"resource": "example_resource", "actions": ["read"]}
            ],
            "side_effects": [],
            "approvals": [],
            "dependencies": [],
            "state": {"persistence": "session"},
            "recovery": {"strategy": "retry"},
            "replay": {"mode": "idempotent"},
            "observability": {"level": "basic"},
            "risk": {"level": risk_level},
        })
    else:
        contract_data = {
            "version": 1,
            "workflow": name,
            "inputs": ["example_input"],
            "outputs": ["example_output"],
            "permissions": [{"example_resource": "read"}],
            "side_effects": [],
            "approval_points": [],
            "recovery_strategy": "retry",
            "replay_semantics": "idempotent",
            "dependencies": [],
            "state": "session",
            "observability": ["basic_logs"],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump(contract_data, f, sort_keys=False)

    print(f"CREATED {output_path} (spec version {spec_version})")
    return 0


def run_lint(contract_path: Path) -> int:
    try:
        result = lint_contract(contract_path)
    except FileNotFoundError:
        print(f"ERROR  {contract_path}")
        print("       file not found")
        return 2
    except PermissionError:
        print(f"ERROR  {contract_path}")
        print("       permission denied")
        return 2
    except yaml.YAMLError as error:
        print(f"FAIL  {contract_path}")
        print(f"      invalid YAML: {error}")
        return 1

    if not result.valid_structure:
        print(f"FAIL  {contract_path} (structural validation failed)")
        for w in result.warnings:
            print(f"      [{w.rule_id}] {w.title}: {w.message}")
        return 1

    if not result.warnings:
        print(f"PASS  {contract_path} (0 semantic warnings)")
        return 0

    print(f"WARN  {contract_path} ({len(result.warnings)} semantic warning(s))")
    for w in result.warnings:
        print(f"      [{w.rule_id}] {w.title}: {w.message}")

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "validate":
        return run_validate(args.contract, schema_path=args.schema)

    if args.command == "lint":
        return run_lint(args.contract)

    if args.command == "init":
        return run_init(
            output_path=args.output,
            name=args.name,
            domain=args.domain,
            spec_version=args.spec_version,
            force=args.force,
            interactive=args.interactive,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())