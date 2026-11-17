import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";

import {
  ContractFileNameError,
  ContractValidationError,
  ProvisionalContractError,
} from "../src/errors.js";
import { ContractEnforcer } from "../src/enforcer.js";
import { loadContractFile } from "../src/contract.js";
import { validateContractFile } from "../src/schema.js";
import { baseContract, tempDir, writeContract } from "./helpers.js";

test("v1.1 with provisional true validates", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract({ provisional: true }));
  const result = validateContractFile(path);
  assert.equal(result.valid, true);
  assert.deepEqual(result.errors, []);
});

test("v1.1 with provisional false and absent both validate", () => {
  const directory = tempDir();
  const explicit = writeContract(
    directory,
    baseContract({ provisional: false }),
    "explicit.yaml",
  );
  const absent = writeContract(directory, baseContract(), "absent.yaml");
  assert.equal(validateContractFile(explicit).valid, true);
  assert.equal(validateContractFile(absent).valid, true);
});

test("v1.2 with provisional true validates", () => {
  const directory = tempDir();
  const path = writeContract(
    directory,
    baseContract({ version: 1.2, provisional: true }),
  );
  assert.equal(validateContractFile(path).valid, true);
});

test("a non-boolean provisional value is invalid at /provisional", () => {
  const directory = tempDir();
  const path = writeContract(
    directory,
    baseContract({ provisional: "true" }),
  );
  const result = validateContractFile(path);
  assert.equal(result.valid, false);
  const mismatch = result.errors.find(
    (issue) =>
      issue.path === "/provisional" &&
      issue.message.includes("not of type 'boolean'"),
  );
  assert.ok(mismatch, JSON.stringify(result.errors));
});

test("v1 rejects provisional even as false", () => {
  const directory = tempDir();
  const v1 = {
    version: 1,
    workflow: "vector",
    inputs: [],
    outputs: [],
    permissions: [],
    side_effects: [],
    approval_points: [],
    recovery_strategy: "retry",
    replay_semantics: "idempotent",
    dependencies: [],
    state: "none",
    observability: [],
    provisional: false,
  };
  const path = writeContract(directory, v1);
  const result = validateContractFile(path);
  assert.equal(result.valid, false);
  const mismatch = result.errors.find(
    (issue) =>
      issue.path === "/provisional" &&
      issue.message.includes("1.1 or later"),
  );
  assert.ok(mismatch, JSON.stringify(result.errors));
});

test("a non-array permissions value is invalid at /permissions", () => {
  const directory = tempDir();
  const path = writeContract(
    directory,
    baseContract({ permissions: "*" }),
  );
  const result = validateContractFile(path);
  assert.equal(result.valid, false);
  const mismatch = result.errors.find(
    (issue) =>
      issue.path === "/permissions" &&
      issue.message.includes("not of type 'array'"),
  );
  assert.ok(mismatch, JSON.stringify(result.errors));
});

test("full mode refuses a provisional contract with a promotion message", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract({ provisional: true }));
  assert.throws(
    () => ContractEnforcer.load(path),
    (error: unknown) => {
      assert.ok(error instanceof ProvisionalContractError);
      assert.match(error.message, /provisional/);
      assert.match(error.message, /promotion/);
      return true;
    },
  );
});

test("draft mode loads a provisional contract", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract({ provisional: true }));
  const enforcer = ContractEnforcer.load(path, { mode: "draft" });
  assert.equal(enforcer.mode, "draft");
  assert.equal(enforcer.isProvisional, true);
});

test("draft mode refuses a non-provisional contract", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract());
  assert.throws(
    () => ContractEnforcer.load(path, { mode: "draft" }),
    (error: unknown) => {
      assert.ok(error instanceof ContractValidationError);
      assert.match(error.message, /not provisional/);
      return true;
    },
  );
});

test("a wildcard permission is refused on load", () => {
  const directory = tempDir();
  const path = writeContract(
    directory,
    baseContract({ permissions: ["*"] }),
  );
  assert.throws(
    () => ContractEnforcer.load(path),
    /Wildcard permission/,
  );
});

test(".yml is rejected; .yaml is canonical", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract(), "contract.yml");
  assert.throws(() => loadContractFile(path), ContractFileNameError);
});

test("the loaded contract is deeply frozen", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract());
  const loaded = loadContractFile(path);
  assert.equal(Object.isFrozen(loaded.contract), true);
  assert.equal(
    Object.isFrozen(loaded.contract["permissions"]),
    true,
  );
  assert.throws(() => {
    (loaded.contract["permissions"] as string[]).push("x");
  }, TypeError);
});

test("the bundled schemas are byte-identical to the Python reference", () => {
  const repositoryRoot = resolve("../..");
  for (const version of ["v1", "v1.1", "v1.2"]) {
    const reference = readFileSync(
      join(
        repositoryRoot,
        "src",
        "scyvera",
        "schemas",
        version,
        "contract.schema.json",
      ),
    );
    const copy = readFileSync(
      join("src", "schemas", version, "contract.schema.json"),
    );
    assert.deepEqual(copy, reference, `${version} schema drift`);
  }
});

test("integrity is pinned to the loaded bytes", () => {
  const directory = tempDir();
  const path = writeContract(directory, baseContract());
  const loaded = loadContractFile(path);
  assert.equal(loaded.integrityHash.length, 64);
  const enforcer = ContractEnforcer.load(path);
  writeFileSync(path, `${readFileSync(path, "utf8")}\n# changed\n`, "utf8");
  assert.throws(() => enforcer.verifyIntegrity(), /tampered/);
});
