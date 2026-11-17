import assert from "node:assert/strict";
import { appendFileSync } from "node:fs";
import test from "node:test";

import {
  ApprovalPendingError,
  ContractTamperError,
  ContractViolationError,
  GuardrailViolationError,
} from "../src/errors.js";
import { ContractEnforcer } from "../src/enforcer.js";
import { TraceLog, traceFromAudit } from "../src/trace.js";
import { baseContract, tempDir, writeContract } from "./helpers.js";

function loaded(
  overrides: Record<string, unknown> = {},
  mode: "full" | "draft" = "full",
): ContractEnforcer {
  const directory = tempDir();
  const path = writeContract(
    directory,
    baseContract({ ...(mode === "draft" ? { provisional: true } : {}), ...overrides }),
  );
  return ContractEnforcer.load(path, { mode });
}

test("a declared permission is allowed and audited", () => {
  const enforcer = loaded();
  enforcer.enforce("github:issues:read", "permission");
  const log = enforcer.getAuditLog();
  assert.equal(log.length, 1);
  assert.equal(log[0]?.decision, "ALLOWED");
  assert.equal(log[0]?.provisional, false);
});

test("an undeclared permission is denied by default", () => {
  const enforcer = loaded();
  assert.throws(
    () => enforcer.enforce("github:issues:write", "permission"),
    (error: unknown) => {
      assert.ok(error instanceof ContractViolationError);
      assert.match(error.message, /not declared/);
      return true;
    },
  );
  assert.equal(enforcer.getAuditLog()[0]?.decision, "DENIED");
});

test("read is an alias for permission", () => {
  const enforcer = loaded();
  enforcer.enforce("github:issues:read", "read");
  assert.equal(enforcer.getAuditLog()[0]?.decision, "ALLOWED");
});

test("a declared side effect is allowed in full mode", () => {
  const enforcer = loaded({
    side_effects: [{ resource: "github", type: "comment" }],
  });
  enforcer.enforce("comment", "side_effect");
  assert.equal(enforcer.getAuditLog()[0]?.decision, "ALLOWED");
});

test("an undeclared side effect is denied", () => {
  const enforcer = loaded();
  assert.throws(
    () => enforcer.enforce("delete_repo", "side_effect"),
    ContractViolationError,
  );
});

test("an approval point is pending, then allowed after approve", () => {
  const enforcer = loaded({
    permissions: ["prod:deploy"],
    approvals: [{ action: "prod:deploy", required: true }],
  });
  assert.throws(
    () => enforcer.enforce("prod:deploy", "permission"),
    (error: unknown) => {
      assert.ok(error instanceof ApprovalPendingError);
      assert.match(error.message, /requires human approval/);
      return true;
    },
  );
  enforcer.approve("prod:deploy");
  enforcer.enforce("prod:deploy", "permission");
  const decisions = enforcer.getAuditLog().map((entry) => entry.decision);
  assert.deepEqual(decisions, ["PENDING", "ALLOWED", "ALLOWED"]);
});

test("draft mode default-denies an irreversible side effect", () => {
  const enforcer = loaded(
    {
      side_effects: [{ resource: "workspace", type: "file_delete" }],
    },
    "draft",
  );
  assert.throws(
    () => enforcer.enforce("file_delete", "side_effect"),
    (error: unknown) => {
      assert.ok(error instanceof ApprovalPendingError);
      assert.match(error.message, /requires human approval/);
      assert.equal(
        (error as ApprovalPendingError).approvalConfig["source"],
        "implicit-irreversible",
      );
      return true;
    },
  );
  assert.equal(enforcer.getAuditLog()[0]?.decision, "PENDING");
  assert.match(
    enforcer.getAuditLog()[0]?.reason ?? "",
    /irreversible in draft mode/,
  );
});

test("draft mode allows an irreversible action after approve", () => {
  const enforcer = loaded(
    {
      side_effects: [{ resource: "workspace", type: "file_delete" }],
    },
    "draft",
  );
  enforcer.approve("file_delete");
  enforcer.enforce("file_delete", "side_effect");
  assert.equal(enforcer.getAuditLog().at(-1)?.decision, "ALLOWED");
});

test("draft mode allows a reversible side effect without approval", () => {
  const enforcer = loaded(
    {
      side_effects: [{ resource: "cache", type: "cache_write" }],
    },
    "draft",
  );
  enforcer.enforce("cache_write", "side_effect");
  assert.equal(enforcer.getAuditLog()[0]?.decision, "ALLOWED");
});

test("full mode keeps T8 behavior: irreversible is allowed without approval", () => {
  const enforcer = loaded({
    side_effects: [{ resource: "workspace", type: "file_delete" }],
  });
  enforcer.enforce("file_delete", "side_effect");
  assert.equal(enforcer.getAuditLog()[0]?.decision, "ALLOWED");
});

test("draft audit entries carry provisional true through the trace", () => {
  const enforcer = loaded(
    { side_effects: [{ resource: "cache", type: "cache_write" }] },
    "draft",
  );
  enforcer.enforce("cache_write", "side_effect");
  const entry = enforcer.getAuditLog()[0];
  assert.ok(entry);
  assert.equal(entry.provisional, true);
  const trace = traceFromAudit(entry, {
    nodeId: null,
    contractHash: "a".repeat(64),
  });
  const jsonl = new TraceLog([trace]).toJsonl();
  assert.match(jsonl, /"provisional":true/);
});

test("a contract mutated after load is denied by the integrity gate", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract());
  const enforcer = ContractEnforcer.load(path);
  appendFileSync(path, "\n# tampered\n", "utf8");
  assert.throws(
    () => enforcer.enforce("github:issues:read", "permission"),
    (error: unknown) => {
      assert.ok(error instanceof ContractTamperError);
      assert.match(error.message, /tampered/);
      return true;
    },
  );
  const entry = enforcer.getAuditLog()[0];
  assert.equal(entry?.decision, "DENIED");
  assert.match(entry?.reason ?? "", /tampered/);
});

test("a v1.2 budget denies the second side effect", () => {
  const enforcer = loaded({
    version: 1.2,
    guardrails: {
      budgets: { side_effects_per_window: 1, window: "1h" },
    },
    side_effects: [{ resource: "github", type: "comment" }],
  });
  enforcer.enforce("comment", "side_effect");
  assert.throws(
    () => enforcer.enforce("comment", "side_effect"),
    (error: unknown) => {
      assert.ok(error instanceof GuardrailViolationError);
      assert.match(error.message, /Guardrail 'budgets' denied action/);
      return true;
    },
  );
  const decisions = enforcer.getAuditLog().map((entry) => entry.decision);
  assert.deepEqual(decisions, ["ALLOWED", "DENIED"]);
});

test("the audit log is returned as a defensive copy", () => {
  const enforcer = loaded();
  enforcer.enforce("github:issues:read", "permission");
  const copy = enforcer.getAuditLog();
  copy[0] = { ...copy[0]!, decision: "DENIED" };
  assert.equal(enforcer.getAuditLog()[0]?.decision, "ALLOWED");
});
