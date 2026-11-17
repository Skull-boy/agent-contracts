/**
 * RFC 0003 §C5 guardrails (v1.2) — the portable subset used by this runtime.
 *
 * Counters are per enforcer instance and per process. They bound one runtime's
 * behavior; they are not a distributed quota. This matches the Python
 * reference's documented limitation.
 */

import { GuardrailConfigError } from "./errors.js";

export const RATE_LIMIT_WINDOW_SECONDS = 60;
export const FAIL_CLOSED_FIELD_REFERENCE = "guardrails.fail_closed";
export const BUDGETS_FIELD_REFERENCE = "guardrails.budgets";
export const RATE_LIMIT_FIELD_REFERENCE = "guardrails.rate_limit";

const WINDOW_PATTERN = /^([0-9]+)(s|m|h|d)$/;
const WINDOW_MULTIPLIERS: Record<string, number> = {
  s: 1,
  m: 60,
  h: 60 * 60,
  d: 24 * 60 * 60,
};

export interface Budgets {
  readonly sideEffectsPerWindow: number;
  readonly window: string;
  readonly windowSeconds: number;
}

export interface RateLimit {
  readonly maxCallsPerMinute: number;
}

export interface Guardrails {
  readonly failClosed: boolean;
  readonly budgets: Budgets | undefined;
  readonly rateLimit: RateLimit | undefined;
}

export function parseWindow(value: unknown): number {
  if (typeof value !== "string") {
    throw new GuardrailConfigError(
      `guardrails window must be a string like '1h', got ${typeof value}`,
    );
  }
  const match = WINDOW_PATTERN.exec(value);
  if (match === null) {
    throw new GuardrailConfigError(
      `guardrails window '${value}' must match ^[0-9]+(s|m|h|d)$ ` +
        `(examples: '30m', '1h', '7d')`,
    );
  }
  const amount = Number.parseInt(match[1] ?? "", 10);
  if (amount <= 0) {
    throw new GuardrailConfigError(
      `guardrails window '${value}' must be greater than zero`,
    );
  }
  return amount * (WINDOW_MULTIPLIERS[match[2] ?? ""] ?? 0);
}

function requireMapping(
  value: unknown,
  field: string,
): Record<string, unknown> {
  if (!isPlainObject(value)) {
    throw new GuardrailConfigError(
      `guardrails.${field} must be an object, got ${describe(value)}`,
    );
  }
  return value;
}

function requirePositiveInt(value: unknown, field: string): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 1
  ) {
    throw new GuardrailConfigError(
      `guardrails.${field} must be an integer >= 1, got ${describe(value)}`,
    );
  }
  return value;
}

function rejectUnknown(
  data: Record<string, unknown>,
  allowed: readonly string[],
  field: string,
): void {
  const unknown = Object.keys(data)
    .filter((key) => !allowed.includes(key))
    .sort();
  if (unknown.length > 0) {
    throw new GuardrailConfigError(
      `guardrails.${field} has unknown key(s): ${unknown.join(", ")}`,
    );
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

function describe(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

/**
 * Parse the optional top-level `guardrails` block.
 *
 * Returns `undefined` when the key is absent (not an empty object), matching
 * the Python reference. `{}` yields an explicit no-op record.
 */
export function parseGuardrails(raw: unknown): Guardrails | undefined {
  if (raw === undefined || raw === null) {
    return undefined;
  }

  const data = requireMapping(raw, "<root>");
  rejectUnknown(data, ["fail_closed", "budgets", "rate_limit"], "<root>");

  const failClosedRaw = data["fail_closed"] ?? false;
  if (typeof failClosedRaw !== "boolean") {
    throw new GuardrailConfigError(
      `guardrails.fail_closed must be a boolean, got ${describe(failClosedRaw)}`,
    );
  }

  let budgets: Budgets | undefined;
  if ("budgets" in data) {
    const budgetsRaw = requireMapping(data["budgets"], "budgets");
    rejectUnknown(
      budgetsRaw,
      ["side_effects_per_window", "window"],
      "budgets",
    );
    if (!("side_effects_per_window" in budgetsRaw)) {
      throw new GuardrailConfigError(
        "guardrails.budgets requires 'side_effects_per_window'",
      );
    }
    if (!("window" in budgetsRaw)) {
      throw new GuardrailConfigError("guardrails.budgets requires 'window'");
    }
    const limit = requirePositiveInt(
      budgetsRaw["side_effects_per_window"],
      "budgets.side_effects_per_window",
    );
    const window = budgetsRaw["window"];
    budgets = {
      sideEffectsPerWindow: limit,
      window: typeof window === "string" ? window : String(window),
      windowSeconds: parseWindow(window),
    };
  }

  let rateLimit: RateLimit | undefined;
  if ("rate_limit" in data) {
    const rateRaw = requireMapping(data["rate_limit"], "rate_limit");
    rejectUnknown(rateRaw, ["max_calls_per_minute"], "rate_limit");
    if (!("max_calls_per_minute" in rateRaw)) {
      throw new GuardrailConfigError(
        "guardrails.rate_limit requires 'max_calls_per_minute'",
      );
    }
    rateLimit = {
      maxCallsPerMinute: requirePositiveInt(
        rateRaw["max_calls_per_minute"],
        "rate_limit.max_calls_per_minute",
      ),
    };
  }

  return { failClosed: failClosedRaw, budgets, rateLimit };
}
