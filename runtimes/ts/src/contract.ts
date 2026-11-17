/**
 * Contract loading, security constraints, and immutability.
 *
 * This is the native port of the load path in `src/scyvera/enforcer.py`. It
 * loads v1/v1.1/v1.2 YAML, applies the RFC 0005 load-mode gate, and freezes the
 * parsed contract. It does not implement the registry or re-seal machinery;
 * those remain Python-owned (RFC 0005 §6.10).
 */

import { createHash } from "node:crypto";
import {
  existsSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";

import {
  ContractFileNotFoundError,
  ContractValidationError,
  ContractVersionError,
  ContractViolationError,
  GuardrailConfigError,
  ProvisionalContractError,
} from "./errors.js";
import {
  applyLifecycleDefaults,
  detectContractVersion,
  loadContractYaml,
  validateContractObject,
} from "./schema.js";
import { parseGuardrails, type Guardrails } from "./guardrails.js";

export type LoadMode = "full" | "draft";

export interface ContractIdentity {
  readonly canonicalPath: string;
  readonly requestedPath: string;
  readonly loadHash: string;
  readonly resolvedSymlink: boolean;
  readonly mode: LoadMode;
}

export interface LoadedContractFile {
  readonly contractPath: string;
  readonly contract: Readonly<Record<string, unknown>>;
  readonly integrityHash: string;
  readonly identity: ContractIdentity;
  readonly guardrails: Guardrails | undefined;
  readonly mode: LoadMode;
}

const WILDCARDS = new Set(["*", "all", "any"]);
const SERVICE_SCOPE_PATTERN = /^[a-zA-Z0-9_-]+:[a-zA-Z0-9_:-]+$/;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) !== null
  );
}

function isUnder(candidate: string, root: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

/** Deep-freeze the contract so post-load mutation fails loudly in strict mode. */
export function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    for (const key of Object.keys(value)) {
      deepFreeze((value as Record<string, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

export function sha256Bytes(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

export function sha256File(path: string): string {
  return sha256Bytes(readFileSync(path));
}

function validateVersionInvariants(
  contract: Record<string, unknown>,
  path: string,
): void {
  const explicit = contract["contract_version"];
  if (explicit === "1.1" && !("lifecycle" in contract)) {
    throw new ContractVersionError(
      `Contract at '${path}' explicitly declares contract_version: '1.1' ` +
        `but is missing the required 'lifecycle' field. Declare a ` +
        `'lifecycle' block (e.g. {mode: request-response}).`,
    );
  }
  if (detectContractVersion(contract) === null) {
    throw new ContractVersionError(
      `Unsupported or unrecognized contract version in '${path}'. Expected ` +
        `'1', '1.1', or '1.2', found version=${String(contract["version"])}, ` +
        `contract_version=${String(explicit)}.`,
    );
  }
}

function validateSecurityConstraints(
  contract: Record<string, unknown>,
  path: string,
): void {
  const permissions = contract["permissions"];
  if (Array.isArray(permissions)) {
    for (const permission of permissions) {
      if (typeof permission === "string") {
        const cleaned = permission.trim();
        if (WILDCARDS.has(cleaned)) {
          throw new ContractValidationError(
            `Wildcard permission '${cleaned}' is prohibited in '${path}' ` +
              `(Threat T7).`,
          );
        }
        if (!SERVICE_SCOPE_PATTERN.test(cleaned)) {
          throw new ContractValidationError(
            `Permission string '${cleaned}' does not match required ` +
              `service:scope pattern (e.g. 'github:issues:write') in '${path}'.`,
          );
        }
      } else if (isPlainObject(permission)) {
        for (const [key, value] of Object.entries(permission)) {
          if (WILDCARDS.has(key) || WILDCARDS.has(String(value).trim())) {
            throw new ContractValidationError(
              `Wildcard entry '${key}: ${String(value)}' in permissions is ` +
                `prohibited in '${path}' (Threat T7).`,
            );
          }
          if (Array.isArray(value)) {
            for (const action of value) {
              if (WILDCARDS.has(String(action).trim())) {
                throw new ContractValidationError(
                  `Wildcard action '${String(action)}' in permission '${key}' ` +
                    `is prohibited in '${path}' (Threat T7).`,
                );
              }
            }
          }
        }
      }
    }
  }

  const sideEffects = contract["side_effects"];
  if (Array.isArray(sideEffects)) {
    for (const sideEffect of sideEffects) {
      if (
        typeof sideEffect === "string" &&
        WILDCARDS.has(sideEffect.trim())
      ) {
        throw new ContractValidationError(
          `Wildcard side effect '${sideEffect}' is prohibited in '${path}' ` +
            `(Threat T7).`,
        );
      }
    }
  }
}

/**
 * Load and validate a file contract.
 *
 * The rejected `.yml` suffix, T14 escape refusal, version invariants, wildcard
 * refusal, schema validation, guardrail parsing, and the RFC 0005 §4.1 mode
 * gate run in the same order as the Python reference.
 */
export function loadContractFile(
  rawPath: string,
  options: { mode?: LoadMode } = {},
): LoadedContractFile {
  const mode = options.mode ?? "full";
  if (mode !== "full" && mode !== "draft") {
    throw new TypeError(
      `Invalid enforcer mode '${String(mode)}'; expected 'full' or 'draft'.`,
    );
  }

  const lexicalPath = resolve(rawPath);
  if (!existsSync(lexicalPath)) {
    throw new ContractFileNotFoundError(lexicalPath);
  }

  const canonicalPath = realpathSync(lexicalPath);
  const addressedDir = dirname(lexicalPath);
  if (!isUnder(canonicalPath, addressedDir)) {
    throw new ContractViolationError(
      "load",
      lexicalPath,
      "Keep contract.yaml inside the addressed directory, or pass the real " +
        "path explicitly.",
      `Refusing to load contract '${lexicalPath}': it resolves to ` +
        `'${canonicalPath}', which is outside the addressed directory ` +
        `'${addressedDir}' (T14 symlink escape).`,
    );
  }
  const resolvedSymlink = canonicalPath !== lexicalPath;

  const bytes = readFileSync(canonicalPath);
  const integrityHash = sha256Bytes(bytes);

  const rawData = loadContractYaml(canonicalPath);
  if (!isPlainObject(rawData)) {
    throw new ContractValidationError(
      `Contract file '${canonicalPath}' must contain a YAML mapping, got ` +
        `${rawData === null ? "null" : Array.isArray(rawData) ? "array" : typeof rawData}.`,
    );
  }

  validateVersionInvariants(rawData, canonicalPath);
  validateSecurityConstraints(rawData, canonicalPath);

  const validation = validateContractObject(rawData);
  if (!validation.valid) {
    const details = validation.errors
      .map((issue) =>
        issue.path ? `${issue.path}: ${issue.message}` : issue.message,
      )
      .join("; ");
    throw new ContractValidationError(
      `Contract validation failed for '${canonicalPath}': ${details}`,
      validation.errors,
    );
  }

  let guardrails: Guardrails | undefined;
  try {
    guardrails = parseGuardrails(rawData["guardrails"]);
  } catch (error) {
    if (error instanceof GuardrailConfigError) {
      throw new ContractValidationError(
        `Contract validation failed for '${canonicalPath}': invalid ` +
          `guardrails block: ${error.message}`,
      );
    }
    throw error;
  }

  const fileIsProvisional = rawData["provisional"] === true;
  if (mode === "draft" && !fileIsProvisional) {
    throw new ContractValidationError(
      `Contract '${canonicalPath}' is not provisional; draft mode ` +
        `(mode="draft") is only for contracts with \`provisional: true\`.`,
    );
  }
  if (mode === "full" && fileIsProvisional) {
    throw new ProvisionalContractError(canonicalPath);
  }

  const contract = deepFreeze(applyLifecycleDefaults(rawData));
  const identity: ContractIdentity = Object.freeze({
    canonicalPath,
    requestedPath: lexicalPath,
    loadHash: integrityHash,
    resolvedSymlink,
    mode,
  });

  return {
    contractPath: canonicalPath,
    contract,
    integrityHash,
    identity,
    guardrails,
    mode,
  };
}
