import assert from "node:assert/strict";
import {
  copyFileSync,
  cpSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";

import { VectorSuiteError } from "../src/errors.js";
import { canonicalPretty } from "../src/json.js";
import {
  CATEGORIES,
  PINNED_SUITE_VERSION,
  loadSuite,
  runSuite,
} from "../src/vectors.js";
import { tempDir } from "./helpers.js";

const REPOSITORY_ROOT = resolve("../..");
const VECTORS = join(REPOSITORY_ROOT, "vectors");
const CM_0001 = join(
  VECTORS,
  "v1",
  "contract-model",
  "cm-0001-provisional-flag-valid.json",
);

function makeSuiteRoot(version: number): string {
  const root = tempDir("scyvera-suite-");
  writeFileSync(join(root, "suite-version"), `suite-version: ${version}\n`);
  const versionDir = join(root, `v${version}`);
  for (const category of CATEGORIES) {
    mkdirSync(join(versionDir, category), { recursive: true });
  }
  return root;
}

test("the shared suite is version 1 with 33 vectors", () => {
  const suite = loadSuite(VECTORS);
  assert.equal(suite.suiteVersion, 1);
  assert.equal(suite.vectors.length, 33);
  const counts = Object.fromEntries(
    CATEGORIES.map((category) => [
      category,
      suite.vectors.filter((vector) => vector.category === category).length,
    ]),
  );
  assert.deepEqual(counts, {
    "contract-model": 11,
    "gate-decision": 13,
    "trace-roundtrip": 9,
  });
});

test("the runtime pins the suite version it implements", () => {
  const suite = loadSuite(VECTORS);
  assert.equal(PINNED_SUITE_VERSION, suite.suiteVersion);
  assert.equal(
    readFileSync(join(VECTORS, "suite-version"), "utf8"),
    `suite-version: ${PINNED_SUITE_VERSION}\n`,
  );
});

test("all 33 vectors pass and produce the canonical result", () => {
  const run = runSuite(loadSuite(VECTORS));
  assert.equal(run.total, 33);
  assert.equal(run.passed, 33);
  assert.equal(run.failed, 0);
  assert.deepEqual(run.failures, []);
  assert.equal(
    run.toJson(),
    '{"failed":0,"failures":[],"passed":33,"suite_version":1,"total":33}\n',
  );
});

test("two runs over the same suite are byte-identical", () => {
  const suite = loadSuite(VECTORS);
  assert.equal(runSuite(suite).toJson(), runSuite(suite).toJson());
});

test("a category filter runs only that category", () => {
  const run = runSuite(loadSuite(VECTORS), { category: "gate-decision" });
  assert.equal(run.total, 13);
  assert.equal(run.failed, 0);
});

test("an unknown category fails closed", () => {
  assert.throws(
    () =>
      runSuite(loadSuite(VECTORS), {
        category: "promotion" as never,
      }),
    VectorSuiteError,
  );
});

test("a suite-version/envelope mismatch fails closed", () => {
  const root = makeSuiteRoot(2);
  copyFileSync(
    CM_0001,
    join(root, "v2", "contract-model", "cm-0001-provisional-flag-valid.json"),
  );
  assert.throws(
    () => loadSuite(root),
    /suite_version must equal suite-version 2/,
  );
});

test("a non-canonical vector file fails closed", () => {
  const root = makeSuiteRoot(1);
  const payload = {
    vector_version: 1,
    suite_version: 1,
    category: "contract-model",
    id: "cm-0001-compact",
    description: "A deliberately compact vector.",
    input: {
      operation: "validate",
      contract: {
        version: 1.1,
        system: { name: "vector-agent" },
      },
    },
    expect: { result: "valid" },
  };
  writeFileSync(
    join(root, "v1", "contract-model", "cm-0001-compact.json"),
    JSON.stringify(payload),
  );
  assert.throws(() => loadSuite(root), /canonical JSON form/);
});

test("a duplicate JSON key fails closed", () => {
  const root = makeSuiteRoot(1);
  writeFileSync(
    join(root, "v1", "contract-model", "cm-0001-duplicate.json"),
    '{"id":"cm-0001-duplicate","id":"cm-0001-duplicate"}\n',
  );
  assert.throws(() => loadSuite(root), /duplicate JSON key/);
});

test("an unknown category directory fails closed", () => {
  const root = makeSuiteRoot(1);
  mkdirSync(join(root, "v1", "promotion"));
  assert.throws(() => loadSuite(root), /unknown category 'promotion'/);
});

test("one failing vector does not abort the suite", () => {
  const copy = join(tempDir("scyvera-suite-copy-"), "vectors");
  cpSync(VECTORS, copy, { recursive: true });
  const file = join(
    copy,
    "v1",
    "contract-model",
    "cm-0001-provisional-flag-valid.json",
  );
  const payload = JSON.parse(readFileSync(file, "utf8")) as Record<
    string,
    unknown
  >;
  const input = payload["input"] as Record<string, unknown>;
  const contract = input["contract"] as Record<string, unknown>;
  contract["permissions"] = "*";
  writeFileSync(file, canonicalPretty(payload));

  const run = runSuite(loadSuite(copy));
  assert.equal(run.total, 33);
  assert.equal(run.failed, 1);
  assert.equal(run.passed, 32);
  assert.equal(
    run.failures[0]?.id,
    "cm-0001-provisional-flag-valid",
  );
  assert.match(run.failures[0]?.reason ?? "", /expected result/);
});
