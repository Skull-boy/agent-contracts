"""Typed guardrail model and parsing for RFC 0003 §C5 (roadmap M2.6).

The v1.2 schema adds one optional top-level ``guardrails`` object::

    guardrails:
      fail_closed: true
      budgets:
        side_effects_per_window: 10
        window: "1h"
      rate_limit:
        max_calls_per_minute: 30

This module owns the frozen in-memory representation and window parsing. It is
deliberately pure: no I/O, no clock access, no printing. The enforcer supplies
time through its injected ``clock`` and owns the per-instance counters.

All blocks are optional. An empty ``guardrails: {}`` is an explicit no-op:
``fail_closed`` defaults to ``False`` and no counters are enforced, so behavior
is byte-for-byte today's behavior. Omitted ``guardrails`` parses to ``None``.

Honest limitation: budget and rate counters are **per enforcer instance and
per process**. They bound a single runtime's behavior; they are not a
distributed quota shared across replicas.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

__all__ = [
    "BUDGETS_FIELD_REFERENCE",
    "FAIL_CLOSED_FIELD_REFERENCE",
    "RATE_LIMIT_FIELD_REFERENCE",
    "RATE_LIMIT_WINDOW_SECONDS",
    "Budgets",
    "GuardrailConfigError",
    "Guardrails",
    "RateLimit",
    "parse_guardrails",
    "parse_window",
]

#: Audit ``contract_field_reference`` values pinned by the enforcement tests.
FAIL_CLOSED_FIELD_REFERENCE: str = "guardrails.fail_closed"
BUDGETS_FIELD_REFERENCE: str = "guardrails.budgets"
RATE_LIMIT_FIELD_REFERENCE: str = "guardrails.rate_limit"

#: RFC 0003 §C5 pins the rate limit to a one-minute window.
RATE_LIMIT_WINDOW_SECONDS: int = 60

_WINDOW_PATTERN = re.compile(r"^([0-9]+)(s|m|h|d)$")
_WINDOW_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
}


class GuardrailConfigError(ValueError):
    """Raised when a guardrails block is structurally unusable.

    The v1.2 JSON Schema already rejects these shapes for file contracts, so
    this is primarily the fail-closed path for runtime declarations and for a
    caller that bypassed validation. It is a ``ValueError`` so callers can
    treat it as ordinary bad input rather than a contract violation.
    """


@dataclass(frozen=True)
class Budgets:
    """Declared side-effect budget (RFC 0003 §C5).

    ``window`` is the original human-readable string (e.g. ``"1h"``) and
    ``window_seconds`` is the parsed duration used by the sliding counter.
    """

    side_effects_per_window: int
    window: str
    window_seconds: int


@dataclass(frozen=True)
class RateLimit:
    """Declared per-minute invocation rate limit (RFC 0003 §C5)."""

    max_calls_per_minute: int


@dataclass(frozen=True)
class Guardrails:
    """Frozen guardrail policy attached to one enforcer instance.

    ``fail_closed`` defaults to ``False``. Set it to ``True`` in the contract
    to deny (instead of permit) when guardrail evaluation itself fails, for
    example because the supplied clock raised or the in-memory counter state
    was corrupted.
    """

    fail_closed: bool = False
    budgets: Optional[Budgets] = None
    rate_limit: Optional[RateLimit] = None


def parse_window(value: str) -> int:
    """Parse an RFC 0003 §C5 window such as ``"30m"`` into seconds.

    Args:
        value: Window string matching ``^[0-9]+(s|m|h|d)$``.

    Returns:
        The window duration in whole seconds.

    Raises:
        GuardrailConfigError: If the value does not match the grammar or is
            zero seconds.
    """
    if not isinstance(value, str):
        raise GuardrailConfigError(
            f"guardrails window must be a string like '1h', got {type(value).__name__}"
        )
    match = _WINDOW_PATTERN.match(value)
    if match is None:
        raise GuardrailConfigError(
            f"guardrails window '{value}' must match ^[0-9]+(s|m|h|d)$ "
            "(examples: '30m', '1h', '7d')"
        )
    amount = int(match.group(1))
    if amount <= 0:
        raise GuardrailConfigError(
            f"guardrails window '{value}' must be greater than zero"
        )
    return amount * _WINDOW_MULTIPLIERS[match.group(2)]


def _require_positive_int(value: Any, field: str) -> int:
    """Return ``value`` when it is an integer >= 1, else fail closed."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardrailConfigError(
            f"guardrails.{field} must be an integer >= 1, got {type(value).__name__}"
        )
    if value < 1:
        raise GuardrailConfigError(
            f"guardrails.{field} must be >= 1, got {value}"
        )
    return value


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    """Return ``value`` when it is a mapping, else fail closed."""
    if not isinstance(value, dict):
        raise GuardrailConfigError(
            f"guardrails.{field} must be an object, got {type(value).__name__}"
        )
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], field: str) -> None:
    """Reject keys outside ``allowed`` (schema parity for declarations)."""
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise GuardrailConfigError(
            f"guardrails.{field} has unknown key(s): {', '.join(unknown)}"
        )


def parse_guardrails(raw: Any) -> Optional[Guardrails]:
    """Build the frozen guardrail record from a contract mapping.

    Args:
        raw: The value of the top-level ``guardrails`` key, or ``None``.

    Returns:
        ``None`` when the key is absent, otherwise a frozen
        :class:`Guardrails` value. ``{}`` yields a no-op record with
        ``fail_closed=False`` and no counters.

    Raises:
        GuardrailConfigError: On any malformed shape. This mirrors the v1.2
            schema's ``additionalProperties: false`` and positive-integer
            constraints so runtime declarations cannot smuggle a shape the
            schema would reject.
    """
    if raw is None:
        return None

    data = _require_mapping(raw, "<root>")
    _reject_unknown(data, {"fail_closed", "budgets", "rate_limit"}, "<root>")

    fail_closed = data.get("fail_closed", False)
    if not isinstance(fail_closed, bool):
        raise GuardrailConfigError(
            "guardrails.fail_closed must be a boolean, got "
            f"{type(fail_closed).__name__}"
        )

    budgets: Optional[Budgets] = None
    if "budgets" in data:
        budgets_raw = _require_mapping(data["budgets"], "budgets")
        _reject_unknown(
            budgets_raw,
            {"side_effects_per_window", "window"},
            "budgets",
        )
        if "side_effects_per_window" not in budgets_raw:
            raise GuardrailConfigError(
                "guardrails.budgets requires 'side_effects_per_window'"
            )
        if "window" not in budgets_raw:
            raise GuardrailConfigError("guardrails.budgets requires 'window'")
        limit = _require_positive_int(
            budgets_raw["side_effects_per_window"],
            "budgets.side_effects_per_window",
        )
        window = budgets_raw["window"]
        budgets = Budgets(
            side_effects_per_window=limit,
            window=window if isinstance(window, str) else str(window),
            window_seconds=parse_window(window),
        )

    rate_limit: Optional[RateLimit] = None
    if "rate_limit" in data:
        rate_raw = _require_mapping(data["rate_limit"], "rate_limit")
        _reject_unknown(rate_raw, {"max_calls_per_minute"}, "rate_limit")
        if "max_calls_per_minute" not in rate_raw:
            raise GuardrailConfigError(
                "guardrails.rate_limit requires 'max_calls_per_minute'"
            )
        rate_limit = RateLimit(
            max_calls_per_minute=_require_positive_int(
                rate_raw["max_calls_per_minute"],
                "rate_limit.max_calls_per_minute",
            )
        )

    return Guardrails(
        fail_closed=fail_closed,
        budgets=budgets,
        rate_limit=rate_limit,
    )
