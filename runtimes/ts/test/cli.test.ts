import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";

import { CATEGORIES } from "../src/vectors.js";
import { tempDir } from "./helpers.js";

const CLI = join("dist", "src", "cli.js");
const VECTORS = resolve("../../vectors");

interface CliResult {
  readonly status: number | null;
  readonly stdout: string;
  readonly stderr: string;
}

function run(args: string[]): CliResult {
  const result = spawnSync(process.execPath, [CLI, ...args], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  return {
    status: result.status,
    stdout: result.stdout,
    stderr: result.stderr,
  };
}

test("no arguments is a usage error (exit 2)", () => {
  const result = run([]);
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Usage:/);
});

test("vectors prints PASS and per-category counts (exit 0)", () => {
  const result = run(["vectors", "--root", VECTORS]);
  assert.equal(result.status, 0);
  assert.match(result.stdout, /PASS {2}33 vectors \(suite-version 1\)/);
  assert.match(result.stdout, /contract-model: 11 passed, 0 failed/);
  assert.match(result.stdout, /gate-decision: 13 passed, 0 failed/);
  assert.match(result.stdout, /trace-roundtrip: 9 passed, 0 failed/);
});

test("vectors --json emits the canonical RFC 0005 result", () => {
  const result = run(["vectors", "--root", VECTORS, "--json"]);
  assert.equal(result.status, 0);
  assert.equal(
    result.stdout,
    '{"failed":0,"failures":[],"passed":33,"suite_version":1,"total":33}\n',
  );
});

test("vectors output is deterministic across runs", () => {
  const first = run(["vectors", "--root", VECTORS, "--json"]);
  const second = run(["vectors", "--root", VECTORS, "--json"]);
  assert.equal(first.stdout, second.stdout);
});

test("a missing suite is a configuration error (exit 2)", () => {
  const result = run(["vectors", "--root", join(tempDir(), "missing")]);
  assert.equal(result.status, 2);
  assert.match(result.stderr, /not found/);
});

test("a different suite version fails the runtime pin (exit 2)", () => {
  const root = tempDir("scyvera-cli-suite-");
  writeFileSync(join(root, "suite-version"), "suite-version: 2\n");
  for (const category of CATEGORIES) {
    mkdirSync(join(root, "v2", category), { recursive: true });
  }
  const result = run(["vectors", "--root", root]);
  assert.equal(result.status, 2);
  assert.match(result.stderr, /pins 1/);
});

test("draft gate on an irreversible side effect is PENDING (exit 1)", () => {
  const result = run([
    "gate",
    "--contract",
    "demo/contract.yaml",
    "--mode",
    "draft",
    "--action",
    "file_delete",
    "--action-type",
    "side_effect",
  ]);
  assert.equal(result.status, 1);
  assert.match(result.stdout, /^PENDING {2}file_delete/);
  assert.match(result.stdout, /irreversible in draft mode/);
});

test("draft gate is ALLOWED after explicit approval (exit 0)", () => {
  const result = run([
    "gate",
    "--contract",
    "demo/contract.yaml",
    "--mode",
    "draft",
    "--action",
    "file_delete",
    "--action-type",
    "side_effect",
    "--approve",
    "--audit",
  ]);
  assert.equal(result.status, 0);
  assert.match(result.stdout, /^ALLOWED {2}file_delete/);
  assert.match(result.stdout, /\[ALLOWED\] file_delete \(side_effect\)/);
});

test("full mode refuses the provisional demo contract (exit 2)", () => {
  const result = run([
    "gate",
    "--contract",
    "demo/contract.yaml",
    "--action",
    "file_delete",
    "--action-type",
    "side_effect",
  ]);
  assert.equal(result.status, 2);
  assert.match(result.stderr, /provisional/);
});

test("an unknown command is a usage error (exit 2)", () => {
  const result = run(["promote"]);
  assert.equal(result.status, 2);
  assert.match(result.stderr, /unknown command/);
});
