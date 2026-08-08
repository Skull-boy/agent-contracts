from pathlib import Path

from agent_contracts.validator import SCHEMA_V1_PATH, SCHEMA_V1_1_PATH


ROOT = Path(__file__).resolve().parent.parent


def test_schema_v1_sync():
    root_v1 = ROOT / "schemas" / "v1" / "contract.schema.json"
    pkg_v1 = ROOT / "src" / "agent_contracts" / "schemas" / "v1" / "contract.schema.json"

    assert root_v1.exists()
    assert pkg_v1.exists()
    assert root_v1.read_text(encoding="utf-8") == pkg_v1.read_text(encoding="utf-8")


def test_schema_v1_1_sync():
    root_v1_1 = ROOT / "schemas" / "v1.1" / "contract.schema.json"
    pkg_v1_1 = ROOT / "src" / "agent_contracts" / "schemas" / "v1.1" / "contract.schema.json"

    assert root_v1_1.exists()
    assert pkg_v1_1.exists()
    assert root_v1_1.read_text(encoding="utf-8") == pkg_v1_1.read_text(encoding="utf-8")


def test_package_schema_paths_resolve():
    assert SCHEMA_V1_PATH.exists()
    assert SCHEMA_V1_1_PATH.exists()
