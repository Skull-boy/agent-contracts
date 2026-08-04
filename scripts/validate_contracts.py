from pathlib import Path
import sys

import yaml

from agent_contracts import validate_contract


ROOT = Path(__file__).resolve().parent.parent

SCHEMA_PATH = ROOT / "schemas" / "v1" / "contract.schema.json"
IMPLEMENTATIONS_PATH = ROOT / "implementations"


def main():
    contracts = sorted(IMPLEMENTATIONS_PATH.rglob("contract.yaml"))

    if not contracts:
        print("No contract.yaml files found.")
        return 1

    failures = 0

    for contract_path in contracts:
        relative_path = contract_path.relative_to(ROOT)

        try:
            result = validate_contract(
                contract_path=contract_path,
                schema_path=SCHEMA_PATH,
            )

            if result.valid:
                print(f"PASS  {relative_path}")
                continue

            print(f"FAIL  {relative_path}")

            for error in result.errors:
                if error.path:
                    print(f"      {error.path}: {error.message}")
                else:
                    print(f"      {error.message}")

            failures += 1

        except (OSError, yaml.YAMLError) as error:
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