"""Agent-module loading for the RFC 0003 §C4 eval harness (roadmap M2.4).

An eval case references its agent as ``<module>:<factory>``. The module may be
a file next to the eval case (``agent_eval_fixture`` ->
``<eval-dir>/agent_eval_fixture.py``), a package next to the eval case, or an
importable dotted module. Failures are reported as :class:`EvalCaseError`.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys
from typing import Any, Callable

from .case import EvalCaseError

__all__ = ["import_agent_module", "load_factory"]


def _module_from_file(candidate: Path, module_path: str) -> Any:
    digest = hashlib.sha256(str(candidate).encode("utf-8")).hexdigest()[:16]
    name = f"_scyvera_eval_{digest}"
    spec = importlib.util.spec_from_file_location(name, candidate)
    if spec is None or spec.loader is None:
        raise EvalCaseError(
            f"cannot build an import spec for agent module '{candidate}'"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - re-raised with context
        sys.modules.pop(name, None)
        raise EvalCaseError(
            f"cannot import agent module '{module_path}' from "
            f"'{candidate}': {type(exc).__name__}: {exc}"
        ) from exc
    return module


def import_agent_module(module_path: str, base_dir: Path) -> Any:
    """Import an agent module, preferring a file relative to ``base_dir``."""
    relative = base_dir.joinpath(*module_path.split("."))
    for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
        if candidate.is_file():
            return _module_from_file(candidate, module_path)
    try:
        return importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001 - re-raised with context
        raise EvalCaseError(
            f"cannot import agent module '{module_path}' (looked relative to "
            f"'{base_dir}' and on sys.path): {type(exc).__name__}: {exc}"
        ) from exc


def load_factory(
    module_path: str,
    factory_name: str,
    base_dir: Path,
) -> Callable[[Any], Any]:
    """Return the callable named ``factory_name`` from ``module_path``.

    Raises:
        EvalCaseError: If the module cannot be imported or the attribute is
            missing/not callable.
    """
    module = import_agent_module(module_path, base_dir)
    factory = getattr(module, factory_name, None)
    if factory is None or not callable(factory):
        raise EvalCaseError(
            f"agent factory '{factory_name}' not found or not callable "
            f"in module '{module_path}'"
        )
    return factory
