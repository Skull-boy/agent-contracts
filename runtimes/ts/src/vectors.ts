/**
 * RFC 0005 §6 conformance-vector loader and native runner.
 *
 * The suite bytes are the contract; this runner never writes to `vectors/`,
 * never executes a target, and never delegates to Python. Configuration
 * problems fail closed with exit code 2 at the CLI boundary.
 */

import {
  appendFileSync,
  existsSync,
  lstatSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { stringify as stringifyYaml } from "yaml";

import { ContractEnforcer } from "./enforcer.js";
import {
  VectorSuiteError,
  canonicalErrorCode,
  type ValidationIssue,
} from "./errors.js";
import { canonicalCompact, canonicalPretty } from "./json.js";
import { validateContractFile } from "./schema.js";
import { TraceLog } from "./trace.js";

export const CATEGORIES = [
  "contract-model",
  "gate-decision",
  "trace-roundtrip",
] as const;

export type Category = (typeof CATEGORIES)[number];

export const SUITE_VERSION_FILENAME = "suite-version";

/**
 * The suite version this runtime implements. RFC 0005 §6.2/anchor A6 requires
 * each runtime to pin the integer in its own CI configuration and fail on
 * drift. The CLI enforces the same pin before running any vector.
 */
export const PINNED_SUITE_VERSION = 1;

const CATEGORY_PREFIX: Record<Category, string> = {
  "contract-model": "cm",
  "gate-decision": "gd",
  "trace-roundtrip": "tr",
};

const SUITE_VERSION_PATTERN = /^suite-version: (0|[1-9][0-9]*)\n$/;
const VECTOR_ID_PATTERN =
  /^(cm|gd|tr)-[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*$/;

const ENVELOPE_REQUIRED = new Set([
  "vector_version",
  "suite_version",
  "category",
  "id",
  "description",
  "input",
  "expect",
]);
const ENVELOPE_OPTIONAL = new Set(["notes"]);

const CANONICAL_CODES = new Set([
  "ContractViolationError",
  "ApprovalPendingError",
  "ProvisionalContractError",
  "ContractValidationError",
  "TraceError",
  "GuardrailViolationError",
]);

export interface Vector {
  readonly suiteVersion: number;
  readonly category: Category;
  readonly id: string;
  readonly description: string;
  readonly input: Readonly<Record<string, unknown>>;
  readonly expect: Readonly<Record<string, unknown>>;
  readonly notes: string | undefined;
  readonly path: string;
}

export interface VectorSuite {
  readonly suiteVersion: number;
  readonly root: string;
  readonly vectors: readonly Vector[];
}

export interface VectorFailure {
  readonly id: string;
  readonly reason: string;
}

export interface VectorRunResult {
  readonly suite_version: number;
  readonly total: number;
  readonly passed: number;
  readonly failed: number;
  readonly failures: readonly { readonly id: string; readonly reason: string }[];
}

export class VectorRun {
  readonly suiteVersion: number;
  readonly total: number;
  readonly passed: number;
  readonly failed: number;
  readonly failures: readonly VectorFailure[];

  constructor(
    suiteVersion: number,
    total: number,
    passed: number,
    failed: number,
    failures: readonly VectorFailure[],
  ) {
    this.suiteVersion = suiteVersion;
    this.total = total;
    this.passed = passed;
    this.failed = failed;
    this.failures = Object.freeze([...failures]);
    Object.freeze(this);
  }

  toDict(): VectorRunResult {
    return {
      suite_version: this.suiteVersion,
      total: this.total,
      passed: this.passed,
      failed: this.failed,
      failures: this.failures.map((failure) => ({
        id: failure.id,
        reason: failure.reason,
      })),
    };
  }

  toJson(): string {
    return `${canonicalCompact(this.toDict())}\n`;
  }
}

// ---------------------------------------------------------------------------
// Strict JSON (duplicate keys fail closed)
// ---------------------------------------------------------------------------

class JsonScanError extends Error {}

function parseJsonStrict(text: string): unknown {
  let index = 0;

  const fail = (message: string): never => {
    throw new JsonScanError(message);
  };

  const skipWhitespace = (): void => {
    while (index < text.length) {
      const character = text[index];
      if (
        character === " " ||
        character === "\t" ||
        character === "\n" ||
        character === "\r"
      ) {
        index += 1;
      } else {
        break;
      }
    }
  };

  const parseString = (): string => {
    if (text[index] !== '"') {
      fail(`expected a string at position ${index}`);
    }
    index += 1;
    let output = "";
    while (index < text.length) {
      const character = text[index];
      index += 1;
      if (character === '"') return output;
      if (character === "\\") {
        const escape = text[index];
        index += 1;
        switch (escape) {
          case '"':
            output += '"';
            break;
          case "\\":
            output += "\\";
            break;
          case "/":
            output += "/";
            break;
          case "b":
            output += "\b";
            break;
          case "f":
            output += "\f";
            break;
          case "n":
            output += "\n";
            break;
          case "r":
            output += "\r";
            break;
          case "t":
            output += "\t";
            break;
          case "u": {
            const hex = text.slice(index, index + 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
              fail("invalid unicode escape in string");
            }
            output += String.fromCharCode(Number.parseInt(hex, 16));
            index += 4;
            break;
          }
          default:
            fail("invalid escape sequence in string");
        }
      } else if ((character ?? "").charCodeAt(0) < 0x20) {
        fail("unescaped control character in string");
      } else {
        output += character;
      }
    }
    return fail("unterminated string");
  };

  const parseNumber = (): number => {
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(
      text.slice(index),
    );
    if (match === null) {
      return fail(`invalid number at position ${index}`);
    }
    index += match[0].length;
    const value = Number(match[0]);
    if (!Number.isFinite(value)) {
      return fail("number is not finite");
    }
    return value;
  };

  const parseObject = (): Record<string, unknown> => {
    index += 1;
    skipWhitespace();
    if (text[index] === "}") {
      index += 1;
      return {};
    }
    const result: Record<string, unknown> = {};
    const seen = new Set<string>();
    while (true) {
      skipWhitespace();
      const key = parseString();
      if (seen.has(key)) {
        fail(`duplicate JSON key '${key}'`);
      }
      seen.add(key);
      skipWhitespace();
      if (text[index] !== ":") {
        fail(`expected ':' after object key at position ${index}`);
      }
      index += 1;
      Object.defineProperty(result, key, {
        value: parseValue(),
        enumerable: true,
        writable: true,
        configurable: true,
      });
      skipWhitespace();
      const next = text[index];
      if (next === ",") {
        index += 1;
        continue;
      }
      if (next === "}") {
        index += 1;
        return result;
      }
      fail(`expected ',' or '}' at position ${index}`);
    }
  };

  const parseArray = (): unknown[] => {
    index += 1;
    skipWhitespace();
    if (text[index] === "]") {
      index += 1;
      return [];
    }
    const result: unknown[] = [];
    while (true) {
      result.push(parseValue());
      skipWhitespace();
      const next = text[index];
      if (next === ",") {
        index += 1;
        continue;
      }
      if (next === "]") {
        index += 1;
        return result;
      }
      fail(`expected ',' or ']' at position ${index}`);
    }
  };

  const parseValue = (): unknown => {
    skipWhitespace();
    const character = text[index];
    if (character === undefined) {
      return fail("unexpected end of JSON input");
    }
    if (character === '"') return parseString();
    if (character === "{") return parseObject();
    if (character === "[") return parseArray();
    if (text.startsWith("true", index)) {
      index += 4;
      return true;
    }
    if (text.startsWith("false", index)) {
      index += 5;
      return false;
    }
    if (text.startsWith("null", index)) {
      index += 4;
      return null;
    }
    if (character === "-" || (character >= "0" && character <= "9")) {
      return parseNumber();
    }
    return fail(`unexpected character '${character}' at position ${index}`);
  };

  const value = parseValue();
  skipWhitespace();
  if (index !== text.length) {
    fail(`trailing data at position ${index}`);
  }
  return value;
}

// ---------------------------------------------------------------------------
// Loader helpers
// ---------------------------------------------------------------------------

function fail(message: string): never {
  throw new VectorSuiteError(message);
}

function readText(path: string, what: string): string {
  let bytes: Buffer;
  try {
    bytes = readFileSync(path);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return fail(`cannot read ${what} '${path}': ${detail}`);
  }
  try {
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
      bytes,
    );
  } catch {
    return fail(`${what} '${path}' is not valid UTF-8`);
  }
}

function rejectSymlink(path: string, what: string): void {
  let stats;
  try {
    stats = lstatSync(path);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return fail(`cannot inspect ${what} '${path}': ${detail}`);
  }
  if (stats.isSymbolicLink()) {
    fail(`${what} '${path}' must not be a symlink (RFC 0005 section 6.1)`);
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) !== null
  );
}

function requireMapping(
  value: unknown,
  where: string,
): Record<string, unknown> {
  if (!isPlainObject(value)) {
    fail(
      `${where} must be a JSON object, got ${
        value === null ? "null" : Array.isArray(value) ? "array" : typeof value
      }`,
    );
  }
  return value;
}

function requireString(
  value: unknown,
  where: string,
  allowEmpty = false,
): string {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    fail(`${where} must be a non-empty string`);
  }
  return value;
}

function requireInteger(value: unknown, where: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    fail(`${where} must be an integer, got ${typeof value}`);
  }
  return value;
}

function requireBoolean(value: unknown, where: string): boolean {
  if (typeof value !== "boolean") {
    fail(`${where} must be a boolean, got ${typeof value}`);
  }
  return value;
}

function requireErrorCode(value: unknown, where: string): string {
  const code = requireString(value, where);
  if (!CANONICAL_CODES.has(code)) {
    fail(
      `${where} must be one of ${[...CANONICAL_CODES].sort().join(", ")}, ` +
        `got '${code}'`,
    );
  }
  return code;
}

function rejectUnknown(
  data: Record<string, unknown>,
  allowed: ReadonlySet<string>,
  where: string,
): void {
  const unknown = Object.keys(data)
    .filter((key) => !allowed.has(key))
    .sort();
  if (unknown.length > 0) {
    fail(`${where} has unknown key(s): ${unknown.join(", ")}`);
  }
}

function validateContractModelInput(
  data: Record<string, unknown>,
  where: string,
): void {
  rejectUnknown(
    data,
    new Set(["operation", "mode", "filename", "contract"]),
    where,
  );
  const operation = data["operation"];
  if (operation !== "validate" && operation !== "load") {
    fail(`${where}.operation must be 'validate' or 'load'`);
  }
  if (operation === "load") {
    if (!("mode" in data)) {
      fail(`${where}.mode is required for operation 'load'`);
    }
    if (data["mode"] !== "full" && data["mode"] !== "draft") {
      fail(`${where}.mode must be 'full' or 'draft'`);
    }
  } else if ("mode" in data) {
    fail(`${where}.mode must be absent for operation 'validate'`);
  }
  const filename = data["filename"] ?? "contract.yaml";
  if (typeof filename !== "string" || !filename.endsWith(".yaml")) {
    fail(`${where}.filename must be a string ending in '.yaml'`);
  }
  requireMapping(data["contract"], `${where}.contract`);
}

function validateGateInput(
  data: Record<string, unknown>,
  where: string,
): void {
  rejectUnknown(
    data,
    new Set(["mode", "contract", "scenario", "tamper_before"]),
    where,
  );
  if (data["mode"] !== "full" && data["mode"] !== "draft") {
    fail(`${where}.mode must be 'full' or 'draft'`);
  }
  requireMapping(data["contract"], `${where}.contract`);
  const scenario = data["scenario"];
  if (!Array.isArray(scenario) || scenario.length === 0) {
    fail(`${where}.scenario must be a non-empty array`);
  }
  scenario.forEach((step, index) => {
    const stepWhere = `${where}.scenario[${index}]`;
    const stepMap = requireMapping(step, stepWhere);
    rejectUnknown(stepMap, new Set(["action", "action_type", "approve"]), stepWhere);
    requireString(stepMap["action"], `${stepWhere}.action`);
    if (
      stepMap["action_type"] !== "permission" &&
      stepMap["action_type"] !== "side_effect" &&
      stepMap["action_type"] !== "read"
    ) {
      fail(
        `${stepWhere}.action_type must be 'permission', 'side_effect', or ` +
          `'read'`,
      );
    }
    if ("approve" in stepMap) {
      requireBoolean(stepMap["approve"], `${stepWhere}.approve`);
    }
  });
  if ("tamper_before" in data) {
    requireBoolean(data["tamper_before"], `${where}.tamper_before`);
  }
}

function validateTraceInput(
  data: Record<string, unknown>,
  where: string,
): void {
  rejectUnknown(data, new Set(["jsonl", "operation"]), where);
  if (data["operation"] !== "roundtrip" && data["operation"] !== "parse") {
    fail(`${where}.operation must be 'roundtrip' or 'parse'`);
  }
  requireString(data["jsonl"], `${where}.jsonl`, true);
}

const INPUT_VALIDATORS: Record<
  Category,
  (data: Record<string, unknown>, where: string) => void
> = {
  "contract-model": validateContractModelInput,
  "gate-decision": validateGateInput,
  "trace-roundtrip": validateTraceInput,
};

function validateContractModelExpect(
  data: Record<string, unknown>,
  where: string,
): void {
  const result = data["result"];
  if (
    result !== "valid" &&
    result !== "invalid" &&
    result !== "loaded" &&
    result !== "rejected"
  ) {
    fail(`${where}.result is not a valid contract-model result`);
  }
  const errors = data["errors"] ?? [];
  if (!Array.isArray(errors)) {
    fail(`${where}.errors must be an array`);
  }
  if (result === "invalid") {
    if (!("errors" in data)) {
      fail(`${where}.errors is required for result 'invalid'`);
    }
  } else if (errors.length > 0) {
    fail(`${where}.errors must be [] unless result is 'invalid'`);
  }
  errors.forEach((item, index) => {
    const itemWhere = `${where}.errors[${index}]`;
    const itemMap = requireMapping(item, itemWhere);
    rejectUnknown(itemMap, new Set(["path", "message_contains"]), itemWhere);
    if (!("path" in itemMap)) {
      fail(`${itemWhere}.path is required (use null for any path)`);
    }
    if (itemMap["path"] !== null && typeof itemMap["path"] !== "string") {
      fail(`${itemWhere}.path must be a string or null`);
    }
    requireString(
      itemMap["message_contains"],
      `${itemWhere}.message_contains`,
    );
  });
  if (result === "rejected") {
    requireErrorCode(data["error_code"], `${where}.error_code`);
    requireString(data["message_contains"], `${where}.message_contains`);
  } else if ("error_code" in data || "message_contains" in data) {
    fail(
      `${where}.error_code/message_contains are only valid for 'rejected'`,
    );
  }
}

function validateGateExpect(
  data: Record<string, unknown>,
  where: string,
): void {
  rejectUnknown(data, new Set(["decisions", "errors"]), where);
  const decisions = data["decisions"];
  if (!Array.isArray(decisions) || decisions.length === 0) {
    fail(`${where}.decisions must be a non-empty array`);
  }
  decisions.forEach((decision, index) => {
    if (
      decision !== "ALLOWED" &&
      decision !== "DENIED" &&
      decision !== "PENDING"
    ) {
      fail(
        `${where}.decisions[${index}] must be ALLOWED, DENIED, or PENDING`,
      );
    }
  });
  const errors = data["errors"] ?? [];
  if (!Array.isArray(errors)) {
    fail(`${where}.errors must be an array`);
  }
  errors.forEach((item, index) => {
    const itemWhere = `${where}.errors[${index}]`;
    const itemMap = requireMapping(item, itemWhere);
    rejectUnknown(
      itemMap,
      new Set(["index", "error_code", "message_contains"]),
      itemWhere,
    );
    const errorIndex = requireInteger(
      itemMap["index"],
      `${itemWhere}.index`,
    );
    if (errorIndex < 0) {
      fail(`${itemWhere}.index must be non-negative`);
    }
    requireErrorCode(itemMap["error_code"], `${itemWhere}.error_code`);
    requireString(
      itemMap["message_contains"],
      `${itemWhere}.message_contains`,
    );
  });
}

function validateTraceExpect(
  data: Record<string, unknown>,
  where: string,
): void {
  rejectUnknown(
    data,
    new Set(["result", "canonical_jsonl", "error_code", "message_contains"]),
    where,
  );
  const result = data["result"];
  if (result !== "roundtrip" && result !== "parsed" && result !== "rejected") {
    fail(`${where}.result is not a valid trace-roundtrip result`);
  }
  if (result === "roundtrip") {
    requireString(
      data["canonical_jsonl"],
      `${where}.canonical_jsonl`,
      true,
    );
  } else if ("canonical_jsonl" in data) {
    fail(`${where}.canonical_jsonl is only valid for 'roundtrip'`);
  }
  if (result === "rejected") {
    requireErrorCode(data["error_code"], `${where}.error_code`);
    requireString(data["message_contains"], `${where}.message_contains`);
  } else if ("error_code" in data || "message_contains" in data) {
    fail(
      `${where}.error_code/message_contains are only valid for 'rejected'`,
    );
  }
}

const EXPECT_VALIDATORS: Record<
  Category,
  (data: Record<string, unknown>, where: string) => void
> = {
  "contract-model": validateContractModelExpect,
  "gate-decision": validateGateExpect,
  "trace-roundtrip": validateTraceExpect,
};

function buildVector(
  payload: Record<string, unknown>,
  category: Category,
  suiteVersion: number,
  path: string,
): Vector {
  const where = `vector '${path}'`;
  rejectUnknown(
    payload,
    new Set([...ENVELOPE_REQUIRED, ...ENVELOPE_OPTIONAL]),
    where,
  );
  const missing = [...ENVELOPE_REQUIRED]
    .filter((key) => !(key in payload))
    .sort();
  if (missing.length > 0) {
    fail(`${where} is missing key(s): ${missing.join(", ")}`);
  }

  if (requireInteger(payload["vector_version"], `${where}.vector_version`) !== 1) {
    fail(`${where}.vector_version must be 1`);
  }
  if (
    requireInteger(payload["suite_version"], `${where}.suite_version`) !==
    suiteVersion
  ) {
    fail(`${where}.suite_version must equal suite-version ${suiteVersion}`);
  }
  if (payload["category"] !== category) {
    fail(`${where}.category must equal the directory name '${category}'`);
  }

  const vectorId = requireString(payload["id"], `${where}.id`);
  if (!VECTOR_ID_PATTERN.test(vectorId)) {
    fail(`${where}.id is not a valid vector ID`);
  }
  if (!vectorId.startsWith(`${CATEGORY_PREFIX[category]}-`)) {
    fail(
      `${where}.id must start with '${CATEGORY_PREFIX[category]}-' for ` +
        `category '${category}'`,
    );
  }

  const description = requireString(
    payload["description"],
    `${where}.description`,
  );
  if (description.includes("\n")) {
    fail(`${where}.description must be one line with no newline`);
  }

  let notes: string | undefined;
  if (payload["notes"] !== undefined && payload["notes"] !== null) {
    notes = requireString(payload["notes"], `${where}.notes`);
  }

  const input = requireMapping(payload["input"], `${where}.input`);
  const expect = requireMapping(payload["expect"], `${where}.expect`);
  INPUT_VALIDATORS[category](input, `${where}.input`);
  EXPECT_VALIDATORS[category](expect, `${where}.expect`);

  if (category === "gate-decision") {
    const scenario = input["scenario"];
    const decisions = expect["decisions"];
    if (
      Array.isArray(scenario) &&
      Array.isArray(decisions) &&
      decisions.length !== scenario.length
    ) {
      fail(
        `${where}.expect.decisions must have one entry per scenario step ` +
          `(${scenario.length}), got ${decisions.length}`,
      );
    }
  }

  return {
    suiteVersion,
    category,
    id: vectorId,
    description,
    input,
    expect,
    notes,
    path,
  };
}

function categoryFiles(categoryDir: string): string[] {
  let entries;
  try {
    entries = readdirSync(categoryDir, { withFileTypes: true });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return fail(`cannot read category directory '${categoryDir}': ${detail}`);
  }
  const files: string[] = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const fullPath = join(categoryDir, entry.name);
    rejectSymlink(fullPath, "vector entry");
    if (entry.isDirectory()) {
      fail(
        `vector file '${fullPath}' must not be nested deeper than the ` +
          `category directory`,
      );
    }
    if (!entry.name.endsWith(".json")) {
      fail(
        `unexpected file '${fullPath}' in a category directory; vectors must ` +
          `be named '<id>.json'`,
      );
    }
    files.push(fullPath);
  }
  return files;
}

export function loadSuite(root = "vectors"): VectorSuite {
  const rootPath = root;
  if (!existsSync(rootPath)) {
    fail(`vector suite not found at '${rootPath}'`);
  }
  if (!statSync(rootPath).isDirectory()) {
    fail(`vector suite root '${rootPath}' is not a directory`);
  }
  rejectSymlink(rootPath, "vector suite root");

  const versionPath = join(rootPath, SUITE_VERSION_FILENAME);
  if (!existsSync(versionPath)) {
    fail(`vector suite is missing '${versionPath}'`);
  }
  const versionText = readText(versionPath, "suite-version");
  const versionMatch = SUITE_VERSION_PATTERN.exec(versionText);
  if (versionMatch === null) {
    fail(
      `'${versionPath}' must be exactly 'suite-version: <integer>\\n' with no ` +
        `BOM, comments, or extra keys`,
    );
  }
  const suiteVersion = Number.parseInt(versionMatch[1] ?? "", 10);
  if (suiteVersion === 0) {
    return { suiteVersion: 0, root: rootPath, vectors: [] };
  }

  const versionDir = join(rootPath, `v${suiteVersion}`);
  if (!existsSync(versionDir) || !statSync(versionDir).isDirectory()) {
    fail(`suite-version is ${suiteVersion} but '${versionDir}' is missing`);
  }
  rejectSymlink(versionDir, "version directory");

  const knownCategories = new Set<string>(CATEGORIES);
  let versionEntries;
  try {
    versionEntries = readdirSync(versionDir, { withFileTypes: true });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return fail(`cannot read version directory '${versionDir}': ${detail}`);
  }
  for (const entry of versionEntries) {
    if (!knownCategories.has(entry.name)) {
      fail(
        `unknown category '${entry.name}' in '${versionDir}'; allowed ` +
          `categories are ${CATEGORIES.join(", ")}`,
      );
    }
  }

  const vectors: Vector[] = [];
  const seenIds = new Map<string, string>();
  for (const category of CATEGORIES) {
    const categoryDir = join(versionDir, category);
    if (!existsSync(categoryDir) || !statSync(categoryDir).isDirectory()) {
      fail(`missing category directory '${categoryDir}'`);
    }
    rejectSymlink(categoryDir, "category directory");
    for (const vectorPath of categoryFiles(categoryDir)) {
      const text = readText(vectorPath, "vector");
      let payload: unknown;
      try {
        payload = parseJsonStrict(text);
      } catch (error) {
        if (error instanceof JsonScanError) {
          fail(`vector '${vectorPath}': ${error.message}`);
        }
        throw error;
      }
      const canonical = canonicalPretty(payload);
      if (text !== canonical) {
        fail(
          `vector '${vectorPath}' is not in canonical JSON form (sorted ` +
            `keys, two-space indent, one trailing newline)`,
        );
      }
      const payloadMap = requireMapping(payload, `vector '${vectorPath}'`);
      const vector = buildVector(
        payloadMap,
        category,
        suiteVersion,
        vectorPath,
      );
      if (basename(vectorPath, ".json") !== vector.id) {
        fail(`vector file '${vectorPath}' must be named '${vector.id}.json'`);
      }
      const duplicate = seenIds.get(vector.id);
      if (duplicate !== undefined) {
        fail(
          `duplicate vector ID '${vector.id}' in '${vectorPath}' and ` +
            `'${duplicate}'`,
        );
      }
      seenIds.set(vector.id, vectorPath);
      vectors.push(vector);
    }
  }

  vectors.sort((left, right) =>
    left.id < right.id ? -1 : left.id > right.id ? 1 : 0,
  );
  return { suiteVersion, root: rootPath, vectors };
}

// ---------------------------------------------------------------------------
// Execution
// ---------------------------------------------------------------------------

function matchContractErrors(
  expected: readonly Readonly<Record<string, unknown>>[],
  actual: readonly ValidationIssue[],
  where: string,
): string | null {
  const remaining = [...actual];
  for (const item of expected) {
    const path = item["path"];
    const needle = item["message_contains"];
    if (typeof needle !== "string") {
      return `${where}: internal vector shape error`;
    }
    const index = remaining.findIndex((candidate) => {
      if (path !== null && candidate.path !== path) return false;
      return candidate.message.includes(needle);
    });
    if (index < 0) {
      return (
        `${where}: no error matched path=${JSON.stringify(path)} ` +
        `message_contains=${JSON.stringify(needle)}`
      );
    }
    remaining.splice(index, 1);
  }
  if (expected.length === 0 && actual.length > 0) {
    return `${where}: expected no errors, got ${actual.length}`;
  }
  return null;
}

function createTempDir(): string {
  // Resolve the temp root first: macOS exposes /var as a symlink to
  // /private/var, which would otherwise look like a T14 escape to the loader.
  return mkdtempSync(join(realpathSync(tmpdir()), "scyvera-vector-"));
}

function writeContract(
  contract: Record<string, unknown>,
  directory: string,
  filename: string,
): string {
  const path = join(directory, filename);
  writeFileSync(
    path,
    stringifyYaml(contract, { sortMapEntries: true, lineWidth: 0 }),
    "utf8",
  );
  return path;
}

function runContractModel(vector: Vector): string | null {
  const input = vector.input;
  const expect = vector.expect;
  const operation = input["operation"];
  const directory = createTempDir();
  try {
    const filename =
      typeof input["filename"] === "string" ? input["filename"] : "contract.yaml";
    const contractPath = writeContract(
      requireMapping(input["contract"], "input.contract"),
      directory,
      filename,
    );

    if (operation === "validate") {
      const result = validateContractFile(contractPath);
      const actualResult = result.valid ? "valid" : "invalid";
      if (actualResult !== expect["result"]) {
        const first = result.errors[0];
        const detail = first
          ? first.path
            ? `${first.path}: ${first.message}`
            : first.message
          : "no validation errors";
        return (
          `expected result ${JSON.stringify(expect["result"])}, got ` +
          `${JSON.stringify(actualResult)} (${detail})`
        );
      }
      if (expect["result"] === "invalid") {
        const expectedErrors = expect["errors"];
        if (!Array.isArray(expectedErrors)) {
          return "invalid vector: errors is not an array";
        }
        return matchContractErrors(
          expectedErrors as readonly Readonly<Record<string, unknown>>[],
          result.errors,
          "validation errors",
        );
      }
      return null;
    }

    const mode = input["mode"];
    let actualResult: "loaded" | "rejected";
    let code = "";
    let message = "";
    try {
      ContractEnforcer.load(contractPath, {
        mode: mode === "draft" ? "draft" : "full",
      });
      actualResult = "loaded";
    } catch (error) {
      actualResult = "rejected";
      code = canonicalErrorCode(error);
      message = error instanceof Error ? error.message : String(error);
    }

    if (actualResult !== expect["result"]) {
      return (
        `expected result ${JSON.stringify(expect["result"])}, got ` +
        `${JSON.stringify(actualResult)}` +
        (code ? ` (${code}: ${message})` : "")
      );
    }
    if (expect["result"] === "rejected") {
      if (code !== expect["error_code"]) {
        return (
          `expected error_code ${JSON.stringify(expect["error_code"])}, got ` +
          `${JSON.stringify(code)}`
        );
      }
      const needle = expect["message_contains"];
      if (typeof needle !== "string" || !message.includes(needle)) {
        return (
          `expected message_contains ${JSON.stringify(needle)}, got ` +
          `${JSON.stringify(message)}`
        );
      }
    }
    return null;
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

function runGate(vector: Vector): string | null {
  const input = vector.input;
  const expect = vector.expect;
  const scenario = input["scenario"];
  const decisions = expect["decisions"];
  if (!Array.isArray(scenario) || !Array.isArray(decisions)) {
    return "invalid vector: scenario/decisions are not arrays";
  }
  if (decisions.length !== scenario.length) {
    return `expected ${decisions.length} decisions for ${scenario.length} steps`;
  }

  const directory = createTempDir();
  try {
    const contractPath = writeContract(
      requireMapping(input["contract"], "input.contract"),
      directory,
      "contract.yaml",
    );

    let enforcer: ContractEnforcer;
    try {
      enforcer = ContractEnforcer.load(contractPath, {
        mode: input["mode"] === "draft" ? "draft" : "full",
      });
    } catch (error) {
      const code = canonicalErrorCode(error);
      const message = error instanceof Error ? error.message : String(error);
      return `contract failed to load: ${code}: ${message}`;
    }

    if (input["tamper_before"] === true) {
      appendFileSync(contractPath, "\n# tampered\n", "utf8");
    }

    const actualDecisions: string[] = [];
    const actualErrors: { index: number; code: string; message: string }[] = [];
    scenario.forEach((rawStep, index) => {
      const step = requireMapping(rawStep, `scenario[${index}]`);
      const action = String(step["action"]);
      const actionType = step["action_type"];
      if (step["approve"] === true) {
        enforcer.approve(action);
      }
      const outcome = enforcer.decide(
        action,
        actionType === "side_effect"
          ? "side_effect"
          : actionType === "read"
            ? "read"
            : "permission",
      );
      actualDecisions.push(outcome.decision);
      if (outcome.error !== undefined) {
        actualErrors.push({
          index,
          code: canonicalErrorCode(outcome.error),
          message:
            outcome.error instanceof Error
              ? outcome.error.message
              : String(outcome.error),
        });
      }
    });

    if (
      actualDecisions.length !== decisions.length ||
      actualDecisions.some((decision, index) => decision !== decisions[index])
    ) {
      return (
        `expected decisions ${JSON.stringify(decisions)}, got ` +
        `${JSON.stringify(actualDecisions)}`
      );
    }

    const expectedErrors = Array.isArray(expect["errors"])
      ? expect["errors"]
      : [];
    if (actualErrors.length !== expectedErrors.length) {
      return (
        `expected ${expectedErrors.length} error(s), got ` +
        `${actualErrors.length}: ` +
        `${JSON.stringify(actualErrors.map((item) => [item.index, item.code]))}`
      );
    }
    const byIndex = new Map<number, Record<string, unknown>>();
    for (const rawExpected of expectedErrors) {
      const expectedError = requireMapping(rawExpected, "expect.errors[]");
      byIndex.set(Number(expectedError["index"]), expectedError);
    }
    for (const actual of actualErrors) {
      const expected = byIndex.get(actual.index);
      if (expected === undefined) {
        return `unexpected error at step ${actual.index}: ${actual.code}: ${actual.message}`;
      }
      if (expected["error_code"] !== actual.code) {
        return (
          `step ${actual.index}: expected error_code ` +
          `${JSON.stringify(expected["error_code"])}, got ` +
          `${JSON.stringify(actual.code)}`
        );
      }
      const needle = expected["message_contains"];
      if (typeof needle !== "string" || !actual.message.includes(needle)) {
        return (
          `step ${actual.index}: expected message_contains ` +
          `${JSON.stringify(needle)}, got ${JSON.stringify(actual.message)}`
        );
      }
    }
    const actualIndexes = new Set(actualErrors.map((item) => item.index));
    const missing = [...byIndex.keys()]
      .filter((index) => !actualIndexes.has(index))
      .sort((a, b) => a - b);
    if (missing.length > 0) {
      return `expected error(s) at step(s) ${JSON.stringify(missing)} but none occurred`;
    }
    return null;
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

function runTrace(vector: Vector): string | null {
  const input = vector.input;
  const expect = vector.expect;
  const operation = input["operation"];
  const jsonl = input["jsonl"];
  if (typeof jsonl !== "string") {
    return "input.jsonl is not a string";
  }

  if (operation === "roundtrip") {
    let canonical: string;
    try {
      canonical = TraceLog.fromJsonl(jsonl).toJsonl();
    } catch (error) {
      return `roundtrip raised ${canonicalErrorCode(error)}: ${errorMessage(error)}`;
    }
    if (expect["result"] !== "roundtrip") {
      return `expected result ${JSON.stringify(expect["result"])}, got 'roundtrip'`;
    }
    if (canonical !== expect["canonical_jsonl"]) {
      return (
        `canonical_jsonl mismatch: expected ` +
        `${JSON.stringify(expect["canonical_jsonl"])}, got ` +
        `${JSON.stringify(canonical)}`
      );
    }
    return null;
  }

  let actualResult: "parsed" | "rejected";
  let code = "";
  let message = "";
  try {
    TraceLog.fromJsonl(jsonl);
    actualResult = "parsed";
  } catch (error) {
    actualResult = "rejected";
    code = canonicalErrorCode(error);
    message = errorMessage(error);
  }

  if (actualResult !== expect["result"]) {
    return `expected result ${JSON.stringify(expect["result"])}, got ${JSON.stringify(actualResult)}`;
  }
  if (expect["result"] === "rejected") {
    if (code !== expect["error_code"]) {
      return `expected error_code ${JSON.stringify(expect["error_code"])}, got ${JSON.stringify(code)}`;
    }
    const needle = expect["message_contains"];
    if (typeof needle !== "string" || !message.includes(needle)) {
      return `expected message_contains ${JSON.stringify(needle)}, got ${JSON.stringify(message)}`;
    }
  }
  return null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const EXECUTORS: Record<Category, (vector: Vector) => string | null> = {
  "contract-model": runContractModel,
  "gate-decision": runGate,
  "trace-roundtrip": runTrace,
};

export function runSuite(
  suite: VectorSuite,
  options: { category?: Category } = {},
): VectorRun {
  if (
    options.category !== undefined &&
    !CATEGORIES.includes(options.category)
  ) {
    fail(
      `unknown category '${String(options.category)}'; allowed categories ` +
        `are ${CATEGORIES.join(", ")}`,
    );
  }

  const selected = suite.vectors.filter(
    (vector) =>
      options.category === undefined || vector.category === options.category,
  );
  const failures: VectorFailure[] = [];
  for (const vector of selected) {
    let reason: string | null;
    try {
      reason = EXECUTORS[vector.category](vector);
    } catch (error) {
      const name = error instanceof Error ? error.name : "Error";
      reason = `runner error: ${name}`;
    }
    if (reason !== null) {
      failures.push({ id: vector.id, reason });
    }
  }

  failures.sort((left, right) =>
    left.id < right.id ? -1 : left.id > right.id ? 1 : 0,
  );
  const total = selected.length;
  const failed = failures.length;
  return new VectorRun(
    suite.suiteVersion,
    total,
    total - failed,
    failed,
    failures,
  );
}
