"""Convention pins for the PD-6 composite gate (roadmap PD-6).

These are static checks, not execution: GitHub Actions runs the composite,
never pytest. Nothing here shells out, reaches the network, or needs a GitHub
runner. The YAML is parsed with ``yaml.safe_load`` and the assertions pin the
interface and supply-chain conventions — SHA pins, least-privilege tokens, the
0/1/2 exit map, and the dogfood wiring — so a regression in the gate's
declared contract is caught in the normal test suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / ".github" / "actions" / "scyvera-gate" / "action.yml"
README = ROOT / ".github" / "actions" / "scyvera-gate" / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "scyvera-dogfood.yml"

SHA_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
FLOATING_RE = re.compile(r"@(main|master|latest|HEAD|v\d+(?:\.\d+)*)$")

EXPECTED_INPUTS = {
    "mode",
    "target",
    "tier",
    "report-format",
    "badge",
    "exit-on-finding",
    "source",
    "python-version",
}
EXPECTED_OUTPUTS = {"score", "status", "findings", "exit-code", "unified-json"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _workflow_steps(document: dict):
    for job_name, job in document["jobs"].items():
        for step in job.get("steps", []):
            yield job_name, step


def _all_uses(document: dict) -> list[str]:
    steps = list(document.get("runs", {}).get("steps", []))
    for job in document.get("jobs", {}).values():
        steps.extend(job.get("steps", []))
    return [step["uses"] for step in steps if "uses" in step]


def _is_third_party(uses: str) -> bool:
    return not uses.startswith(("./", "docker://"))


def _run_steps(document: dict):
    return [
        step
        for step in document["runs"]["steps"]
        if isinstance(step, dict) and "run" in step
    ]


def test_action_is_a_composite() -> None:
    action = _load(ACTION)
    assert action["runs"]["using"] == "composite"
    assert action["name"].strip()
    assert action["description"].strip()


def test_action_inputs_match_the_documented_contract() -> None:
    inputs = _load(ACTION)["inputs"]
    assert set(inputs) == EXPECTED_INPUTS
    assert inputs["target"]["required"] is True
    assert inputs["mode"]["default"] == "audit"
    assert inputs["tier"]["default"] == "auto"
    assert inputs["report-format"]["default"] == "text"
    assert inputs["badge"]["default"] == ""
    assert inputs["exit-on-finding"]["default"] == "true"
    assert inputs["source"]["default"] == "pypi"
    assert inputs["python-version"]["default"] == "3.12"


def test_action_outputs_cover_the_m25_envelope() -> None:
    outputs = _load(ACTION)["outputs"]
    assert set(outputs) == EXPECTED_OUTPUTS
    for name, spec in outputs.items():
        assert spec["value"].startswith("${{ steps.run.outputs."), name


def test_third_party_actions_are_sha_pinned() -> None:
    action = _load(ACTION)
    workflow = _load(WORKFLOW)
    pinned = [
        uses
        for uses in _all_uses(action) + _all_uses(workflow)
        if _is_third_party(uses)
    ]
    # action.yml (setup-python) + dogfood checkout + setup-python via the
    # action itself; every one must carry a full 40-character commit SHA.
    assert pinned
    for uses in pinned:
        assert SHA_RE.match(uses), f"third-party action is not SHA-pinned: {uses}"


def test_no_floating_or_major_only_action_refs() -> None:
    for uses in _all_uses(_load(ACTION)) + _all_uses(_load(WORKFLOW)):
        assert not FLOATING_RE.search(uses), f"floating action ref: {uses}"


def test_workflow_declares_least_privilege_permissions() -> None:
    workflow = _load(WORKFLOW)
    assert workflow["permissions"] == {"contents": "read"}
    for job_name, job in workflow["jobs"].items():
        assert "permissions" in job, f"{job_name} has no permissions block"
        assert job["permissions"] == {"contents": "read"}, job_name


def test_action_declares_no_permissions_key() -> None:
    # Composite actions cannot carry a token scope of their own; the calling
    # job's permissions block is the enforcement point. This pin documents the
    # split so nobody adds an ignored key that looks like protection.
    assert "permissions" not in _load(ACTION)


def test_no_unbounded_wildcard_permissions() -> None:
    documents = [_load(ACTION), _load(WORKFLOW)]
    for document in documents:
        scopes = [document.get("permissions")]
        if "jobs" in document:
            scopes.extend(job.get("permissions") for job in document["jobs"].values())
        for scope in scopes:
            if scope is None:
                continue
            assert "*" not in scope.values()
            assert "write-all" not in scope.values()
            assert "read-all" not in scope.values()


def test_python_floor_is_at_least_3_10() -> None:
    action = _load(ACTION)
    default = action["inputs"]["python-version"]["default"]
    major, minor = (int(part) for part in str(default).split(".")[:2])
    assert (major, minor) >= (3, 10)

    for path in (ACTION, WORKFLOW):
        text = path.read_text(encoding="utf-8")
        assert "3.8" not in text
        assert "3.9" not in text


def test_exit_code_map_is_pinned_to_0_1_2() -> None:
    (run_step,) = [step for step in _run_steps(_load(ACTION)) if step.get("id") == "run"]
    script = run_step["run"]

    assert 'case "$code" in' in script
    for branch in ("0)", "1)", "2)"):
        assert branch in script
    assert "exit_code=$code" in script

    # 2 is always an action error; 1 is fatal only when the caller asks.
    decision_scripts = [
        (step.get("name", ""), step.get("if", ""), step.get("run", ""))
        for step in _run_steps(_load(ACTION))
    ]
    assert any(
        "exit_code == '2'" in condition and "exit 1" in body
        for _, condition, body in decision_scripts
    )
    assert any(
        "exit_code == '1'" in condition
        and "exit-on-finding == 'true'" in condition
        and "exit 1" in body
        for _, condition, body in decision_scripts
    )
    assert any(
        "exit_code == '1'" in condition
        and "exit-on-finding != 'true'" in condition
        and "::warning::" in body
        for _, condition, body in decision_scripts
    )


def test_run_step_emits_every_declared_output() -> None:
    (run_step,) = [step for step in _run_steps(_load(ACTION)) if step.get("id") == "run"]
    script = run_step["run"]
    for token in (
        ">> \"$GITHUB_OUTPUT\"",
        "score=",
        "status=",
        "findings=",
        "unified_json=",
    ):
        assert token in script


def test_run_steps_use_a_portable_shell() -> None:
    action = _load(ACTION)
    for step in _run_steps(action):
        assert step.get("shell") == "bash"
    for _, step in _workflow_steps(_load(WORKFLOW)):
        if "run" in step:
            assert step.get("shell") == "bash"


def test_badge_is_opt_in() -> None:
    action = _load(ACTION)
    assert action["inputs"]["badge"]["default"] == ""
    assert any(
        "inputs.badge != ''" in step.get("if", "")
        for step in _run_steps(action)
        if "BADGE_FILE" in step.get("env", {})
    )


def test_dogfood_runs_both_modes_against_the_repo() -> None:
    workflow = _load(WORKFLOW)
    calls = [
        step
        for _, step in _workflow_steps(workflow)
        if step.get("uses") == "./.github/actions/scyvera-gate"
    ]
    assert len(calls) == 2
    by_mode = {call["with"]["mode"]: call for call in calls}
    assert set(by_mode) == {"audit", "check"}

    check = by_mode["check"]["with"]
    assert check["source"] == "local"
    assert check["tier"] == "1"
    assert check["target"].startswith("implementations/")

    audit = by_mode["audit"]["with"]
    assert audit["source"] == "local"
    assert audit["target"] == "."
    assert audit["exit-on-finding"] == "false"


def test_dogfood_audit_floor_is_a_warning_only() -> None:
    workflow = _load(WORKFLOW)
    audit_job = workflow["jobs"]["dogfood-audit"]
    scripts = [step.get("run", "") for step in audit_job["steps"]]
    floor = [script for script in scripts if "92" in script]
    assert floor, "the 92-point dogfood floor is not asserted"
    assert any("::warning::" in script for script in floor)
    assert all("exit 1" not in script for script in floor)


def test_dogfood_triggers_on_push_main_and_pull_request() -> None:
    workflow = _load(WORKFLOW)
    # PyYAML implements YAML 1.1, where the bare key `on` parses as True.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" in triggers


def test_action_readme_documents_sha_pinning() -> None:
    text = README.read_text(encoding="utf-8")
    assert "pin to a full commit sha" in text.lower()
    assert "Skull-boy/agent-contracts/.github/actions/scyvera-gate@main" in text
