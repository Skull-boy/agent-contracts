import argparse
import importlib.util
import json
import sys
from pathlib import Path

import yaml

from .audit import AuditError, scan_tree
from .conformance import (
    CheckTier,
    Tier1Adapter,
    Tier1ContractError,
    Tier1UnavailableError,
    TierNotImplementedError,
    check_contract,
    render_check,
    resolve_tier,
)
from .exceptions import ContractFileNameError
from .generate import build_draft, write_draft
from .linter import lint_contract
from .packs import PackError, load_pack
from .report import render_badge, render_report
from .validator import validate_contract

# Loaded tier 1 adapters, keyed by absolute source path, so repeated checks in
# one process do not re-exec the adapter module.
_TIER1_ADAPTERS: dict[str, Tier1Adapter] = {}


def _load_tier1_adapter_module(path: Path) -> Tier1Adapter | None:
    """Load ``tier1.py`` by path (``implementations/`` is not installed)."""
    key = str(path.resolve())
    cached = _TIER1_ADAPTERS.get(key)
    if cached is not None:
        return cached

    module_name = f"_scyvera_tier1_adapter_{len(_TIER1_ADAPTERS)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode

    factory = getattr(module, "create_adapter", None)
    if callable(factory):
        adapter = factory()
    else:
        adapter_type = getattr(module, "N8nTier1Adapter", None)
        if not isinstance(adapter_type, type):
            return None
        adapter = adapter_type()

    if not isinstance(adapter, Tier1Adapter):
        return None
    _TIER1_ADAPTERS[key] = adapter
    return adapter


def _contract_framework(contract_path: Path) -> str | None:
    """Read the ``framework`` key from a contract, if it is readable.

    Discovery stays filesystem-only: an unreadable or malformed contract is
    simply not a claim, leaving the normal "no tier 1 adapter" path intact.
    """
    if not contract_path.is_file():
        return None
    try:
        with contract_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return None
    if isinstance(data, dict):
        framework = data.get("framework")
        if isinstance(framework, str):
            return framework.strip().lower()
    return None


def _has_python_source(target: Path) -> bool:
    """Whether ``target`` contains at least one non-cache Python source file."""
    if not target.is_dir():
        return False
    return any(
        path.is_file() and "__pycache__" not in path.parts
        for path in target.rglob("*.py")
    )


def _discover_tier1_adapter(target: Path) -> Tier1Adapter | None:
    """Find a tier 1 adapter that claims ``target``.

    Discovery is filesystem-only and mirrors the repository layout:

    - n8n: the target contains ``workflow.json``; use a sibling ``tier1.py``
      or walk up to ``implementations/n8n/tier1.py``. Behaviour is unchanged
      from M2.2, including the rule that a workflow target never falls
      through to another adapter.
    - LangGraph: the target contains a ``contract.yaml`` whose ``framework``
      is ``langgraph``, or the target contains Python source and a parent
      chain exposes ``implementations/langgraph/tier1.py``. Both checks read
      the filesystem only and are deterministic.
    """
    if (target / "workflow.json").is_file():
        sibling = target / "tier1.py"
        if sibling.is_file():
            return _load_tier1_adapter_module(sibling)
        for base in (target, *target.parents):
            nested = base / "implementations" / "n8n" / "tier1.py"
            if nested.is_file():
                return _load_tier1_adapter_module(nested)
        return None

    langgraph_claim = (
        _contract_framework(target / "contract.yaml") == "langgraph"
        or _has_python_source(target)
    )
    if not langgraph_claim:
        return None

    sibling = target / "tier1.py"
    if sibling.is_file():
        return _load_tier1_adapter_module(sibling)
    for base in (target, *target.parents):
        nested = base / "implementations" / "langgraph" / "tier1.py"
        if nested.is_file():
            return _load_tier1_adapter_module(nested)
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scyvera",
        description="Validate and manage Agent Contract files.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # validate subcommand
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an Agent Contract against its specification schema.",
    )

    validate_parser.add_argument(
        "contract",
        type=Path,
        help="Path to contract.yaml",
    )

    validate_parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to custom JSON Schema file",
    )

    # lint subcommand
    lint_parser = subparsers.add_parser(
        "lint",
        help="Perform Tier 2 semantic analysis on an Agent Contract.",
    )

    lint_parser.add_argument(
        "contract",
        type=Path,
        help="Path to contract.yaml",
    )

    # check subcommand (RFC 0003 §C3, roadmap M2.1)
    check_parser = subparsers.add_parser(
        "check",
        help="Run RFC 0003 §C3 conformance checks against a contract.",
        description=(
            "Run the conformance check for [contract]. Tier 0 (structural) "
            "is a superset of `scyvera validate` + `scyvera lint`: one "
            "report combining schema errors and ACxxx semantic warnings. "
            "Tier 1 (static) inspects an implementation directory such as an "
            "n8n workflow and reports T101/T102/T103 findings. Tier 2 is "
            "reserved for the runtime-trace adapter and fails loudly until it "
            "ships (never silently)."
        ),
        epilog=("exit codes: 0 pass (or warn-only), 1 fail, 2 usage/IO error"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    check_parser.add_argument(
        "contract",
        type=Path,
        help=(
            "Path to contract.yaml, or an implementation directory for "
            "--tier 1 (n8n: contract.yaml + workflow.json; LangGraph: "
            "contract.yaml + Python source)"
        ),
    )

    check_parser.add_argument(
        "--tier",
        type=str,
        choices=["0", "1", "2", "auto"],
        default="auto",
        help=(
            "Conformance tier: 0 structural (schema + lint), 1 static "
            "(adapter; M2.2), 2 runtime-trace (M2.4); auto resolves to tier 0 "
            "with an explicit notice"
        ),
    )

    check_parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to custom JSON Schema file (tier 0 only)",
    )

    # audit subcommand
    audit_parser = subparsers.add_parser(
        "audit",
        help="Scan a path for agent blast-radius findings.",
        description=(
            "Scan [path] (default `.`) with the AUxxx rule registry and print "
            "the Blast Radius Report. Read-only unless --generate writes one "
            "contract draft."
        ),
        epilog=(
            "exit codes: 0 ok, 1 findings or threshold breach, "
            "2 usage/IO error"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    audit_parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Directory or file to scan (default: .)",
    )

    audit_parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit the machine-readable report (report_version: 1) and "
            "nothing else"
        ),
    )

    audit_parser.add_argument(
        "--badge",
        action="store_true",
        help=(
            "Append a shields.io Blast Radius badge (band only, no score); "
            "with --json, adds a top-level \"badge\" key"
        ),
    )

    audit_parser.add_argument(
        "--fail-under",
        metavar="SCORE",
        default=None,
        help=(
            "Exit 1 when the Blast Radius score is below SCORE "
            "(an integer from 0 to 100)"
        ),
    )

    audit_parser.add_argument(
        "--generate",
        metavar="CONTRACT",
        type=Path,
        default=None,
        help=(
            "Write a v1.1 contract draft derived from scored findings to "
            "CONTRACT (use a .yaml name); the report still prints"
        ),
    )

    audit_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the --generate target when it already exists",
    )

    audit_parser.add_argument(
        "--pack",
        metavar="NAME",
        default=None,
        help=(
            "Apply a local Policy Pack from packs/<NAME>.yaml to the "
            "--generate draft (requires --generate)"
        ),
    )

    # init subcommand
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize a new Agent Contract starter template.",
    )

    init_parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=Path("contract.yaml"),
        help="Target output path (default: contract.yaml)",
    )

    init_parser.add_argument(
        "--name",
        type=str,
        default="My System",
        help="System or agent name",
    )

    init_parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Operational domain (e.g. healthcare, finance, education, research, software, business)",
    )

    init_parser.add_argument(
        "--spec-version",
        type=str,
        choices=["1.1", "1"],
        default="1.1",
        help="Specification version (default: 1.1)",
    )

    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite target file if it already exists",
    )

    init_parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Prompt interactively for contract details",
    )

    return parser


def run_validate(contract_path: Path, schema_path: Path | None = None) -> int:
    try:
        result = validate_contract(contract_path, schema_path=schema_path)

    except FileNotFoundError:
        print(f"ERROR  {contract_path}")
        print("       file not found")
        return 2

    except PermissionError:
        print(f"ERROR  {contract_path}")
        print("       permission denied")
        return 2

    except yaml.YAMLError as error:
        print(f"FAIL  {contract_path}")
        print(f"      invalid YAML: {error}")
        return 1

    if result.valid:
        print(f"PASS  {contract_path}")
        return 0

    print(f"FAIL  {contract_path}")

    for error in result.errors:
        if error.path:
            print(f"      {error.path}: {error.message}")
        else:
            print(f"      {error.message}")

    return 1


def run_check(
    contract_path: Path,
    tier: str = "auto",
    schema_path: Path | None = None,
) -> int:
    """Run the RFC 0003 §C3 conformance check and return its exit code.

    Tier 1 accepts either a contract file or an implementation directory; for
    a directory the adapter inspects ``workflow.json`` next to
    ``contract.yaml``. Exit codes: ``0`` pass (or warn-only, matching
    ``scyvera lint``), ``1`` fail (including any T101 or error-severity T102
    finding), ``2`` usage/IO error, including an explicit tier 2 request or a
    tier 1 target no adapter claims — per the roadmap's "tier auto-degrades
    with explicit notice, never silently" acceptance rule.
    """
    target = contract_path if contract_path.is_dir() else contract_path.parent
    contract = (
        contract_path / "contract.yaml" if contract_path.is_dir() else contract_path
    )

    try:
        resolved_tier, _ = resolve_tier(tier)
        adapter: Tier1Adapter | None = None
        if resolved_tier is CheckTier.STATIC:
            adapter = _discover_tier1_adapter(target)
            if adapter is None:
                print(
                    f"scyvera check: error: no tier 1 adapter for {target} "
                    "(expected workflow.json + contract.yaml with a supported "
                    "adapter)",
                    file=sys.stderr,
                )
                return 2
        report = check_contract(
            contract,
            schema_path=schema_path,
            tier=tier,
            target=target,
            adapter=adapter,
        )
    except TierNotImplementedError as error:
        print(f"scyvera check: error: {error}", file=sys.stderr)
        return 2
    except Tier1UnavailableError as error:
        print(f"scyvera check: error: {error}", file=sys.stderr)
        return 2
    except Tier1ContractError as error:
        print(f"FAIL  {contract}")
        print(f"      cannot run tier 1: {error}")
        return 1
    except ContractFileNameError as error:
        print(f"scyvera check: error: {error}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"ERROR  {contract}")
        print("       file not found")
        return 2
    except PermissionError:
        print(f"ERROR  {contract}")
        print("       permission denied")
        return 2
    except yaml.YAMLError as error:
        print(f"FAIL  {contract}")
        print(f"      invalid YAML: {error}")
        return 1

    print(render_check(report), end="")

    return 1 if (not report.valid or report.tier1_failed) else 0


def run_init(
    output_path: Path,
    name: str = "My System",
    domain: str | None = None,
    spec_version: str = "1.1",
    force: bool = False,
    interactive: bool = False,
) -> int:
    if output_path.exists() and not force:
        print(f"ERROR  {output_path} already exists. Use --force to overwrite.")
        return 1

    purpose = "Operational contract for intelligent/automated system"
    risk_level = "low"

    if interactive:
        try:
            user_name = input(f"System Name [{name}]: ").strip()
            if user_name:
                name = user_name
            user_domain = input("Domain (e.g. healthcare, finance, education, research, software, business): ").strip()
            if user_domain:
                domain = user_domain
            user_purpose = input("Purpose/Description: ").strip()
            if user_purpose:
                purpose = user_purpose
            user_risk = input("Risk Level (low/medium/high/critical) [low]: ").strip()
            if user_risk in ("low", "medium", "high", "critical"):
                risk_level = user_risk
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    if spec_version == "1.1":
        contract_data: dict[str, Any] = {
            "version": 1.1,
            "system": {
                "name": name,
                "purpose": purpose,
                "version": "1.0.0",
            },
        }
        if domain:
            contract_data["domain"] = domain

        contract_data.update({
            "capabilities": [
                {"name": "example_capability", "description": "Example capability claim"}
            ],
            "resources": [
                {"name": "example_resource", "type": "dataset", "access": "read"}
            ],
            "inputs": [
                {"name": "example_input", "type": "string", "required": True}
            ],
            "outputs": [
                {"name": "example_output", "type": "document"}
            ],
            "permissions": [
                {"resource": "example_resource", "actions": ["read"]}
            ],
            "side_effects": [],
            "approvals": [],
            "dependencies": [],
            "state": {"persistence": "session"},
            "recovery": {"strategy": "retry"},
            "replay": {"mode": "idempotent"},
            "observability": {"level": "basic"},
            "risk": {"level": risk_level},
        })
    else:
        contract_data = {
            "version": 1,
            "workflow": name,
            "inputs": ["example_input"],
            "outputs": ["example_output"],
            "permissions": [{"example_resource": "read"}],
            "side_effects": [],
            "approval_points": [],
            "recovery_strategy": "retry",
            "replay_semantics": "idempotent",
            "dependencies": [],
            "state": "session",
            "observability": ["basic_logs"],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump(contract_data, f, sort_keys=False)

    print(f"CREATED {output_path} (spec version {spec_version})")
    return 0


def run_lint(contract_path: Path) -> int:
    try:
        result = lint_contract(contract_path)
    except FileNotFoundError:
        print(f"ERROR  {contract_path}")
        print("       file not found")
        return 2
    except PermissionError:
        print(f"ERROR  {contract_path}")
        print("       permission denied")
        return 2
    except yaml.YAMLError as error:
        print(f"FAIL  {contract_path}")
        print(f"      invalid YAML: {error}")
        return 1

    if not result.valid_structure:
        print(f"FAIL  {contract_path} (structural validation failed)")
        for w in result.warnings:
            print(f"      [{w.rule_id}] {w.title}: {w.message}")
        return 1

    if not result.warnings:
        print(f"PASS  {contract_path} (0 semantic warnings)")
        return 0

    print(f"WARN  {contract_path} ({len(result.warnings)} semantic warning(s))")
    for w in result.warnings:
        print(f"      [{w.rule_id}] {w.title}: {w.message}")

    return 0


def _parse_fail_under(raw: str | None) -> int | None:
    """Return a valid 0–100 threshold, or ``None`` when absent or invalid.

    Only an optional sign followed by ASCII digits is accepted, so inputs
    such as ``"1_0"`` (which :func:`int` would otherwise accept) are rejected
    with the same actionable one-line error as ``"abc"``.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    digits = candidate[1:] if candidate[:1] in {"+", "-"} else candidate
    if not digits or not digits.isascii() or not digits.isdigit():
        return None
    value = int(candidate)
    if 0 <= value <= 100:
        return value
    return None


def run_audit(
    path: Path,
    as_json: bool = False,
    badge: bool = False,
    fail_under: str | None = None,
    generate: Path | None = None,
    force: bool = False,
    pack: str | None = None,
) -> int:
    """Run the audit command and return its process exit code.

    Exit codes follow RFC 0004 §2: ``0`` ok, ``1`` findings or a
    ``--fail-under`` threshold breach, ``2`` usage or I/O error. With
    ``--generate`` the command additionally writes one contract draft
    (RFC 0004 §5); nothing else is ever written.
    """
    if pack is not None and generate is None:
        print(
            "scyvera audit: error: --pack requires --generate <contract>",
            file=sys.stderr,
        )
        return 2

    policy_pack = None
    if pack is not None:
        try:
            policy_pack = load_pack(pack)
        except PackError as error:
            print(f"scyvera audit: error: {error}", file=sys.stderr)
            return 2

    if force and generate is None:
        print(
            "scyvera audit: error: --force requires --generate",
            file=sys.stderr,
        )
        return 2

    threshold = _parse_fail_under(fail_under)
    if fail_under is not None and threshold is None:
        print(
            "scyvera audit: error: --fail-under must be an integer "
            "between 0 and 100",
            file=sys.stderr,
        )
        return 2

    if generate is not None:
        if generate.suffix == ".yml":
            print(
                f"scyvera audit: error: {generate} must use the .yaml "
                "extension so `scyvera validate` can load it",
                file=sys.stderr,
            )
            return 2
        if generate.exists() and not force:
            print(
                f"scyvera audit: error: {generate} exists; "
                "pass --force to overwrite",
                file=sys.stderr,
            )
            return 2

    try:
        report = scan_tree(path)
    except FileNotFoundError:
        print(f"ERROR  {path}")
        print("       file not found")
        return 2
    except PermissionError:
        print(f"ERROR  {path}")
        print("       permission denied")
        return 2
    except AuditError as error:
        print(f"ERROR  {path}")
        print(f"       {error}")
        return 2

    draft_path: str | None = None
    if generate is not None:
        try:
            write_draft(
                build_draft(report, pack=policy_pack),
                generate,
            )
        except PermissionError:
            print(
                f"scyvera audit: error: cannot write {generate}: "
                "permission denied",
                file=sys.stderr,
            )
            return 2
        except OSError as error:
            print(
                f"scyvera audit: error: cannot write {generate}: {error}",
                file=sys.stderr,
            )
            return 2
        draft_path = str(generate)

    scored = [finding for finding in report.findings if finding.scored]

    if as_json:
        if badge or draft_path is not None:
            payload = report.to_dict()
            if badge:
                payload["badge"] = render_badge(report)
            if draft_path is not None:
                payload["draft_path"] = draft_path
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(report.to_json())
    else:
        print(render_report(report))
        if draft_path is not None:
            print(
                f"Draft contract written to {draft_path} "
                f"(validate with: scyvera validate {draft_path})."
            )
        if badge:
            print(render_badge(report))

    if threshold is not None:
        return 0 if report.score >= threshold else 1
    return 0 if not scored else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "validate":
        return run_validate(args.contract, schema_path=args.schema)

    if args.command == "lint":
        return run_lint(args.contract)

    if args.command == "check":
        return run_check(args.contract, tier=args.tier, schema_path=args.schema)

    if args.command == "audit":
        return run_audit(
            args.path,
            as_json=args.json,
            badge=args.badge,
            fail_under=args.fail_under,
            generate=args.generate,
            force=args.force,
            pack=args.pack,
        )

    if args.command == "init":
        return run_init(
            output_path=args.output,
            name=args.name,
            domain=args.domain,
            spec_version=args.spec_version,
            force=args.force,
            interactive=args.interactive,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())