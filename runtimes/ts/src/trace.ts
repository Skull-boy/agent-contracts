/**
 * RFC 0003 §C4 trace schema with the additive RFC 0005 §4.4 field.
 *
 * Parsing is fail-closed: unknown fields, missing fields, wrong types,
 * non-boolean `provisional`, bad SHA-256 strings, non-ISO-8601 timestamps, and
 * unknown result values are rejected. Serialization is canonical: sorted keys,
 * compact separators, one object per line, newline-terminated. A full-mode
 * entry omits `provisional` and is byte-identical to the pre-RFC-0005 output.
 */

import { TraceError } from "./errors.js";
import { canonicalCompactUtf8 } from "./json.js";
import type { AuditEntry, Decision } from "./enforcer.js";

export const TRACE_RESULT_ALLOWED = "allowed" as const;
export const TRACE_RESULT_PENDING_APPROVAL = "pending_approval" as const;
export const TRACE_RESULT_VIOLATION = "violation" as const;
export type TraceResult =
  | typeof TRACE_RESULT_ALLOWED
  | typeof TRACE_RESULT_PENDING_APPROVAL
  | typeof TRACE_RESULT_VIOLATION;

export const TRACE_RESULTS: ReadonlySet<TraceResult> = new Set([
  TRACE_RESULT_ALLOWED,
  TRACE_RESULT_PENDING_APPROVAL,
  TRACE_RESULT_VIOLATION,
]);

const RESULT_TO_DECISION: Record<TraceResult, Decision> = {
  allowed: "ALLOWED",
  pending_approval: "PENDING",
  violation: "DENIED",
};

const REQUIRED_FIELDS = [
  "node_id",
  "action_name",
  "action_type",
  "declared",
  "result",
  "hash_of_contract",
  "timestamp",
  "reason",
  "contract_field_reference",
] as const;

const OPTIONAL_FIELDS = ["provisional"] as const;

const UNDECLARED_MARKER = " is not declared in ";
const HASH_PATTERN = /^[0-9a-fA-F]{64}$/;
const TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(?:([Zz])|([+-])(\d{2}):?(\d{2}))?)?$/;

export interface TraceEntryInit {
  readonly nodeId: string | null;
  readonly actionName: string;
  readonly actionType: string;
  readonly declared: boolean;
  readonly result: TraceResult;
  readonly hashOfContract: string;
  readonly timestamp: string;
  readonly reason: string;
  readonly contractFieldReference: string;
  readonly provisional?: boolean;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) !== null
  );
}

function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

function daysInMonth(year: number, month: number): number {
  const days = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return days[month - 1] ?? 0;
}

/** Accept the ISO-8601 subset Python's `datetime.fromisoformat` accepts. */
export function isIsoTimestamp(value: string): boolean {
  if (!value) return false;
  const match = TIMESTAMP_PATTERN.exec(value);
  if (match === null) return false;
  const year = Number.parseInt(match[1] ?? "", 10);
  const month = Number.parseInt(match[2] ?? "", 10);
  const day = Number.parseInt(match[3] ?? "", 10);
  if (month < 1 || month > 12) return false;
  if (day < 1 || day > daysInMonth(year, month)) return false;
  if (match[4] !== undefined) {
    const hour = Number.parseInt(match[4], 10);
    const minute = Number.parseInt(match[5] ?? "", 10);
    const second =
      match[6] === undefined ? 0 : Number.parseInt(match[6], 10);
    if (hour > 23 || minute > 59 || second > 59) return false;
  }
  if (match[9] !== undefined) {
    const offsetHour = Number.parseInt(match[10] ?? "", 10);
    const offsetMinute = Number.parseInt(match[11] ?? "", 10);
    if (offsetHour > 23 || offsetMinute > 59) return false;
  }
  return true;
}

function requireString(
  value: unknown,
  field: string,
  allowEmpty = true,
): string {
  if (typeof value !== "string") {
    throw new TraceError(`trace field '${field}' must be a string`);
  }
  if (!allowEmpty && value.length === 0) {
    throw new TraceError(`trace field '${field}' must be non-empty`);
  }
  return value;
}

function validateHash(value: unknown): string {
  if (typeof value !== "string" || value.length !== 64) {
    throw new TraceError(
      "trace field 'hash_of_contract' must be a 64-character hexadecimal " +
        "SHA-256 string",
    );
  }
  if (!HASH_PATTERN.test(value)) {
    throw new TraceError(
      "trace field 'hash_of_contract' must be hexadecimal",
    );
  }
  return value;
}

function validateTimestamp(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TraceError(
      "trace field 'timestamp' must be a non-empty string",
    );
  }
  if (!isIsoTimestamp(value)) {
    throw new TraceError(
      `trace field 'timestamp' is not ISO-8601: ${JSON.stringify(value)}`,
    );
  }
  return value;
}

export class TraceEntry {
  readonly nodeId: string | null;
  readonly actionName: string;
  readonly actionType: string;
  readonly declared: boolean;
  readonly result: TraceResult;
  readonly hashOfContract: string;
  readonly timestamp: string;
  readonly reason: string;
  readonly contractFieldReference: string;
  readonly provisional: boolean | undefined;

  constructor(init: TraceEntryInit) {
    if (init.nodeId !== null) {
      requireString(init.nodeId, "node_id", false);
    }
    requireString(init.actionName, "action_name", false);
    requireString(init.actionType, "action_type", false);
    if (typeof init.declared !== "boolean") {
      throw new TraceError("trace field 'declared' must be a boolean");
    }
    if (
      init.provisional !== undefined &&
      typeof init.provisional !== "boolean"
    ) {
      throw new TraceError(
        "trace field 'provisional' must be a boolean",
      );
    }
    if (!TRACE_RESULTS.has(init.result)) {
      throw new TraceError(
        `trace field 'result' must be one of ` +
          `${JSON.stringify([...TRACE_RESULTS].sort())}, got ` +
          `${JSON.stringify(init.result)}`,
      );
    }
    validateHash(init.hashOfContract);
    validateTimestamp(init.timestamp);
    requireString(init.reason, "reason");
    requireString(init.contractFieldReference, "contract_field_reference");

    this.nodeId = init.nodeId;
    this.actionName = init.actionName;
    this.actionType = init.actionType;
    this.declared = init.declared;
    this.result = init.result;
    this.hashOfContract = init.hashOfContract;
    this.timestamp = init.timestamp;
    this.reason = init.reason;
    this.contractFieldReference = init.contractFieldReference;
    this.provisional = init.provisional;
    Object.freeze(this);
  }

  static fromDict(data: unknown): TraceEntry {
    if (!isPlainObject(data)) {
      throw new TraceError(
        `trace entry must be a JSON object, got ${
          data === null ? "null" : Array.isArray(data) ? "array" : typeof data
        }`,
      );
    }
    const missing = REQUIRED_FIELDS.filter((field) => !(field in data));
    if (missing.length > 0) {
      throw new TraceError(
        `trace entry is missing field(s): ${missing.join(", ")}`,
      );
    }
    const allowed = new Set<string>([
      ...REQUIRED_FIELDS,
      ...OPTIONAL_FIELDS,
    ]);
    const unknown = Object.keys(data)
      .filter((key) => !allowed.has(key))
      .sort();
    if (unknown.length > 0) {
      throw new TraceError(
        `trace entry has unknown field(s): ${unknown.join(", ")}`,
      );
    }

    let provisional: boolean | undefined;
    if ("provisional" in data) {
      if (typeof data["provisional"] !== "boolean") {
        throw new TraceError(
          "trace field 'provisional' must be a boolean when present",
        );
      }
      provisional = data["provisional"];
    }

    return new TraceEntry({
      nodeId: data["node_id"] as string | null,
      actionName: data["action_name"] as string,
      actionType: data["action_type"] as string,
      declared: data["declared"] as boolean,
      result: data["result"] as TraceResult,
      hashOfContract: data["hash_of_contract"] as string,
      timestamp: data["timestamp"] as string,
      reason: data["reason"] as string,
      contractFieldReference: data["contract_field_reference"] as string,
      provisional,
    });
  }

  toDict(): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      node_id: this.nodeId,
      action_name: this.actionName,
      action_type: this.actionType,
      declared: this.declared,
      result: this.result,
      hash_of_contract: this.hashOfContract,
      timestamp: this.timestamp,
      reason: this.reason,
      contract_field_reference: this.contractFieldReference,
    };
    if (this.provisional === true) {
      payload["provisional"] = true;
    }
    return payload;
  }
}

export class TraceLog {
  readonly entries: readonly TraceEntry[];

  constructor(entries: readonly TraceEntry[] = []) {
    for (const entry of entries) {
      if (!(entry instanceof TraceEntry)) {
        throw new TraceError(
          "trace log entries must be TraceEntry values",
        );
      }
    }
    this.entries = Object.freeze([...entries]);
  }

  toJsonl(): string {
    return this.entries
      .map((entry) => `${canonicalCompactUtf8(entry.toDict())}\n`)
      .join("");
  }

  static fromJsonl(text: string): TraceLog {
    if (typeof text !== "string") {
      throw new TraceError("trace JSONL must be a string");
    }
    const lines = splitLines(text);
    const entries: TraceEntry[] = [];
    lines.forEach((line, index) => {
      const number = index + 1;
      if (line.trim().length === 0) {
        throw new TraceError(`trace JSONL line ${number}: empty line`);
      }
      let payload: unknown;
      try {
        payload = JSON.parse(line);
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        throw new TraceError(
          `trace JSONL line ${number}: invalid JSON (${detail})`,
        );
      }
      try {
        entries.push(TraceEntry.fromDict(payload));
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        throw new TraceError(
          `trace JSONL line ${number}: ${detail}`,
        );
      }
    });
    return new TraceLog(entries);
  }
}

function splitLines(text: string): string[] {
  if (text.length === 0) return [];
  const lines = text.split(/\r\n|\n|\r/);
  if (lines.length > 0 && lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

/**
 * Convert an enforcer audit entry to a trace entry, mirroring the Python
 * reference's `trace_from_audit`. `declared` is derived from the audit reason:
 * only the default-deny path carries the undeclared marker.
 */
export function traceFromAudit(
  entry: AuditEntry,
  options: { nodeId: string | null; contractHash: string },
): TraceEntry {
  const result = decisionToResult(entry.decision);
  const declared = !(
    entry.decision === "DENIED" && entry.reason.includes(UNDECLARED_MARKER)
  );
  return new TraceEntry({
    nodeId: options.nodeId,
    actionName: entry.actionName,
    actionType: entry.actionType,
    declared,
    result,
    hashOfContract: options.contractHash,
    timestamp: entry.timestamp,
    reason: entry.reason,
    contractFieldReference: entry.contractFieldReference,
    provisional: entry.provisional ? true : undefined,
  });
}

function decisionToResult(decision: Decision): TraceResult {
  const found = (Object.keys(RESULT_TO_DECISION) as TraceResult[]).find(
    (result) => RESULT_TO_DECISION[result] === decision,
  );
  if (found === undefined) {
    throw new TraceError(
      `unknown audit decision ${JSON.stringify(decision)}`,
    );
  }
  return found;
}
