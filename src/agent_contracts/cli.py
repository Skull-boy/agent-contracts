import argparse
import sys
from pathlib import Path

import yaml

from .validator import validate_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-contracts",
        description="Validate Agent Contract files.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an Agent Contract.",
    )

    validate_parser.add_argument(
        "contract",
        type=Path,
        help="Path to contract.yaml",
    )

    return parser


def run_validate(contract_path: Path) -> int:
    try:
        result = validate_contract(contract_path)

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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "validate":
        return run_validate(args.contract)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())