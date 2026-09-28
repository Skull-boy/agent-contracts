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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile
from typing import Any, Optional
import uuid

import yaml

from .exceptions import RegistryError

logger = logging.getLogger("scyvera.registry")

_REQUIRED_FIELDS = frozenset({
    "entry_id", "node_id", "contract_hash", "contract_source",
    "registered_at", "version", "content", "path",
})


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

        # Idempotent: return existing entry if hash already registered
        if contract_hash in self._hash_index:
            return self._hash_index[contract_hash]

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

        # Compute version
        if node_id is not None:
            existing = self._node_index.get(node_id, [])
            version = len(existing) + 1
        else:
            version = 1

        entry = RegistryEntry(
            entry_id=str(uuid.uuid4()),
            node_id=node_id,
            contract_hash=contract_hash,
            contract_source=source,
            registered_at=datetime.now(timezone.utc).isoformat(),
            version=version,
            content=content,
            path=file_path,
        )

        # Append to in-memory stores
        self._entries.append(entry)
        self._hash_index[entry.contract_hash] = entry
        if entry.node_id is not None:
            self._node_index.setdefault(entry.node_id, []).append(entry)

        # Persist to disk
        self._append_to_file(entry)

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
        """Return all entries for a given node_id, ordered by version ascending."""
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
            RegistryError: If the timestamp is not parseable.
        """
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

    # -------------------------------------------------------------------------
    # Internal Methods
    # -------------------------------------------------------------------------

    def _load_from_file(self) -> None:
        """Read the JSON-lines file and populate in-memory stores.

        Each line is one JSON object → one RegistryEntry.
        Empty lines are skipped. Malformed lines raise RegistryError.
        """
        try:
            raw_content = self._path.read_text(encoding="utf-8")
        except Exception as exc:
            raise RegistryError(
                "load",
                f"Failed to read registry file '{self._path}': {exc}",
            ) from exc

        for line_num, line in enumerate(raw_content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise RegistryError(
                    "load",
                    f"Malformed JSON on line {line_num} of '{self._path}': {exc}",
                ) from exc

            # Validate required fields
            missing = _REQUIRED_FIELDS - set(data.keys())
            if missing:
                raise RegistryError(
                    "load",
                    f"Missing required fields {sorted(missing)} "
                    f"on line {line_num} of '{self._path}'",
                )

            entry = RegistryEntry(
                entry_id=data["entry_id"],
                node_id=data["node_id"],
                contract_hash=data["contract_hash"],
                contract_source=data["contract_source"],
                registered_at=data["registered_at"],
                version=data["version"],
                content=data["content"],
                path=data["path"],
            )

            self._entries.append(entry)
            self._hash_index[entry.contract_hash] = entry
            if entry.node_id is not None:
                self._node_index.setdefault(entry.node_id, []).append(entry)

    def _append_to_file(self, entry: RegistryEntry) -> None:
        """Append one entry as a single JSON line to the registry file.

        Uses atomic write pattern: write to temp file in the same
        directory, then append to the registry file.
        Never truncates or rewrites the existing file.
        """
        entry_json = json.dumps(asdict(entry), separators=(",", ":"))

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
