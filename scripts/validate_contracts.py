from pathlib import Path
import json
import sys

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent.parent

SCHEMA_PATH = ROOT / "schemas" / "v1" / "contract.schema.json"
IMPLEMENTATIONS_PATH = ROOT / "implementations"


def load_schema():
    with SCHEMA_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_contract(path):
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def main():
    schema = load_schema()
    validator = Draft202012Validator(schema)

    contracts = sorted(IMPLEMENTATIONS_PATH.rglob("contract.yaml"))

    if not contracts:
        print("No contract.yaml files found.")
        return 1

    failures = 0

    for contract_path in contracts:
        relative_path = contract_path.relative_to(ROOT)

        try:
            contract = load_contract(contract_path)

            if contract is None:
                print(f"FAIL  {relative_path}")
                print("      contract.yaml is empty")
                failures += 1
                continue

            errors = sorted(
                validator.iter_errors(contract),
                key=lambda error: list(error.absolute_path),
            )

            if not errors:
                print(f"PASS  {relative_path}")
                continue

            print(f"FAIL  {relative_path}")

            for error in errors:
                location = ".".join(str(part) for part in error.absolute_path)

                if location:
                    print(f"      {location}: {error.message}")
                else:
                    print(f"      {error.message}")

            failures += 1

        except (OSError, yaml.YAMLError, json.JSONDecodeError) as error:
            print(f"FAIL  {relative_path}")
            print(f"      {error}")
            failures += 1

    print()
    print(f"Validated {len(contracts)} contract(s).")
    print(f"Passed: {len(contracts) - failures}")
    print(f"Failed: {failures}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())