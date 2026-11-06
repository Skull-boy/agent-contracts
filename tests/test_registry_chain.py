"""Tests for the hash-chained contract registry (RFC 0003 §C1, roadmap M1.1).

Acceptance coverage from the roadmap row:

- a valid chain passes, including after a reload;
- reordered and spliced/edited files fail closed with ``RegistryError``;
- ``upgrade_chain()`` migrates a pre-chain file exactly once, snapshots it, and
  is an idempotent no-op afterwards;
- a chain failure blocks ``get_at_time()`` (and ``get_history()``) so a
  tampered file never answers provenance questions.

Extra safety nets: genesis hashing, mixed-format rejection, legacy
query/append behavior, idempotent registration, atomic append failure, and
canonical-byte determinism.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path

import pytest

from scyvera import (
    GENESIS_HASH,
    ContractEnforcer,
    ContractRegistry,
    RegistryEntry,
    RegistryError,
)
from scyvera.chain import (
    canonical_entry_bytes,
    compute_chain_intervals,
    next_prev_hash,
    verify_chain_entries,
)

ROOT = Path(__file__).resolve().parent.parent
GITHUB_CONTRACT = ROOT / "tests" / "fixtures" / "github_contract.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(tmp_path: Path, name: str = "registry.jsonl") -> ContractRegistry:
    return ContractRegistry(path=str(tmp_path / name))


def _make_declaration(
    node_id: str, permissions: list[str] | None = None
) -> ContractEnforcer:
    return ContractEnforcer.from_declaration(
        {
            "node_id": node_id,
            "permissions": permissions or ["github.read"],
        }
    )


def _register_three(registry: ContractRegistry) -> list[RegistryEntry]:
    entries = []
    for node_id in ("chain-a-v1", "chain-b-v1", "chain-c-v1"):
        entries.append(_make_declaration(node_id).register(registry))
    return entries


def _rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, separators=(",", ":")) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _strip_chain(path: Path) -> bytes:
    """Turn a chained registry into a valid pre-chain file; return its bytes."""
    rows = _rows(path)
    for row in rows:
        row.pop("prev_hash", None)
    _write_rows(path, rows)
    return path.read_bytes()


# ---------------------------------------------------------------------------
# Valid chain
# ---------------------------------------------------------------------------


def test_fresh_registry_first_entry_uses_genesis_hash(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    entry = _make_declaration("genesis-v1").register(registry)

    assert entry.prev_hash == GENESIS_HASH
    assert _rows(tmp_path / "registry.jsonl")[0]["prev_hash"] == GENESIS_HASH


def test_chain_links_cover_full_history(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    first, second, third = _register_three(registry)

    assert second.prev_hash == next_prev_hash(first)
    assert third.prev_hash == next_prev_hash(second)
    assert registry.verify_chain() is True
    assert [row["prev_hash"] for row in _rows(tmp_path / "registry.jsonl")] == [
        GENESIS_HASH,
        next_prev_hash(first),
        next_prev_hash(second),
    ]


def test_valid_chain_survives_reload(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)

    reloaded = ContractRegistry(path=str(tmp_path / "registry.jsonl"))
    assert reloaded.size() == 3
    assert reloaded.verify_chain() is True


def test_canonical_bytes_are_deterministic() -> None:
    entry = RegistryEntry(
        entry_id="00000000-0000-4000-8000-000000000000",
        node_id="deterministic-v1",
        contract_hash="a" * 64,
        contract_source="declaration",
        registered_at="2026-11-06T00:00:00+00:00",
        version=1,
        content={"node_id": "deterministic-v1", "permissions": ["github.read"]},
        path=None,
        prev_hash=GENESIS_HASH,
    )

    first = canonical_entry_bytes(entry)
    second = canonical_entry_bytes(entry)
    assert first == second
    assert first.endswith(b"}") and not first.endswith(b"\n")
    assert next_prev_hash(entry) == hashlib.sha256(first).hexdigest()
    assert next_prev_hash(entry) == next_prev_hash(entry)


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_reordered_lines_raise_at_load(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"

    rows = _rows(path)
    rows[1], rows[2] = rows[2], rows[1]
    _write_rows(path, rows)

    with pytest.raises(RegistryError) as excinfo:
        ContractRegistry(path=str(path))
    assert excinfo.value.operation == "verify_chain"
    assert "chain break" in excinfo.value.reason


def test_spliced_edited_line_raises_at_load(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"

    rows = _rows(path)
    rows[1]["node_id"] = "tampered-v1"
    _write_rows(path, rows)

    with pytest.raises(RegistryError) as excinfo:
        ContractRegistry(path=str(path))
    assert excinfo.value.operation == "verify_chain"
    assert "chain break" in excinfo.value.reason


def test_fabricated_insertion_raises_at_load(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"

    rows = _rows(path)
    forged = dict(rows[0])
    forged["entry_id"] = "11111111-1111-4111-8111-111111111111"
    forged["node_id"] = "forged-v1"
    forged["contract_hash"] = "b" * 64
    # The forgery reuses a plausible prev_hash; the following real entry still
    # no longer links to it, so the chain must break.
    rows.insert(1, forged)
    _write_rows(path, rows)

    with pytest.raises(RegistryError) as excinfo:
        ContractRegistry(path=str(path))
    assert excinfo.value.operation == "verify_chain"


def test_truncated_chain_raises(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"

    rows = _rows(path)
    rows[2]["prev_hash"] = GENESIS_HASH  # plausible but wrong link
    _write_rows(path, rows)

    with pytest.raises(RegistryError):
        ContractRegistry(path=str(path))


def test_chain_failure_blocks_provenance_queries(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    entries = _register_three(registry)
    path = tmp_path / "registry.jsonl"

    # Tamper *after* construction: verification must re-read the file, so the
    # already-loaded instance cannot keep answering from stale memory.
    rows = _rows(path)
    rows[1]["node_id"] = "tampered-v1"
    _write_rows(path, rows)

    later = datetime.now(timezone.utc).isoformat()
    with pytest.raises(RegistryError):
        registry.verify_chain()
    with pytest.raises(RegistryError):
        registry.get_at_time(entries[0].node_id or "", later)
    with pytest.raises(RegistryError):
        registry.get_history(entries[0].node_id or "")


def test_mixed_format_is_rejected_at_load(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"

    rows = _rows(path)
    rows[1].pop("prev_hash")
    _write_rows(path, rows)

    with pytest.raises(RegistryError) as excinfo:
        ContractRegistry(path=str(path))
    assert excinfo.value.operation == "load"
    assert "mixes chained and pre-chain" in excinfo.value.reason
    assert "upgrade_chain" in excinfo.value.reason


# ---------------------------------------------------------------------------
# Legacy files and explicit migration
# ---------------------------------------------------------------------------


def test_legacy_file_loads_and_queries_but_refuses_register(
    tmp_path: Path,
) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"
    _strip_chain(path)

    legacy = ContractRegistry(path=str(path))
    assert legacy.size() == 3
    assert legacy.get_history("chain-a-v1")[0].prev_hash is None
    at_time = datetime.now(timezone.utc).isoformat()
    assert legacy.get_at_time("chain-a-v1", at_time) is not None

    with pytest.raises(RegistryError) as excinfo:
        _make_declaration("legacy-new-v1").register(legacy)
    assert excinfo.value.operation == "register"
    assert "upgrade_chain" in excinfo.value.reason


def test_verify_chain_never_passes_a_pre_chain_file(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"
    _strip_chain(path)

    legacy = ContractRegistry(path=str(path))
    with pytest.raises(RegistryError) as excinfo:
        legacy.verify_chain()
    assert excinfo.value.operation == "verify_chain"
    assert "pre-chain" in excinfo.value.reason


def test_upgrade_chain_migrates_once_with_snapshot_and_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    registry = _make_registry(tmp_path)
    _register_three(registry)
    path = tmp_path / "registry.jsonl"
    original = _strip_chain(path)

    legacy = ContractRegistry(path=str(path))
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="scyvera.registry"):
        snapshot = legacy.upgrade_chain()

    assert snapshot == path.with_name(path.name + ".prechain")
    assert snapshot is not None
    assert snapshot.read_bytes() == original
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "upgraded" in caplog.text

    rows = _rows(path)
    assert [row["prev_hash"] for row in rows][0] == GENESIS_HASH
    assert all(row["prev_hash"] is not None for row in rows)
    assert legacy.verify_chain() is True

    # Migration is idempotent: second call is a no-op and does not rewrite.
    before = path.read_bytes()
    assert legacy.upgrade_chain() is None
    assert path.read_bytes() == before


def test_after_upgrade_appends_are_chained(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    previous = _make_declaration("upgrade-a-v1").register(registry)
    path = tmp_path / "registry.jsonl"
    _strip_chain(path)

    upgraded = ContractRegistry(path=str(path))
    upgraded.upgrade_chain()

    appended = _make_declaration("upgrade-b-v1").register(upgraded)
    assert appended.prev_hash == next_prev_hash(previous)
    assert upgraded.verify_chain() is True

    reloaded = ContractRegistry(path=str(path))
    assert reloaded.size() == 2
    assert reloaded.get_history("upgrade-b-v1")[0].prev_hash == next_prev_hash(
        previous
    )


def test_upgrade_preserves_entry_values(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    before = _register_three(registry)
    path = tmp_path / "registry.jsonl"
    _strip_chain(path)

    legacy = ContractRegistry(path=str(path))
    legacy.upgrade_chain()
    after = legacy.get_history("chain-a-v1")

    assert after[0].entry_id == before[0].entry_id
    assert after[0].contract_hash == before[0].contract_hash
    assert after[0].content == before[0].content


# ---------------------------------------------------------------------------
# Registration invariants
# ---------------------------------------------------------------------------


def test_idempotent_register_appends_exactly_once(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    enforcer = _make_declaration("idempotent-chain-v1")

    first = enforcer.register(registry)
    second = enforcer.register(registry)

    assert first.entry_id == second.entry_id
    assert registry.size() == 1
    assert len(_rows(tmp_path / "registry.jsonl")) == 1


def test_failed_append_leaves_no_partial_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _make_registry(tmp_path)
    path = tmp_path / "registry.jsonl"

    def explode(entry: RegistryEntry) -> None:
        raise RegistryError("append", "simulated disk failure")

    monkeypatch.setattr(registry, "_append_to_file", explode)
    with pytest.raises(RegistryError):
        _make_declaration("atomic-v1").register(registry)

    content = path.read_text(encoding="utf-8")
    assert content == ""
    assert [line for line in content.splitlines() if line.strip()] == []


def test_chain_helpers_expose_expected_links(tmp_path: Path) -> None:
    registry = _make_registry(tmp_path)
    entries = _register_three(registry)

    intervals = compute_chain_intervals(entries)
    assert [interval.index for interval in intervals] == [0, 1, 2]
    assert intervals[0].expected_prev_hash == GENESIS_HASH
    assert all(interval.valid for interval in intervals)
    assert verify_chain_entries(entries) is True
