"""Trace-driven eval harness for RFC 0003 §C4 (roadmap M2.4).

This subpackage runs a Python reference agent against a synthetic scenario
using a real :class:`~scyvera.enforcer.ContractEnforcer`, collects an RFC 0003
§C4 :class:`~scyvera.trace.TraceLog`, and scores the run on four axes:

=============  ==========================================================
Axis           Meaning
=============  ==========================================================
constraints    ``1.0`` iff every trace entry was declared in the contract;
               any undeclared attempt (even a correctly denied one) is
               ``0.0``.
approval       ``1.0`` unless an approval-required or ``irreversible`` side
               effect executes (``ALLOWED``) without an ``approve: true``
               step; an unapproved irreversible execution is ``0.0``.
recovery       ``1.0`` iff the decision sequence matches
               ``expected_trace.decisions`` and no step raised a non-scyvera
               exception. Mechanical proxy for "matches recovery_strategy".
replay         ``1.0`` iff a second run with a fresh enforcer and fresh
               agent produces an identical decision sequence.
=============  ==========================================================

The total is ``100 * sum(score_weights[axis] * axis)``, rounded to six
decimals. ``score_weights`` must be non-negative and sum to ``1.0`` within
``1e-9``.

Usage::

    from scyvera.evals import load_eval_case, run_eval

    case = load_eval_case("implementations/langgraph/<name>/evals/<name>.eval.yaml")
    result = run_eval(case)
    print(result.total, result.axes)

Eval-case format (YAML)::

    version: 1
    name: my-agent
    contract: contract.yaml          # relative to the eval file; must not escape
    agent: agent_fixture:make_agent  # module relative to the eval dir, or importable
    scenario:                        # ordered; non-empty
      - action: github:issues:read
        action_type: read            # side_effect | permission | read
        approve: true                # optional, default false
    expected_trace:
      decisions: [ALLOWED]           # one per scenario step
    score_weights:
      constraints: 0.25
      approval: 0.25
      recovery: 0.25
      replay: 0.25

Agent factory convention: ``factory(enforcer)`` returns an object with one
gated method per scenario action. The method name is the action lowercased
with runs of non-alphanumeric characters replaced by ``_``
(``github:issues:read`` -> ``github_issues_read``). Each method takes no
arguments and should perform exactly one gated call. Both runs build a fresh
enforcer and a fresh agent, so the factory must be callable twice.

The harness is offline and imports only the standard library plus
``scyvera``. Trace timestamps inside :class:`EvalResult` are normalized to a
fixed ISO-8601 sentinel so scores and serialized results are reproducible;
the enforcer's audit log keeps the real wall-clock timestamps. Counters are
per-process and per-enforcer; this is not a distributed eval service.
"""

from .case import (
    EVAL_AXES,
    EvalAxes,
    EvalCase,
    EvalCaseError,
    EvalStep,
    load_eval_case,
)
from .runner import EvalResult, run_eval, run_eval_file

__all__ = [
    "EVAL_AXES",
    "EvalAxes",
    "EvalCase",
    "EvalCaseError",
    "EvalResult",
    "EvalStep",
    "load_eval_case",
    "run_eval",
    "run_eval_file",
]
