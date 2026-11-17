/**
 * Canonical JSON helpers shared by the trace serializer and the vector runner.
 *
 * RFC 0005 §6.3/§6.8 and the Python reference use
 * `json.dumps(..., sort_keys=True, ensure_ascii=True)` (compact for results,
 * two-space indent for vector files, one trailing newline). These helpers
 * reproduce those bytes for the JSON data model used by contracts/traces.
 */

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) !== null
  );
}

/** Recursively sort object keys; arrays keep their order. */
export function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sortKeysDeep(item));
  }
  if (isPlainObject(value)) {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      sorted[key] = sortKeysDeep(value[key]);
    }
    return sorted;
  }
  return value;
}

/**
 * Escape every non-ASCII code point as `\uXXXX`, matching Python's
 * `ensure_ascii=True`. Astral characters become a surrogate pair.
 */
export function ensureAscii(text: string): string {
  let output = "";
  for (const character of text) {
    const codePoint = character.codePointAt(0);
    if (codePoint === undefined) continue;
    if (codePoint <= 0x7f) {
      output += character;
    } else if (codePoint <= 0xffff) {
      output += `\\u${codePoint.toString(16).padStart(4, "0")}`;
    } else {
      const value = codePoint - 0x10000;
      const high = 0xd800 + (value >> 10);
      const low = 0xdc00 + (value & 0x3ff);
      output += `\\u${high.toString(16).padStart(4, "0")}`;
      output += `\\u${low.toString(16).padStart(4, "0")}`;
    }
  }
  return output;
}

/** Sorted-key compact JSON (no trailing newline). */
export function canonicalCompact(value: unknown): string {
  return ensureAscii(JSON.stringify(sortKeysDeep(value)));
}

/** Sorted-key two-space JSON plus exactly one trailing newline. */
export function canonicalPretty(value: unknown): string {
  return `${ensureAscii(JSON.stringify(sortKeysDeep(value), null, 2))}\n`;
}

/**
 * Sorted-key compact JSON in UTF-8, without ASCII escaping.
 * This matches Python's `ensure_ascii=False`, used by `TraceLog.to_jsonl()`.
 */
export function canonicalCompactUtf8(value: unknown): string {
  return JSON.stringify(sortKeysDeep(value));
}
