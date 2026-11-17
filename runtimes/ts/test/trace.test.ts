import assert from "node:assert/strict";
import test from "node:test";

import { TraceError } from "../src/errors.js";
import { TraceEntry, TraceLog, isIsoTimestamp } from "../src/trace.js";

const HASH = "a".repeat(64);

function fullEntry(): Record<string, unknown> {
  return {
    node_id: null,
    action_name: "github:issues:read",
    action_type: "permission",
    declared: true,
    result: "allowed",
    hash_of_contract: HASH,
    timestamp: "2026-01-01T00:00:00+00:00",
    reason: "declared",
    contract_field_reference: "permissions",
  };
}

test("a full-mode entry round-trips without provisional", () => {
  const jsonl = new TraceLog([TraceEntry.fromDict(fullEntry())]).toJsonl();
  assert.equal(
    jsonl,
    '{"action_name":"github:issues:read","action_type":"permission",' +
      '"contract_field_reference":"permissions","declared":true,' +
      `"hash_of_contract":"${HASH}","node_id":null,"reason":"declared",` +
      '"result":"allowed","timestamp":"2026-01-01T00:00:00+00:00"}\n',
  );
  assert.equal(TraceLog.fromJsonl(jsonl).toJsonl(), jsonl);
});

test("a draft-mode entry emits provisional true", () => {
  const entry = TraceEntry.fromDict({ ...fullEntry(), provisional: true });
  const jsonl = new TraceLog([entry]).toJsonl();
  assert.match(jsonl, /"provisional":true/);
  assert.equal(TraceLog.fromJsonl(jsonl).toJsonl(), jsonl);
});

test("an absent provisional field parses as a full-mode entry", () => {
  const entry = TraceEntry.fromDict(fullEntry());
  assert.equal(entry.provisional, undefined);
  assert.equal(entry.toDict()["provisional"], undefined);
});

test("provisional false is accepted but omitted from output", () => {
  const entry = TraceEntry.fromDict({ ...fullEntry(), provisional: false });
  assert.equal(entry.provisional, false);
  assert.equal("provisional" in entry.toDict(), false);
});

test("a null or string provisional value is rejected", () => {
  assert.throws(
    () => TraceEntry.fromDict({ ...fullEntry(), provisional: null }),
    /must be a boolean/,
  );
  assert.throws(
    () => TraceEntry.fromDict({ ...fullEntry(), provisional: "true" }),
    /must be a boolean/,
  );
});

test("an unknown field is rejected", () => {
  assert.throws(
    () => TraceEntry.fromDict({ ...fullEntry(), extra: 1 }),
    /unknown field/,
  );
});

test("a bad hash is rejected", () => {
  assert.throws(
    () =>
      TraceEntry.fromDict({
        ...fullEntry(),
        hash_of_contract: "z".repeat(64),
      }),
    /hexadecimal/,
  );
});

test("a bad timestamp is rejected", () => {
  assert.throws(
    () =>
      TraceEntry.fromDict({ ...fullEntry(), timestamp: "not-a-date" }),
    /ISO-8601/,
  );
});

test("an unknown result is rejected", () => {
  assert.throws(
    () => TraceEntry.fromDict({ ...fullEntry(), result: "maybe" }),
    /result/,
  );
});

test("a missing field is rejected", () => {
  const entry = fullEntry();
  delete entry["reason"];
  assert.throws(() => TraceEntry.fromDict(entry), /missing field/);
});

test("empty JSONL lines are rejected", () => {
  assert.throws(
    () => TraceLog.fromJsonl("\n"),
    /empty line/,
  );
});

test("an empty trace log is valid and serializes to the empty string", () => {
  assert.equal(new TraceLog().toJsonl(), "");
  assert.equal(TraceLog.fromJsonl("").entries.length, 0);
});

test("JSONL parsing reports the line number", () => {
  const good = JSON.stringify(fullEntry());
  assert.throws(
    () => TraceLog.fromJsonl(`${good}\nnot-json\n`),
    /line 2/,
  );
});

test("timestamps accept ISO-8601 offsets and Z", () => {
  assert.equal(isIsoTimestamp("2026-01-01T00:00:00+00:00"), true);
  assert.equal(isIsoTimestamp("2026-01-01T00:00:00Z"), true);
  assert.equal(isIsoTimestamp("2026-01-01"), true);
  assert.equal(isIsoTimestamp("2026-13-01T00:00:00Z"), false);
  assert.equal(isIsoTimestamp("2026-02-30T00:00:00Z"), false);
});

test("TraceError is the typed parse failure", () => {
  try {
    TraceEntry.fromDict({});
    assert.fail("expected TraceError");
  } catch (error) {
    assert.ok(error instanceof TraceError);
  }
});

test("trace JSONL preserves non-ASCII UTF-8 (ensure_ascii=False)", () => {
  const entry = TraceEntry.fromDict({
    ...fullEntry(),
    reason: "déclaré",
  });
  const jsonl = new TraceLog([entry]).toJsonl();
  assert.match(jsonl, /déclaré/);
  assert.equal(jsonl.includes("\\u00e9"), false);
});
