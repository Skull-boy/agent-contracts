"""Policy Pack loading and validation (RFC 0004 §6).

A Policy Pack is a local, facts-only YAML artifact at ``packs/<name>.yaml``
that maps domain-recognizable names to draft constraints. Packs contain no
logic, are never fetched over the network, and never replace an audit result
(RFC 0004 §6, §10.2).

The repository-root ``packs/`` directory is the authoring surface; the
byte-identical copy under ``src/scyvera/packs/`` is what ships in the wheel,
mirroring the schema packaging convention. ``tests/test_packs.py`` pins the two
copies together, so a contributor cannot add a pack that works in a checkout
but is missing from an installed package.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from .exceptions import PackError


__all__ = [
    "PACKS_DIR",
    "PackError",
    "PolicyPack",
    "available_packs",
    "load_pack",
    "pack_from_mapping",
]


PACKS_DIR = Path(__file__).resolve().parent / "packs"

_SUPPORTED_CONTRACT_VERSION = "1.1"
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_TOP_LEVEL_KEYS = frozenset(
    {
        "pack",
        "version",
        "domain",
        "description",
        "derive",
        "construction",
    }
)
_DERIVE_KEYS = frozenset(
    {
        "irreversibly_forbidden",
        "requires_approval",
        "cap_side_effects_per_window",
    }
)
_CONSTRUCTION_KEYS = frozenset(
    {
        "contract_version",
        # RFC 0004 §6 names ``construction.cap_*`` in prose while its normative
        # template puts the cap under ``derive``; both locations are accepted.
        "cap_side_effects_per_window",
    }
)

#: Field order used when reporting pack problems. Kept immutable so a caller
#: can never mutate the loader's vocabulary.
_REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "pack",
    "version",
    "domain",
    "description",
    "derive",
    "construction",
)


@dataclass(frozen=True)
class PolicyPack:
    """An immutable, validated Policy Pack (RFC 0004 §6).

    Sequence fields are sorted and de-duplicated so applying the same pack
    twice, or reordering entries in YAML, cannot produce a different draft.
    """

    name: str
    version: str
    domain: str
    description: str
    irreversibly_forbidden: tuple[str, ...]
    requires_approval: tuple[str, ...]
    cap_side_effects_per_window: int | None
    contract_version: str


def _fail(source: str, message: str) -> PackError:
    """Return one actionable pack error prefixed with its source."""
    return PackError(f"{source}: {message}")


def _expect_mapping(
    value: Any,
    *,
    field: str,
    source: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(source, f"'{field}' must be a mapping")
    return value


def _expect_string(value: Any, *, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(source, f"'{field}' must be a non-empty string")
    return value.strip()


def _expect_string_list(
    value: Any,
    *,
    field: str,
    source: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _fail(source, f"'{field}' must be a list of strings")
    items: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _fail(source, f"'{field}' must contain only non-empty strings")
        items.add(item.strip())
    return tuple(sorted(items))


def _reject_unknown_keys(
    mapping: Mapping[str, Any],
    allowed: frozenset[str],
    *,
    field: str,
    source: str,
) -> None:
    unknown = sorted(str(key) for key in set(mapping) - allowed)
    if unknown:
        raise _fail(
            source,
            f"unknown key(s) in '{field}': {', '.join(unknown)}",
        )


def _expect_positive_int(value: Any, *, field: str, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _fail(source, f"'{field}' must be a positive integer")
    return value


def _resolve_cap(
    derive: Mapping[str, Any],
    construction: Mapping[str, Any],
    *,
    source: str,
) -> int | None:
    """Resolve ``cap_side_effects_per_window`` from either RFC §6 location.

    RFC 0004 §6's normative template nests the cap under ``derive``, while the
    bullet immediately below names ``construction.cap_*``. Both spellings are
    therefore accepted. Declaring it in both places is rejected rather than
    silently preferring one, because the pack would then carry two answers with
    no defined precedence.
    """
    derive_cap = derive.get("cap_side_effects_per_window")
    construction_cap = construction.get("cap_side_effects_per_window")
    if derive_cap is not None and construction_cap is not None:
        raise _fail(
            source,
            "specify cap_side_effects_per_window once, under either derive or "
            "construction (RFC 0004 §6 names both)",
        )
    if derive_cap is not None:
        return _expect_positive_int(
            derive_cap,
            field="derive.cap_side_effects_per_window",
            source=source,
        )
    if construction_cap is not None:
        return _expect_positive_int(
            construction_cap,
            field="construction.cap_side_effects_per_window",
            source=source,
        )
    return None


def pack_from_mapping(
    payload: Mapping[str, Any],
    *,
    name: str | None = None,
    source: str = "<mapping>",
) -> PolicyPack:
    """Validate ``payload`` and return an immutable :class:`PolicyPack`.

    The accepted structure is the RFC 0004 §6 template: ``pack``, ``version``,
    ``domain``, ``description``, ``derive.*``, and
    ``construction.contract_version``. ``cap_side_effects_per_window`` is read
    from ``derive`` (template) or ``construction`` (prose), but not both.
    Unknown keys are rejected rather than ignored, so a typo in a contributor's
    pack fails CI instead of silently producing a weaker boundary.
    """
    if not isinstance(payload, Mapping):
        raise _fail(source, "pack must be a YAML mapping")

    _reject_unknown_keys(payload, _TOP_LEVEL_KEYS, field="pack", source=source)
    missing = [field for field in _REQUIRED_TOP_LEVEL if field not in payload]
    if missing:
        raise _fail(source, f"missing required key(s): {', '.join(missing)}")

    pack_name = _expect_string(payload["pack"], field="pack", source=source)
    if not _NAME_PATTERN.match(pack_name):
        raise _fail(
            source,
            f"'pack' must be lowercase words separated by dashes: "
            f"{pack_name!r}",
        )
    if name is not None and pack_name != name:
        raise _fail(
            source,
            f"'pack' is {pack_name!r} but the file/request is named {name!r}",
        )

    derive = _expect_mapping(
        payload["derive"],
        field="derive",
        source=source,
    )
    _reject_unknown_keys(derive, _DERIVE_KEYS, field="derive", source=source)
    if "irreversibly_forbidden" not in derive:
        raise _fail(source, "missing required key(s): derive.irreversibly_forbidden")
    if "requires_approval" not in derive:
        raise _fail(source, "missing required key(s): derive.requires_approval")

    construction = _expect_mapping(
        payload["construction"],
        field="construction",
        source=source,
    )
    _reject_unknown_keys(
        construction,
        _CONSTRUCTION_KEYS,
        field="construction",
        source=source,
    )
    if "contract_version" not in construction:
        raise _fail(
            source,
            "missing required key(s): construction.contract_version",
        )
    contract_version = _expect_string(
        construction["contract_version"],
        field="construction.contract_version",
        source=source,
    )
    if contract_version != _SUPPORTED_CONTRACT_VERSION:
        raise _fail(
            source,
            "unsupported construction.contract_version "
            f"{contract_version!r} (expected {_SUPPORTED_CONTRACT_VERSION!r})",
        )

    cap = _resolve_cap(derive, construction, source=source)

    forbidden = _expect_string_list(
        derive["irreversibly_forbidden"],
        field="derive.irreversibly_forbidden",
        source=source,
    )
    required = _expect_string_list(
        derive["requires_approval"],
        field="derive.requires_approval",
        source=source,
    )
    overlap = set(forbidden) & set(required)
    if overlap:
        raise _fail(
            source,
            "a type cannot be both forbidden and approval-gated: "
            + ", ".join(sorted(overlap)),
        )

    return PolicyPack(
        name=pack_name,
        version=_expect_string(payload["version"], field="version", source=source),
        domain=_expect_string(payload["domain"], field="domain", source=source),
        description=_expect_string(
            payload["description"],
            field="description",
            source=source,
        ),
        irreversibly_forbidden=forbidden,
        requires_approval=required,
        cap_side_effects_per_window=cap,
        contract_version=contract_version,
    )


def _resolve_packs_dir(packs_dir: str | Path | None) -> Path:
    """Return the directory to load packs from (bundled by default)."""
    return Path(packs_dir) if packs_dir is not None else PACKS_DIR


def available_packs(
    *,
    packs_dir: str | Path | None = None,
) -> tuple[str, ...]:
    """Return the sorted names of loadable packs in ``packs_dir``.

    Defaults to the packaged copy so the CLI reports the same set an installed
    user sees. Symlinked entries are omitted, matching the audit engine's
    threat-model T14 refusal.
    """
    directory = _resolve_packs_dir(packs_dir)
    if not directory.is_dir():
        return ()
    names = [
        path.stem
        for path in directory.glob("*.yaml")
        if path.is_file()
        and not path.is_symlink()
        and _NAME_PATTERN.match(path.stem)
    ]
    return tuple(sorted(names))


def load_pack(
    name: str,
    *,
    packs_dir: str | Path | None = None,
) -> PolicyPack:
    """Load and validate the local pack named ``name`` (RFC 0004 §6).

    Resolution is filesystem-only: no network fetch exists in v1, as resolved
    in RFC 0004 §10.2. Names are restricted to lowercase dash-separated words,
    so a name such as ``../contract`` cannot escape the packs directory.
    """
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise PackError(
            "invalid policy pack name: expected lowercase words separated by "
            "dashes"
        )

    directory = _resolve_packs_dir(packs_dir)
    path = directory / f"{name}.yaml"

    if path.is_symlink():
        raise PackError(
            f"refusing to load symlinked policy pack (T14): {path}"
        )
    if not path.is_file():
        available = ", ".join(available_packs(packs_dir=directory)) or "none"
        raise PackError(
            f"unknown policy pack '{name}' (available: {available})"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PackError(f"cannot read policy pack {path}: {error}") from error

    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise PackError(f"invalid YAML in policy pack {path}: {error}") from error

    return pack_from_mapping(payload, name=name, source=str(path))
