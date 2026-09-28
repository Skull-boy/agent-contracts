"""
Comprehensive test suite for Scyvera Contract Registry (Phase 2).

Verifies:
- Registry initialization (directory/file creation, loading, error handling)
- Contract registration (file, declaration, idempotency, versioning)
- Query methods (get_latest, get_by_hash, get_history, get_at_time, list_nodes, size)
- Persistence (across instances, JSON-lines format, append-only guarantee)
- Integration with ContractEnforcer (registry_entry_id lifecycle)
"""
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import uuid

import pytest

from scyvera import (
    ContractEnforcer,
    ContractRegistry,
    RegistryEntry,
    RegistryError,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"
GITHUB_CONTRACT = FIXTURES / "github_contract.yaml"


# =============================================================================
# Helpers
# =============================================================================

def _make_registry(tmp_path: Path, name: str = "registry.jsonl") -> ContractRegistry:
    """Create a registry in a tmp_path with a given filename."""
    return ContractRegistry(path=str(tmp_path / name))


def _make_declaration(node_id: str, permissions: list[str] | None = None) -> ContractEnforcer:
    """Create a declaration-based enforcer with a given node_id."""
    return ContractEnforcer.from_declaration({
        "node_id": node_id,
        "permissions": permissions or ["github.read"],
    })


# =============================================================================
# 1. Initialization Tests
# =============================================================================

def test_registry_creates_directory_if_missing(tmp_path):
    """Path to a nested dir that doesn't exist — registry creation must create it."""
    nested_path = tmp_path / "deep" / "nested" / "dir" / "registry.jsonl"
    registry = ContractRegistry(path=str(nested_path))
    assert nested_path.parent.exists()
    assert nested_path.exists()
    assert registry.size() == 0


def test_registry_creates_file_if_missing(tmp_path):
    """File doesn't exist → registry creates it on init, size() == 0."""
    reg_path = tmp_path / "new_registry.jsonl"
    assert not reg_path.exists()
    registry = ContractRegistry(path=str(reg_path))
    assert reg_path.exists()
    assert registry.size() == 0


def test_registry_loads_existing_entries(tmp_path):
    """Create registry, register two contracts, create second registry pointing to same file."""
    reg_path = str(tmp_path / "registry.jsonl")
    registry1 = ContractRegistry(path=reg_path)

    enforcer_a = _make_declaration("agent-a-v1")
    enforcer_b = _make_declaration("agent-b-v1")
    enforcer_a.register(registry1)
    enforcer_b.register(registry1)
    assert registry1.size() == 2

    # Second registry instance pointing to same file
    registry2 = ContractRegistry(path=reg_path)
    assert registry2.size() == 2


def test_registry_raises_on_malformed_file(tmp_path):
    """Write non-JSON to registry file → RegistryError on ContractRegistry init."""
    reg_path = tmp_path / "bad_registry.jsonl"
    reg_path.write_text("this is not json\n", encoding="utf-8")

    with pytest.raises(RegistryError) as exc_info:
        ContractRegistry(path=str(reg_path))
    assert exc_info.value.operation == "load"
    assert "Malformed JSON" in exc_info.value.reason


# =============================================================================
# 2. Registration Tests
# =============================================================================

def test_register_file_contract(tmp_path):
    """Load from fixture, register — verify all entry fields."""
    registry = _make_registry(tmp_path)
    enforcer = ContractEnforcer.load(GITHUB_CONTRACT)
    entry = enforcer.register(registry)

    assert entry.contract_source == "file"
    assert entry.contract_hash is not None
    assert len(entry.contract_hash) == 64
    assert entry.node_id is None  # file contracts have no node_id
    assert entry.version == 1
    assert entry.path is not None
    assert isinstance(entry.content, dict)


def test_register_declaration_contract(tmp_path):
    """from_declaration(), register — verify entry fields."""
    registry = _make_registry(tmp_path)
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "my-agent-v1",
        "permissions": ["github.read"],
        "side_effects": ["github.comment"],
    })
    entry = enforcer.register(registry)

    assert entry.contract_source == "declaration"
    assert entry.node_id == "my-agent-v1"
    assert entry.path is None
    assert entry.content == {
        "node_id": "my-agent-v1",
        "permissions": ["github.read"],
        "side_effects": ["github.comment"],
    }


def test_register_idempotent_same_hash(tmp_path):
    """Register same enforcer twice — registry.size() == 1, same entry_id."""
    registry = _make_registry(tmp_path)
    enforcer = _make_declaration("idempotent-v1")

    entry1 = enforcer.register(registry)
    entry2 = enforcer.register(registry)

    assert registry.size() == 1
    assert entry1.entry_id == entry2.entry_id


def test_register_increments_version_per_node_id(tmp_path):
    """Register two different declarations with same node_id → version increments."""
    registry = _make_registry(tmp_path)

    enforcer1 = ContractEnforcer.from_declaration({
        "node_id": "versioned-v1",
        "permissions": ["github.read"],
    })
    enforcer2 = ContractEnforcer.from_declaration({
        "node_id": "versioned-v1",
        "permissions": ["github.read", "github.write"],
    })

    entry1 = enforcer1.register(registry)
    entry2 = enforcer2.register(registry)

    assert entry1.version == 1
    assert entry2.version == 2


def test_register_different_node_ids_independent_versions(tmp_path):
    """Different node_ids have independent version counters."""
    registry = _make_registry(tmp_path)

    enforcer_a = _make_declaration("node-a-v1")
    enforcer_b = _make_declaration("node-b-v1")

    entry_a = enforcer_a.register(registry)
    entry_b = enforcer_b.register(registry)

    assert entry_a.version == 1
    assert entry_b.version == 1


def test_register_sets_enforcer_registry_entry_id(tmp_path):
    """After register(), enforcer.registry_entry_id matches entry.entry_id."""
    registry = _make_registry(tmp_path)
    enforcer = _make_declaration("registered-v1")

    assert enforcer.registry_entry_id is None
    entry = enforcer.register(registry)
    assert enforcer.registry_entry_id is not None
    assert enforcer.registry_entry_id == entry.entry_id


def test_register_entry_id_is_uuid4(tmp_path):
    """entry.entry_id matches UUID4 format."""
    registry = _make_registry(tmp_path)
    enforcer = _make_declaration("uuid-test-v1")
    entry = enforcer.register(registry)

    # uuid.UUID with version=4 must not raise
    parsed = uuid.UUID(entry.entry_id, version=4)
    assert str(parsed) == entry.entry_id


# =============================================================================
# 3. Query Tests
# =============================================================================

def test_get_latest_returns_highest_version(tmp_path):
    """Register node-x-v1 twice (different content) → get_latest returns version 2."""
    registry = _make_registry(tmp_path)

    enforcer1 = ContractEnforcer.from_declaration({
        "node_id": "node-x-v1",
        "permissions": ["read"],
    })
    enforcer2 = ContractEnforcer.from_declaration({
        "node_id": "node-x-v1",
        "permissions": ["read", "write"],
    })

    enforcer1.register(registry)
    enforcer2.register(registry)

    latest = registry.get_latest("node-x-v1")
    assert latest is not None
    assert latest.version == 2


def test_get_latest_returns_none_for_unknown_node(tmp_path):
    """get_latest for a node that was never registered returns None."""
    registry = _make_registry(tmp_path)
    assert registry.get_latest("nobody-v1") is None


def test_get_by_hash_finds_entry(tmp_path):
    """Register a declaration → get_by_hash returns that entry."""
    registry = _make_registry(tmp_path)
    enforcer = _make_declaration("hash-lookup-v1")
    entry = enforcer.register(registry)

    found = registry.get_by_hash(entry.contract_hash)
    assert found is not None
    assert found.entry_id == entry.entry_id


def test_get_by_hash_returns_none_if_not_found(tmp_path):
    """get_by_hash with nonexistent hash returns None."""
    registry = _make_registry(tmp_path)
    assert registry.get_by_hash("nonexistentHash") is None


def test_get_history_returns_all_versions_ordered(tmp_path):
    """Register node-y-v1 three times → get_history returns 3 entries ordered 1, 2, 3."""
    registry = _make_registry(tmp_path)

    for i in range(3):
        enforcer = ContractEnforcer.from_declaration({
            "node_id": "node-y-v1",
            "permissions": [f"perm-{i}"],
        })
        enforcer.register(registry)

    history = registry.get_history("node-y-v1")
    assert len(history) == 3
    assert [e.version for e in history] == [1, 2, 3]


def test_get_history_returns_empty_for_unknown(tmp_path):
    """get_history for unknown node returns empty list."""
    registry = _make_registry(tmp_path)
    assert registry.get_history("nobody-v1") == []


def test_get_at_time_returns_correct_version(tmp_path):
    """Register v1, then v2 — get_at_time between them returns v1, after v2 returns v2."""
    registry = _make_registry(tmp_path)

    enforcer1 = ContractEnforcer.from_declaration({
        "node_id": "time-test-v1",
        "permissions": ["read"],
    })
    entry1 = enforcer1.register(registry)
    t1 = entry1.registered_at

    # Small delay to ensure distinct timestamps
    time.sleep(0.05)
    between_time = datetime.now(timezone.utc).isoformat()
    time.sleep(0.05)

    enforcer2 = ContractEnforcer.from_declaration({
        "node_id": "time-test-v1",
        "permissions": ["read", "write"],
    })
    entry2 = enforcer2.register(registry)

    # Query between v1 and v2 — should return v1
    result_between = registry.get_at_time("time-test-v1", between_time)
    assert result_between is not None
    assert result_between.version == 1

    # Query after v2 — should return v2
    after_time = datetime.now(timezone.utc).isoformat()
    result_after = registry.get_at_time("time-test-v1", after_time)
    assert result_after is not None
    assert result_after.version == 2


def test_get_at_time_returns_none_before_any_registration(tmp_path):
    """Timestamp before any registration returns None."""
    before_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    registry = _make_registry(tmp_path)
    enforcer = _make_declaration("future-v1")
    enforcer.register(registry)

    result = registry.get_at_time("future-v1", before_time)
    assert result is None


def test_get_at_time_raises_on_invalid_timestamp(tmp_path):
    """get_at_time with unparseable timestamp raises RegistryError."""
    registry = _make_registry(tmp_path)

    with pytest.raises(RegistryError) as exc_info:
        registry.get_at_time("node-v1", "not-a-timestamp")
    assert exc_info.value.operation == "get_at_time"
    assert "Invalid timestamp" in exc_info.value.reason


def test_list_nodes_returns_sorted_node_ids(tmp_path):
    """Register node-b, node-a, node-c → list_nodes returns sorted."""
    registry = _make_registry(tmp_path)

    for node_id in ["node-b-v1", "node-a-v1", "node-c-v1"]:
        enforcer = _make_declaration(node_id)
        enforcer.register(registry)

    nodes = registry.list_nodes()
    assert nodes == ["node-a-v1", "node-b-v1", "node-c-v1"]


def test_list_nodes_excludes_none_node_ids(tmp_path):
    """Register a file contract (node_id=None) — list_nodes does not include None."""
    registry = _make_registry(tmp_path)
    file_enforcer = ContractEnforcer.load(GITHUB_CONTRACT)
    file_enforcer.register(registry)

    nodes = registry.list_nodes()
    assert None not in nodes


def test_size_correct(tmp_path):
    """Register 3 contracts → size() == 3."""
    registry = _make_registry(tmp_path)

    for node_id in ["size-a-v1", "size-b-v1", "size-c-v1"]:
        enforcer = _make_declaration(node_id)
        enforcer.register(registry)

    assert registry.size() == 3


# =============================================================================
# 4. Persistence Tests
# =============================================================================

def test_registry_persists_across_instances(tmp_path):
    """Create registry, register 2 entries, del, create new → size() == 2."""
    reg_path = str(tmp_path / "persist.jsonl")

    registry1 = ContractRegistry(path=reg_path)
    enforcer_a = _make_declaration("persist-a-v1")
    enforcer_b = _make_declaration("persist-b-v1")
    entry_a = enforcer_a.register(registry1)
    entry_b = enforcer_b.register(registry1)
    del registry1

    registry2 = ContractRegistry(path=reg_path)
    assert registry2.size() == 2

    # Verify entries match
    found_a = registry2.get_by_hash(entry_a.contract_hash)
    found_b = registry2.get_by_hash(entry_b.contract_hash)
    assert found_a is not None
    assert found_b is not None
    assert found_a.entry_id == entry_a.entry_id
    assert found_b.entry_id == entry_b.entry_id


def test_registry_file_is_jsonlines(tmp_path):
    """Register 3 entries → file has exactly 3 lines, each valid JSON."""
    reg_path = tmp_path / "jsonlines.jsonl"
    registry = ContractRegistry(path=str(reg_path))

    for node_id in ["jl-a-v1", "jl-b-v1", "jl-c-v1"]:
        enforcer = _make_declaration(node_id)
        enforcer.register(registry)

    content = reg_path.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) == 3

    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
        assert "entry_id" in parsed


def test_registry_file_is_append_only(tmp_path):
    """Register entry, note file content, register another → first entry still present verbatim."""
    reg_path = tmp_path / "append.jsonl"
    registry = ContractRegistry(path=str(reg_path))

    enforcer1 = _make_declaration("append-a-v1")
    enforcer1.register(registry)

    content_after_first = reg_path.read_text(encoding="utf-8")
    first_line = content_after_first.splitlines()[0]

    enforcer2 = _make_declaration("append-b-v1")
    enforcer2.register(registry)

    content_after_second = reg_path.read_text(encoding="utf-8")
    lines = content_after_second.splitlines()
    assert len(lines) == 2
    # First entry must still be present verbatim
    assert lines[0] == first_line


# =============================================================================
# 5. Integration Tests
# =============================================================================

def test_registry_entry_id_property_before_registration():
    """Fresh enforcer → registry_entry_id is None."""
    enforcer = _make_declaration("fresh-v1")
    assert enforcer.registry_entry_id is None


def test_registry_entry_id_property_after_registration(tmp_path):
    """After register() → registry_entry_id is not None."""
    registry = _make_registry(tmp_path)
    enforcer = _make_declaration("after-reg-v1")

    assert enforcer.registry_entry_id is None
    entry = enforcer.register(registry)
    assert enforcer.registry_entry_id is not None
    assert enforcer.registry_entry_id == entry.entry_id


def test_full_workflow_file_contract(tmp_path):
    """load() → register() → get_latest() → verify entry matches enforcer."""
    registry = _make_registry(tmp_path)
    enforcer = ContractEnforcer.load(GITHUB_CONTRACT)

    entry = enforcer.register(registry)

    assert entry.contract_source == "file"
    assert entry.contract_hash == enforcer.integrity_hash
    assert entry.version == 1
    assert enforcer.registry_entry_id == entry.entry_id

    # get_by_hash returns same entry
    found = registry.get_by_hash(enforcer.integrity_hash)
    assert found is not None
    assert found.entry_id == entry.entry_id

    # size correct
    assert registry.size() == 1


def test_full_workflow_declaration_contract(tmp_path):
    """from_declaration() → register() → get_history() → single entry."""
    registry = _make_registry(tmp_path)
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "workflow-decl-v1",
        "permissions": ["github.read"],
        "side_effects": ["github.comment"],
    })

    entry = enforcer.register(registry)

    history = registry.get_history("workflow-decl-v1")
    assert len(history) == 1
    assert history[0].entry_id == entry.entry_id
    assert history[0].node_id == "workflow-decl-v1"
    assert history[0].version == 1
    assert enforcer.registry_entry_id == entry.entry_id
