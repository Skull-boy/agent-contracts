/**
 * Fail-closed contract validation for v1, v1.1, and v1.2.
 *
 * The JSON Schema files are copied verbatim from the Python reference
 * (`src/scyvera/schemas/`) by `scripts/copy-assets.mjs`. This module implements
 * the draft-2020-12 subset those schemas use. There is deliberately no
 * `$ref`, dynamic scope, or format registry: a schema construct this evaluator
 * does not understand would be a silent gap, so the supported keyword list is
 * closed and documented in the README.
 */

import { readFileSync } from "node:fs";
import { extname } from "node:path";
import { parse as parseYaml } from "yaml";

import {
  ContractFileNameError,
  ContractValidationError,
  type ValidationIssue,
} from "./errors.js";

export type ContractVersion = "1" | "1.1" | "1.2";

export interface ValidationResult {
  readonly valid: boolean;
  readonly errors: readonly ValidationIssue[];
}

export interface LifecycleDefaults {
  readonly mode: string;
  readonly initiation: string;
  readonly resumability: string;
}

export const LIFECYCLE_DEFAULTS: LifecycleDefaults = Object.freeze({
  mode: "request-response",
  initiation: "human-only",
  resumability: "stateless",
});

const SCHEMA_URLS: Record<ContractVersion, URL> = {
  "1": new URL("./schemas/v1/contract.schema.json", import.meta.url),
  "1.1": new URL("./schemas/v1.1/contract.schema.json", import.meta.url),
  "1.2": new URL("./schemas/v1.2/contract.schema.json", import.meta.url),
};

const schemaCache = new Map<ContractVersion, JsonSchema>();

type JsonSchema = Record<string, unknown>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) !== null
  );
}

function pointerToken(key: string): string {
  return key.replaceAll("~", "~0").replaceAll("/", "~1");
}

function childPath(path: string, key: string | number): string {
  return `${path}/${pointerToken(String(key))}`;
}

function describe(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function printable(value: unknown): string {
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function deepEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((item, index) => deepEqual(item, right[index]))
    );
  }
  if (isPlainObject(left) && isPlainObject(right)) {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every(
        (key) =>
          Object.prototype.hasOwnProperty.call(right, key) &&
          deepEqual(left[key], right[key]),
      )
    );
  }
  return false;
}

function matchesType(type: string, value: unknown): boolean {
  switch (type) {
    case "object":
      return isPlainObject(value);
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "boolean":
      return typeof value === "boolean";
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "null":
      return value === null;
    default:
      // Unknown type keywords fail closed rather than silently passing.
      return false;
  }
}

function push(
  errors: ValidationIssue[],
  path: string,
  message: string,
): void {
  errors.push({ path, message });
}

function validateNode(
  schema: unknown,
  value: unknown,
  path: string,
  errors: ValidationIssue[],
): void {
  if (schema === true || schema === undefined) return;
  if (schema === false) {
    push(errors, path, `False schema does not allow ${printable(value)}`);
    return;
  }
  if (!isPlainObject(schema)) {
    push(errors, path, "schema node is not an object");
    return;
  }

  const type = schema["type"];
  if (typeof type === "string") {
    if (!matchesType(type, value)) {
      push(
        errors,
        path,
        `${printable(value)} is not of type '${type}'`,
      );
      return;
    }
  } else if (Array.isArray(type)) {
    if (!type.some((item) => typeof item === "string" && matchesType(item, value))) {
      push(
        errors,
        path,
        `${printable(value)} is not of type ${JSON.stringify(type)}`,
      );
      return;
    }
  }

  if ("const" in schema && !deepEqual(value, schema["const"])) {
    push(errors, path, `${printable(value)} was expected`);
  }

  if (Array.isArray(schema["enum"])) {
    if (!schema["enum"].some((item) => deepEqual(value, item))) {
      push(
        errors,
        path,
        `${printable(value)} is not one of ${JSON.stringify(schema["enum"])}`,
      );
    }
  }

  if (Array.isArray(schema["anyOf"])) {
    const matches = schema["anyOf"].filter((branch) => {
      const branchErrors: ValidationIssue[] = [];
      validateNode(branch, value, path, branchErrors);
      return branchErrors.length === 0;
    });
    if (matches.length === 0) {
      push(
        errors,
        path,
        `${printable(value)} is not valid under any of the given schemas`,
      );
    }
  }

  if (Array.isArray(schema["oneOf"])) {
    let matches = 0;
    for (const branch of schema["oneOf"]) {
      const branchErrors: ValidationIssue[] = [];
      validateNode(branch, value, path, branchErrors);
      if (branchErrors.length === 0) matches += 1;
    }
    if (matches === 0) {
      push(
        errors,
        path,
        `${printable(value)} is not valid under any of the given schemas`,
      );
    } else if (matches > 1) {
      push(
        errors,
        path,
        `${printable(value)} is valid under each of the given schemas`,
      );
    }
  }

  if ("not" in schema) {
    const branchErrors: ValidationIssue[] = [];
    validateNode(schema["not"], value, path, branchErrors);
    if (branchErrors.length === 0) {
      push(
        errors,
        path,
        `${printable(value)} should not be valid under ${printable(schema["not"])}`,
      );
    }
  }

  if ("if" in schema) {
    const conditionErrors: ValidationIssue[] = [];
    validateNode(schema["if"], value, path, conditionErrors);
    if (conditionErrors.length === 0 && "then" in schema) {
      validateNode(schema["then"], value, path, errors);
    } else if (conditionErrors.length > 0 && "else" in schema) {
      validateNode(schema["else"], value, path, errors);
    }
  }

  if (isPlainObject(value)) {
    const required = schema["required"];
    if (Array.isArray(required)) {
      for (const key of required) {
        if (typeof key === "string" && !(key in value)) {
          push(errors, path, `'${key}' is a required property`);
        }
      }
    }

    const minProperties = schema["minProperties"];
    if (typeof minProperties === "number") {
      if (Object.keys(value).length < minProperties) {
        push(
          errors,
          path,
          `${printable(value)} does not have enough properties`,
        );
      }
    }
    const maxProperties = schema["maxProperties"];
    if (typeof maxProperties === "number") {
      if (Object.keys(value).length > maxProperties) {
        push(errors, path, `${printable(value)} has too many properties`);
      }
    }

    const properties = schema["properties"];
    const known = new Set<string>();
    if (isPlainObject(properties)) {
      for (const [key, childSchema] of Object.entries(properties)) {
        known.add(key);
        if (key in value) {
          validateNode(childSchema, value[key], childPath(path, key), errors);
        }
      }
    }

    const additional = schema["additionalProperties"];
    if (additional !== undefined) {
      const unknownKeys = Object.keys(value).filter((key) => !known.has(key));
      if (additional === false) {
        for (const key of unknownKeys) {
          push(
            errors,
            path,
            `Additional properties are not allowed ('${key}' was unexpected)`,
          );
        }
      } else if (isPlainObject(additional)) {
        for (const key of unknownKeys) {
          validateNode(
            additional,
            value[key],
            childPath(path, key),
            errors,
          );
        }
      }
    }
  }

  if (Array.isArray(value)) {
    const items = schema["items"];
    if (isPlainObject(items) || items === true || items === false) {
      value.forEach((item, index) => {
        validateNode(items, item, childPath(path, index), errors);
      });
    }
    const minItems = schema["minItems"];
    if (typeof minItems === "number" && value.length < minItems) {
      push(errors, path, `${printable(value)} is too short`);
    }
    const maxItems = schema["maxItems"];
    if (typeof maxItems === "number" && value.length > maxItems) {
      push(errors, path, `${printable(value)} is too long`);
    }
  }

  if (typeof value === "string") {
    const minLength = schema["minLength"];
    if (typeof minLength === "number") {
      if (Array.from(value).length < minLength) {
        push(errors, path, `${printable(value)} is too short`);
      }
    }
    const maxLength = schema["maxLength"];
    if (typeof maxLength === "number") {
      if (Array.from(value).length > maxLength) {
        push(errors, path, `${printable(value)} is too long`);
      }
    }
    const pattern = schema["pattern"];
    if (typeof pattern === "string") {
      let matched = true;
      try {
        matched = new RegExp(pattern, "u").test(value);
      } catch {
        matched = false;
      }
      if (!matched) {
        push(
          errors,
          path,
          `'${value}' does not match '${pattern}'`,
        );
      }
    }
  }

  if (typeof value === "number") {
    const minimum = schema["minimum"];
    if (typeof minimum === "number" && value < minimum) {
      push(
        errors,
        path,
        `${value} is less than the minimum of ${minimum}`,
      );
    }
    const maximum = schema["maximum"];
    if (typeof maximum === "number" && value > maximum) {
      push(
        errors,
        path,
        `${value} is greater than the maximum of ${maximum}`,
      );
    }
  }
}

function schemaFor(version: ContractVersion): JsonSchema {
  const cached = schemaCache.get(version);
  if (cached !== undefined) return cached;
  const url = SCHEMA_URLS[version];
  const parsed: unknown = JSON.parse(readFileSync(url, "utf8"));
  if (!isPlainObject(parsed)) {
    throw new Error(`schema asset is not a JSON object: ${url.pathname}`);
  }
  schemaCache.set(version, parsed);
  return parsed;
}

/**
 * Detect the contract specification version exactly as the Python validator
 * does: an explicit `contract_version` wins, then `version`, then v1.
 * Returns `null` for an explicitly unsupported version.
 */
export function detectContractVersion(
  contract: Record<string, unknown>,
): ContractVersion | null {
  const explicit = contract["contract_version"];
  if (explicit !== undefined && explicit !== null) {
    const value = String(explicit);
    if (value === "1.2") return "1.2";
    if (value === "1.1") return "1.1";
    if (value === "1") return "1";
    return null;
  }

  if ("version" in contract) {
    const value = contract["version"];
    if (value === 1.2 || value === "1.2") return "1.2";
    if (value === 1.1 || value === "1.1") return "1.1";
    if (value === 1 || value === "1") return "1";
    if (value === null) return "1";
    return null;
  }

  return "1";
}

/**
 * Validate an already-parsed contract mapping.
 *
 * The v1 + `provisional` rejection is a validator rule before schema
 * selection, matching the RFC 0005 §3.1 requirement and the Python reference.
 */
export function validateContractObject(
  contract: unknown,
): ValidationResult {
  if (!isPlainObject(contract)) {
    return {
      valid: false,
      errors: [
        {
          path: "",
          message: `contract must be a mapping, got ${describe(contract)}`,
        },
      ],
    };
  }

  const version = detectContractVersion(contract);
  if (version === "1" && "provisional" in contract) {
    return {
      valid: false,
      errors: [
        {
          path: "/provisional",
          message:
            "`provisional` is not supported on contract_version 1; " +
            "provisional contracts require contract_version 1.1 or later.",
        },
      ],
    };
  }

  if (version === null) {
    return {
      valid: false,
      errors: [
        {
          path: "/version",
          message: `Unsupported specification version: ${String(contract["version"])}`,
        },
      ],
    };
  }

  const errors: ValidationIssue[] = [];
  validateNode(schemaFor(version), contract, "", errors);
  errors.sort((left, right) => {
    if (left.path < right.path) return -1;
    if (left.path > right.path) return 1;
    return left.message < right.message ? -1 : left.message > right.message ? 1 : 0;
  });
  return { valid: errors.length === 0, errors };
}

/** Read a contract YAML file. `.yml` is rejected; `.yaml` is canonical. */
export function loadContractYaml(path: string): unknown {
  if (extname(path) === ".yml") {
    throw new ContractFileNameError(path);
  }
  const text = readFileSync(path, "utf8");
  try {
    return parseYaml(text);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new ContractValidationError(
      `Contract file '${path}' is not valid YAML: ${detail}`,
    );
  }
}

/** Validate a contract file, resolving the schema by its declared version. */
export function validateContractFile(path: string): ValidationResult {
  const contract = loadContractYaml(path);
  if (contract === null || contract === undefined) {
    return {
      valid: false,
      errors: [{ path: "", message: "contract.yaml is empty" }],
    };
  }
  return validateContractObject(contract);
}

/**
 * Apply the v1.1/v1.2 lifecycle default when the block is absent.
 * v1 contracts are returned unchanged.
 */
export function applyLifecycleDefaults(
  contract: Record<string, unknown>,
): Record<string, unknown> {
  const version = detectContractVersion(contract);
  if (version !== "1.1" && version !== "1.2") {
    return contract;
  }
  if ("lifecycle" in contract) {
    return contract;
  }
  return { ...contract, lifecycle: { ...LIFECYCLE_DEFAULTS } };
}
