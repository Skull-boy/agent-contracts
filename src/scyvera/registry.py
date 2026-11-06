"""
Contract Registry — versioned, append-only, persistent store of every
contract that has been registered with the Scyvera governance layer.

DESIGN PRINCIPLES:
==================
1. APPEND-ONLY: Registry entries are never deleted or overwritten.
   The registry file is the permanent audit trail of governance history.

2. FAIL CLOSED: Any registry error raises RegistryError, never silently
   continues. Corrupt files, unwritable paths, malformed entries — all
   raise immediately.

3. EXPLICIT OVER IMPLICIT: Registration is always a deliberate act.
   Contracts are not auto-registered on load.

4. NO EXTERNAL DEPENDENCIES: stdlib only (json, uuid, datetime,
   pathlib, dataclasses) plus PyYAML for YAML parsing.

5. IDEMPOTENT REGISTRATION: Registering the same contract hash twice
   returns the existing entry without creating a duplicate.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Optional
import uuid

import yaml

from .chain import (
    GENESIS_HASH,
    canonical_entry_bytes,
    next_prev_hash,
    verify_chain_entries,
)
from .exceptions import RegistryError

logger = logging.getLogger("scyvera.registry")

_REQUIRED_FIELDS = frozenset({
    "entry_id", "node_id", "contract_hash", "contract_source",
    "registered_at", "version", "content", "path",
})


def _path_key(path: Optional[str]) -> Optional[str]:
    """Normalize a registry entry path for identity lookups (M1.3, T14)."""
    if path is None:
        return None
    return os.path.normcase(os.path.abspath(path))


@dataclass
class RegistryEntry:
    """Immutable data container representing a single registry record.

    All fields are JSON-serializable: strings, ints, dicts, or None.
    No datetime objects, no Path objects.
    ``asdict()`` produces valid JSON-serializable output.
    """
    entry_id: str
    node_id: Optional[str]
    contract_hash: str
    contract_source: str
    registered_at: str
    version: int
    content: dict
    path: Optional[str]
    # SHA-256 of the previous canonical entry, or the genesis value (RFC 0003
    # §C1). None marks a legacy entry written before the chain existed. A
    # registry file is either fully chained or fully legacy; mixed files are
    # rejected at load time because they indicate splices or manual edits.
    prev_hash: Optional[str] = None


class ContractRegistry:
    """Versioned, append-only, persistent store of registered contracts.

    Backed by a JSON-lines file (one entry per line). On initialization,
    all existing entries are loaded into memory for fast querying.
    """

    def __init__(self, path: str = ".scyvera/registry.jsonl") -> None:
        self._path = Path(path)
        self._entries: list[RegistryEntry] = []
        self._hash_index: dict[str, RegistryEntry] = {}
        self._node_index: dict[str, list[RegistryEntry]] = {}
        # File contracts have no node_id, so their version history is keyed by
        # canonical path. This is what lets an M1.4 re-seal register version
        # N+1 for the same file instead of a second unrelated version 1.
        self._path_index: dict[str, list[RegistryEntry]] = {}
        # Format state is established at load time, never inferred lazily:
        # an empty file is chain-ready, a fully chained file is verified
        # eagerly, and a fully legacy file stays readable but refuses appends.
        self._chained = False
        self._legacy = False

        # Create directory and file if they don't exist
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

        self._load_from_file()

    # -------------------------------------------------------------------------
    # Public Methods
    # -------------------------------------------------------------------------

    def register(self, enforcer: Any) -> RegistryEntry:
        """Register an enforcer's contract into this registry.

        Creates a RegistryEntry from the enforcer's sealed state.
        If an entry with the same contract_hash already exists,
        returns the existing entry (idempotent).

        Args:
            enforcer: A ContractEnforcer instance.

        Returns:
            The created (or existing) RegistryEntry.
        """
        contract_hash = enforcer._integrity_hash

        if self._legacy:
            raise RegistryError(
                "register",
                f"registry '{self._path}' is in pre-chain format; call "
                "upgrade_chain() to seal its history before appending",
            )

        # Idempotent: return existing entry if hash already registered
        if contract_hash in self._hash_index:
            return self._hash_index[contract_hash]

        # Never extend a chain that no longer matches the file on disk.
        if self._chained and self._entries:
            self.verify_chain()

        node_id = enforcer.node_id
        source = enforcer.contract_source

        # Build content field
        if source == "declaration":
            content = copy.deepcopy(enforcer._sealed_declaration)
        else:
            # File-based contract: read and parse the YAML file
            try:
                raw_bytes = enforcer._contract_path.read_bytes()
                content = yaml.safe_load(raw_bytes)
                if content is None:
                    content = {}
            except Exception as exc:
                raise RegistryError(
                    "register",
                    f"Failed to read contract file '{enforcer._contract_path}': {exc}",
                ) from exc

        # Build path field
        file_path: Optional[str] = None
        if source == "file" and enforcer._contract_path is not None:
            file_path = str(enforcer._contract_path.resolve())

        # Compute version. Declarations version by node_id; file contracts
        # version by canonical path so an M1.4 re-seal produces N+1.
        path_key = _path_key(file_path)
        if node_id is not None:
            existing = self._node_index.get(node_id, [])
        elif path_key is not None:
            existing = self._path_index.get(path_key, [])
        else:
            existing = []
        version = len(existing) + 1

        # RFC 0003 §C1: chain every new entry. A fresh (empty) registry starts
        # from the fixed genesis value; otherwise hash the last entry's
        # canonical bytes.
        prev_hash = (
            GENESIS_HASH
            if not self._entries
            else next_prev_hash(self._entries[-1])
        )

        entry = RegistryEntry(
            entry_id=str(uuid.uuid4()),
            node_id=node_id,
            contract_hash=contract_hash,
            contract_source=source,
            registered_at=datetime.now(timezone.utc).isoformat(),
            version=version,
            content=content,
            path=file_path,
            prev_hash=prev_hash,
        )

        # Append to in-memory stores
        self._entries.append(entry)
        self._hash_index[entry.contract_hash] = entry
        if entry.node_id is not None:
            self._node_index.setdefault(entry.node_id, []).append(entry)
        if path_key is not None:
            self._path_index.setdefault(path_key, []).append(entry)

        # Persist to disk
        self._append_to_file(entry)
        # From this point the registry on disk carries a chain. Mark it only
        # after the append succeeds so a failed write cannot claim integrity.
        self._chained = True

        return entry

    def get_latest(self, node_id: str) -> Optional[RegistryEntry]:
        """Return the most recently registered entry for a given node_id.

        "Most recent" = highest version number.
        Returns None if no entries exist for this node_id.
        """
        entries = self._node_index.get(node_id)
        if not entries:
            return None
        return max(entries, key=lambda e: e.version)

    def get_by_hash(self, contract_hash: str) -> Optional[RegistryEntry]:
        """Return the entry with the matching contract_hash, or None."""
        return self._hash_index.get(contract_hash)

    def get_history(self, node_id: str) -> list[RegistryEntry]:
        """Return all entries for a given node_id, ordered by version ascending.

        RFC 0003 §C1: a chained registry re-verifies first, because a
        tampered file must not answer provenance questions.
        """
        self._guard_provenance()
        entries = self._node_index.get(node_id, [])
        return sorted(entries, key=lambda e: e.version)

    def get_at_time(
        self,
        node_id: str,
        timestamp: str,
    ) -> Optional[RegistryEntry]:
        """Return the entry active for the given node_id at the given ISO8601 UTC timestamp.

        "Active at time T" = the highest-version entry whose
        registered_at is <= T.

        Raises:
            RegistryError: If the timestamp is not parseable, or if the
                chained registry fails verification (RFC 0003 §C1).
        """
        self._guard_provenance()
        try:
            query_dt = datetime.fromisoformat(timestamp)
        except (ValueError, TypeError) as exc:
            raise RegistryError(
                "get_at_time",
                f"Invalid timestamp '{timestamp}': {exc}",
            ) from exc

        entries = self._node_index.get(node_id, [])
        candidates = []
        for entry in entries:
            entry_dt = datetime.fromisoformat(entry.registered_at)
            if entry_dt <= query_dt:
                candidates.append(entry)

        if not candidates:
            return None
        return max(candidates, key=lambda e: e.version)

    def list_nodes(self) -> list[str]:
        """Return a sorted list of all unique node_ids that have at least one entry.

        Excludes None node_ids.
        """
        return sorted(self._node_index.keys())

    def size(self) -> int:
        """Return total number of entries in the registry."""
        return len(self._entries)

    def has_hash(self, contract_hash: str) -> bool:
        """Return True if an entry with this hash exists."""
        return contract_hash in self._hash_index

    def get_history_by_path(self, path: str | Path) -> list[RegistryEntry]:
        """Return all entries registered for a canonical contract path (M1.3).

        File contracts carry ``node_id=None``, so the canonical path is their
        stable identity (T14). A chained registry re-verifies first, matching
        :meth:`get_history`, because a tampered file must not answer identity
        questions. Results are ordered by version ascending.
        """
        self._guard_provenance()
        key = _path_key(os.fspath(path))
        if key is None:
            return []
        entries = self._path_index.get(key, [])
        return sorted(entries, key=lambda e: e.version)

    def get_latest_by_path(self, path: str | Path) -> Optional[RegistryEntry]:
        """Return the highest-version entry for a canonical contract path."""
        history = self.get_history_by_path(path)
        if not history:
            return None
        return history[-1]

    # -------------------------------------------------------------------------
    # Chain Integrity (RFC 0003 §C1, roadmap M1.1)
    # -------------------------------------------------------------------------

    def verify_chain(self) -> bool:
        """Verify the registry hash chain by recomputing it from the file.

        RFC 0003 §C1 requires verification to be recomputable from
        ``registry.jsonl`` alone, so this method re-reads the file instead of
        trusting in-memory state. A break, splice, reorder, edit, or
        fabricated insertion raises :class:`RegistryError`; the return value
        of ``True`` documents success.

        A pre-chain (legacy) file never returns a passing verdict: it raises
        with an actionable ``upgrade_chain()`` message, because there is no
        cryptographic anchor to verify.
        """
        entries = self._read_entries_from_file("verify_chain")
        if not entries:
            return True
        if all(entry.prev_hash is None for entry in entries):
            raise RegistryError(
                "verify_chain",
                f"registry '{self._path}' is pre-chain; call upgrade_chain() "
                "to backfill prev_hash before relying on provenance",
            )
        return verify_chain_entries(entries)

    def upgrade_chain(self) -> Optional[Path]:
        """Explicitly migrate a pre-chain registry to the hash chain.

        RFC 0003 §C1 (and its resolved open question) forbids automatic
        migration: this method snapshots the original bytes to
        ``<registry>.prechain`` next to the registry, emits a warning, then
        rewrites the full history with deterministic ``prev_hash`` values.
        It returns the snapshot path. Calling it on an already-chained
        registry is an idempotent no-op that returns ``None`` without
        rewriting anything.

        Historical caveat: backfilled hashes prove integrity from the upgrade
        moment forward. Tampering that happened before the snapshot was taken
        is outside C1's guarantee — that is exactly why the sidecar and the
        warning exist.
        """
        if self._chained or (not self._entries and not self._legacy):
            # Already chained, or an empty chain-ready registry: nothing to
            # migrate and nothing to rewrite.
            return None

        snapshot_path = self._path.with_name(self._path.name + ".prechain")
        original = self._path.read_bytes()
        snapshot_path.write_bytes(original)

        entries = self._read_entries_from_file("upgrade_chain")
        chained: list[RegistryEntry] = []
        previous: Optional[RegistryEntry] = None
        for entry in entries:
            entry.prev_hash = (
                GENESIS_HASH if previous is None else next_prev_hash(previous)
            )
            chained.append(entry)
            previous = entry

        self._rewrite_file(chained)
        self._entries = chained
        self._hash_index = {}
        self._node_index = {}
        self._path_index = {}
        for entry in chained:
            self._hash_index[entry.contract_hash] = entry
            if entry.node_id is not None:
                self._node_index.setdefault(entry.node_id, []).append(entry)
            key = _path_key(entry.path)
            if key is not None:
                self._path_index.setdefault(key, []).append(entry)
        self._chained = True
        self._legacy = False

        logger.warning(
            "Registry '%s' upgraded to the RFC 0003 §C1 hash chain; pre-chain "
            "snapshot written to '%s'. Backfilled hashes prove integrity from "
            "this moment forward only.",
            self._path,
            snapshot_path,
        )
        return snapshot_path

    # -------------------------------------------------------------------------
    # Internal Methods
    # -------------------------------------------------------------------------

    def _guard_provenance(self) -> None:
        """Re-verify a chained registry before answering provenance queries.

        RFC 0003 §C1 requires ``verify_chain()`` before ``get_at_time()`` and
        ``get_history()``. Legacy files have no anchor to verify and keep
        working, with the documented caveat that their history is unsealed.
        """
        if self._chained:
            self.verify_chain()

    def _load_from_file(self) -> None:
        """Read the JSON-lines file and populate in-memory stores.

        Each line is one JSON object → one RegistryEntry. Empty lines are
        skipped. Malformed lines raise RegistryError.

        Format rules (RFC 0003 §C1):
        - empty file → chain-ready; the first append uses ``GENESIS_HASH``;
        - every entry chained → verified eagerly, and a corrupt chain raises
          immediately (never lingers);
        - every entry legacy (no ``prev_hash``) → loads exactly as before,
          readable but append-refusing until ``upgrade_chain()``;
        - mixed chained/legacy lines → fail closed, because that shape means
          a splice or manual edit.
        """
        entries = self._read_entries_from_file("load")
        has_chained = any(entry.prev_hash is not None for entry in entries)
        has_legacy = any(entry.prev_hash is None for entry in entries)
        if has_chained and has_legacy:
            raise RegistryError(
                "load",
                f"registry '{self._path}' mixes chained and pre-chain entries; "
                "this indicates a splice or manual edit. Restore the original "
                "file, or run upgrade_chain() on an all-pre-chain file.",
            )

        self._entries = entries
        self._hash_index = {}
        self._node_index = {}
        self._path_index = {}
        for entry in entries:
            self._hash_index[entry.contract_hash] = entry
            if entry.node_id is not None:
                self._node_index.setdefault(entry.node_id, []).append(entry)
            key = _path_key(entry.path)
            if key is not None:
                self._path_index.setdefault(key, []).append(entry)

        self._chained = has_chained
        self._legacy = has_legacy
        if self._chained:
            self.verify_chain()

    def _read_entries_from_file(self, operation: str) -> list[RegistryEntry]:
        """Parse every JSONL line into a RegistryEntry, without touching state."""
        try:
            raw_content = self._path.read_text(encoding="utf-8")
        except Exception as exc:
            raise RegistryError(
                operation,
                f"Failed to read registry file '{self._path}': {exc}",
            ) from exc

        entries: list[RegistryEntry] = []
        for line_num, line in enumerate(raw_content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise RegistryError(
                    operation,
                    f"Malformed JSON on line {line_num} of '{self._path}': {exc}",
                ) from exc
            if not isinstance(data, dict):
                raise RegistryError(
                    operation,
                    f"Registry line {line_num} of '{self._path}' is not a "
                    "JSON object",
                )

            missing = _REQUIRED_FIELDS - set(data.keys())
            if missing:
                raise RegistryError(
                    operation,
                    f"Missing required fields {sorted(missing)} "
                    f"on line {line_num} of '{self._path}'",
                )

            prev_hash = data.get("prev_hash")
            if prev_hash is not None and not isinstance(prev_hash, str):
                raise RegistryError(
                    operation,
                    f"Invalid prev_hash type on line {line_num} of "
                    f"'{self._path}': expected string or null",
                )

            entries.append(
                RegistryEntry(
                    entry_id=data["entry_id"],
                    node_id=data["node_id"],
                    contract_hash=data["contract_hash"],
                    contract_source=data["contract_source"],
                    registered_at=data["registered_at"],
                    version=data["version"],
                    content=data["content"],
                    path=data["path"],
                    prev_hash=prev_hash,
                )
            )
        return entries

    def _rewrite_file(self, entries: list[RegistryEntry]) -> None:
        """Atomically replace the registry with a full chained history."""
        payload = "".join(
            canonical_entry_bytes(entry).decode("utf-8") + "\n"
            for entry in entries
        )
        tmp_path: Optional[str] = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
            )
            with open(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(payload)
            os.replace(tmp_path, self._path)
            tmp_path = None
        except Exception as exc:
            if isinstance(exc, RegistryError):
                raise
            raise RegistryError(
                "upgrade_chain",
                f"Failed to rewrite registry file '{self._path}': {exc}",
            ) from exc
        finally:
            if tmp_path is not None:
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass

    def _append_to_file(self, entry: RegistryEntry) -> None:
        """Append one entry as a single JSON line to the registry file.

        Uses atomic write pattern: write to temp file in the same
        directory, then append to the registry file.
        Never truncates or rewrites the existing file.

        The persisted bytes come from :func:`scyvera.chain.canonical_entry_bytes`
        — the same function the chain hashes — so stored and hashed bytes can
        never diverge.
        """
        entry_json = canonical_entry_bytes(entry).decode("utf-8")

        try:
            # Write to a temp file first for atomicity
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
            )
            try:
                with open(fd, "w", encoding="utf-8") as tmp_file:
                    tmp_file.write(entry_json)

                # Read temp content and append to registry
                tmp_content = Path(tmp_path).read_text(encoding="utf-8")
                with open(self._path, "a", encoding="utf-8") as registry_file:
                    registry_file.write(tmp_content + "\n")
            finally:
                # Clean up temp file
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    pass
        except Exception as exc:
            if isinstance(exc, RegistryError):
                raise
            raise RegistryError(
                "append",
                f"Failed to write entry to registry file '{self._path}': {exc}",
            ) from exc
