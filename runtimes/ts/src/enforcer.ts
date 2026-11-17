/**
 * Native default-deny gate (RFC 0005 §4.2).
 *
 * Pipeline: integrity → declaration → approval → guardrails → allowed.
 * Draft mode changes exactly one decision: an irreversible action carries an
 * implicit human-approval gate even when the draft declares no approvals.
 * Every other check is unchanged, matching the Python reference.
 */

import { existsSync, realpathSync } from "node:fs";
import { basename } from "node:path";

import {
  ApprovalPendingError,
  ContractTamperError,
  ContractViolationError,
  GuardrailViolationError,
} from "./errors.js";
import {
  loadContractFile,
  sha256File,
  type ContractIdentity,
  type LoadMode,
  type LoadedContractFile,
} from "./contract.js";
import {
  BUDGETS_FIELD_REFERENCE,
  FAIL_CLOSED_FIELD_REFERENCE,
  RATE_LIMIT_FIELD_REFERENCE,
  RATE_LIMIT_WINDOW_SECONDS,
  type Guardrails,
} from "./guardrails.js";

export type ActionType = "permission" | "side_effect" | "read";
export type EffectiveActionType = "permission" | "side_effect";
export type Decision = "ALLOWED" | "DENIED" | "PENDING";

export interface AuditEntry {
  readonly timestamp: string;
  readonly actionName: string;
  readonly actionType: string;
  readonly decision: Decision;
  readonly reason: string;
  readonly contractFieldReference: string;
  readonly provisional: boolean;
}

export interface GateOutcome {
  readonly decision: Decision;
  readonly error?: unknown;
}

export interface ContractEnforcerOptions {
  readonly mode?: LoadMode;
  readonly clock?: () => Date;
}

export interface ApprovalConfig {
  readonly [key: string]: unknown;
}

const IRREVERSIBLE_PHRASES: readonly string[] = [
  "delete",
  "destroy",
  "drop",
  "truncate",
  "purge",
  "erase",
  "wipe",
  "force push",
  "remote execution",
  "publish",
  "deploy",
  "merge",
  "close",
  "transfer",
  "payment",
  "overwrite",
  "revoke",
];

const IRREVERSIBLE_PHRASE_TOKENS: readonly (readonly string[])[] =
  IRREVERSIBLE_PHRASES.map((phrase) => phrase.split(" "));

function irreversibleTokens(text: string): readonly string[] {
  const lowered = text.toLowerCase().replaceAll("_", " ").replaceAll("-", " ");
  return lowered
    .replace(/[^a-z0-9]+/g, " ")
    .split(" ")
    .filter((token) => token.length > 0);
}

function containsIrreversiblePhrase(text: string): boolean {
  const tokens = irreversibleTokens(text);
  if (tokens.length === 0) return false;
  for (const phrase of IRREVERSIBLE_PHRASE_TOKENS) {
    const width = phrase.length;
    if (width > tokens.length) continue;
    for (let index = 0; index <= tokens.length - width; index += 1) {
      if (phrase.every((token, offset) => tokens[index + offset] === token)) {
        return true;
      }
    }
  }
  return false;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) !== null
  );
}

function freezeEntry(entry: AuditEntry): AuditEntry {
  return Object.freeze(entry);
}

export class ContractEnforcer {
  private readonly loaded: LoadedContractFile;
  private readonly clock: () => Date;
  private readonly auditLog: AuditEntry[] = [];
  private readonly grantedApprovals = new Set<string>();
  private guardrailAttempts: Date[] = [];
  private guardrailAdmissions: Date[] = [];

  private constructor(loaded: LoadedContractFile, clock: () => Date) {
    this.loaded = loaded;
    this.clock = clock;
  }

  static load(
    path: string,
    options: ContractEnforcerOptions = {},
  ): ContractEnforcer {
    const loaded = loadContractFile(path, { mode: options.mode });
    return new ContractEnforcer(
      loaded,
      options.clock ?? (() => new Date()),
    );
  }

  get mode(): LoadMode {
    return this.loaded.mode;
  }

  get contract(): Readonly<Record<string, unknown>> {
    return this.loaded.contract;
  }

  get contractPath(): string {
    return this.loaded.contractPath;
  }

  get integrityHash(): string {
    return this.loaded.integrityHash;
  }

  get identity(): ContractIdentity {
    return this.loaded.identity;
  }

  get guardrails(): Guardrails | undefined {
    return this.loaded.guardrails;
  }

  get isProvisional(): boolean {
    return this.loaded.contract["provisional"] === true;
  }

  /**
   * Re-read the pinned canonical path and compare its SHA-256 to load time.
   * Throws ContractTamperError on removal, content change, or a path swap.
   */
  verifyIntegrity(): true {
    const { requestedPath, canonicalPath } = this.loaded.identity;
    try {
      // A post-load symlink swap is a T14 failure even if its bytes match.
      // Node exposes no portable lstat-free resolve, so use realpathSync.
      const current = sha256File(canonicalPath);
      if (current !== this.loaded.integrityHash) {
        throw new ContractTamperError(
          `Contract file '${canonicalPath}' has been tampered with on disk! ` +
            `Load-time hash: ${this.loaded.integrityHash}, Current hash: ` +
            `${current}. Reload the contract or restart the agent to recover.`,
        );
      }
    } catch (error) {
      if (error instanceof ContractTamperError) throw error;
      if (!existsSync(canonicalPath)) {
        throw new ContractTamperError(
          `Contract file '${canonicalPath}' was removed from disk after load! ` +
            `Reload the contract or restart the agent to recover.`,
        );
      }
      const detail = error instanceof Error ? error.message : String(error);
      throw new ContractTamperError(
        `Contract file '${canonicalPath}' could not be verified after load: ` +
          `${detail}. Reload the contract or restart the agent to recover.`,
      );
    }

    // The requested path is re-resolved only to detect a swap; reads always use
    // the canonical path pinned at load time.
    try {
      const currentTarget = realpathSync(requestedPath);
      if (currentTarget !== canonicalPath) {
        throw new ContractTamperError(
          `Contract path '${requestedPath}' now resolves to ` +
            `'${currentTarget}', but it was pinned to '${canonicalPath}' at ` +
            `load time. A symlink or path swap was detected after load (T14).`,
        );
      }
    } catch (error) {
      if (error instanceof ContractTamperError) throw error;
      throw new ContractTamperError(
        `Contract path '${requestedPath}' could not be resolved after load ` +
          `(T14 path swap). Reload the contract or restart the agent.`,
      );
    }

    return true;
  }

  /** Gate one action. Throws the native typed error on denial/pending. */
  enforce(actionName: string, actionType: ActionType): void {
    if (
      actionType !== "permission" &&
      actionType !== "side_effect" &&
      actionType !== "read"
    ) {
      throw new TypeError(
        `Invalid action_type '${String(actionType)}'. Must be 'side_effect', ` +
          `'permission', or 'read'.`,
      );
    }
    const effectiveType: EffectiveActionType =
      actionType === "read" ? "permission" : actionType;
    const now = new Date().toISOString();
    const guardrailMoment = this.recordGuardrailAttempt(
      actionName,
      effectiveType,
      now,
    );

    try {
      this.verifyIntegrity();
    } catch (error) {
      this.appendAudit({
        timestamp: new Date().toISOString(),
        actionName,
        actionType: effectiveType,
        decision: "DENIED",
        reason: "Contract was tampered with; gate denied.",
        contractFieldReference: "integrity_hash",
        provisional: this.mode === "draft",
      });
      throw error;
    }

    const declared = this.isActionDeclared(actionName, effectiveType);
    if (!declared.declared) {
      const suggestion =
        effectiveType === "side_effect" ? "side_effects" : "permissions";
      this.appendAudit({
        timestamp: now,
        actionName,
        actionType: effectiveType,
        decision: "DENIED",
        reason:
          `Action '${actionName}' is not declared in '${effectiveType}s'.`,
        contractFieldReference: declared.fieldReference,
        provisional: this.mode === "draft",
      });
      throw new ContractViolationError(
        actionName,
        basename(this.contractPath),
        suggestion,
      );
    }

    const approval = this.checkApprovalRequired(actionName);
    if (approval.required && !this.grantedApprovals.has(actionName)) {
      const impliedIrreversible =
        approval.config["source"] === "implicit-irreversible";
      const pendingReason = impliedIrreversible
        ? "Action requires human confirmation prior to execution " +
          "(irreversible in draft mode)."
        : "Action requires human confirmation prior to execution.";
      this.appendAudit({
        timestamp: now,
        actionName,
        actionType: effectiveType,
        decision: "PENDING",
        reason: pendingReason,
        contractFieldReference: "approval_points / approvals",
        provisional: this.mode === "draft",
      });
      throw new ApprovalPendingError(actionName, { ...approval.config });
    }

    if (guardrailMoment !== undefined) {
      this.enforceGuardrails(
        actionName,
        effectiveType,
        guardrailMoment,
        now,
      );
    }

    this.appendAudit({
      timestamp: now,
      actionName,
      actionType: effectiveType,
      decision: "ALLOWED",
      reason: `Action '${actionName}' matched declared contract specification.`,
      contractFieldReference: declared.fieldReference,
      provisional: this.mode === "draft",
    });
  }

  /** Gate one action and return the decision instead of throwing. */
  decide(actionName: string, actionType: ActionType): GateOutcome {
    try {
      this.enforce(actionName, actionType);
      return { decision: "ALLOWED" };
    } catch (error) {
      if (error instanceof ApprovalPendingError) {
        return { decision: "PENDING", error };
      }
      if (
        error instanceof ContractTamperError ||
        error instanceof ContractViolationError
      ) {
        return { decision: "DENIED", error };
      }
      throw error;
    }
  }

  approve(actionName: string, token = ""): void {
    const clean = actionName.trim();
    this.grantedApprovals.add(clean);
    this.appendAudit({
      timestamp: new Date().toISOString(),
      actionName: clean,
      actionType: "approval",
      decision: "ALLOWED",
      reason: `Human approval granted manually with token='${token}'.`,
      contractFieldReference: "approval_points / approvals",
      provisional: this.mode === "draft",
    });
  }

  getAuditLog(): AuditEntry[] {
    return this.auditLog.map((entry) => ({ ...entry }));
  }

  private appendAudit(entry: AuditEntry): void {
    this.auditLog.push(freezeEntry(entry));
  }

  private fieldArray(name: string): readonly unknown[] {
    const value = this.loaded.contract[name];
    return Array.isArray(value) ? value : [];
  }

  private isActionDeclared(
    actionName: string,
    actionType: EffectiveActionType,
  ): { declared: boolean; fieldReference: string } {
    const cleanAction = actionName.trim();

    if (actionType === "permission") {
      const fieldReference = "permissions";
      for (const permission of this.fieldArray("permissions")) {
        if (typeof permission === "string") {
          if (
            cleanAction === permission.trim() ||
            cleanAction.replaceAll(" ", "") ===
              permission.replaceAll(" ", "")
          ) {
            return { declared: true, fieldReference };
          }
        } else if (isPlainObject(permission)) {
          for (const [key, value] of Object.entries(permission)) {
            if (key === "resource" || key === "actions") continue;
            const combined = `${key}:${String(value)}`.replaceAll(" ", "");
            if (
              cleanAction.replaceAll(" ", "") === combined ||
              cleanAction === key ||
              cleanAction === String(value)
            ) {
              return { declared: true, fieldReference };
            }
          }
          const resource = permission["resource"];
          const actions = permission["actions"];
          if (typeof resource === "string" && resource.length > 0) {
            if (cleanAction === resource) {
              return { declared: true, fieldReference };
            }
            if (Array.isArray(actions)) {
              for (const action of actions) {
                const text = String(action);
                if (
                  cleanAction === `${resource}:${text}` ||
                  cleanAction === `${resource}: ${text}` ||
                  cleanAction === text
                ) {
                  return { declared: true, fieldReference };
                }
              }
            }
          }
        }
      }
      return { declared: false, fieldReference };
    }

    const fieldReference = "side_effects";
    return {
      declared: this.matchingSideEffectDeclarations(cleanAction).length > 0,
      fieldReference,
    };
  }

  /**
   * RFC 0005 §4.3 requires the irreversible check to use exactly the gate's
   * side-effect matching algorithm, so this is the single implementation.
   */
  private matchingSideEffectDeclarations(actionName: string): unknown[] {
    const cleanAction = actionName.trim();
    const cleanLower = cleanAction.toLowerCase();
    const matches: unknown[] = [];

    for (const sideEffect of this.fieldArray("side_effects")) {
      if (typeof sideEffect === "string") {
        if (
          cleanLower.includes(sideEffect.toLowerCase()) ||
          cleanAction === sideEffect ||
          sideEffect.toLowerCase().includes(cleanLower)
        ) {
          matches.push(sideEffect);
        }
      } else if (isPlainObject(sideEffect)) {
        const type = String(sideEffect["type"] ?? "").toLowerCase();
        const resource = String(sideEffect["resource"] ?? "").toLowerCase();
        const description = String(
          sideEffect["description"] ?? "",
        ).toLowerCase();

        if (
          cleanLower === type ||
          cleanLower === resource ||
          cleanLower === `${resource}:${type}`
        ) {
          matches.push(sideEffect);
          continue;
        }
        if (resource.length > 0 && cleanLower.startsWith(resource)) {
          const remainder = cleanLower
            .slice(resource.length)
            .replace(/^[:\-_ ]+/, "");
          if (
            remainder.length > 0 &&
            (type.includes(remainder) ||
              remainder.includes(type) ||
              description.includes(remainder))
          ) {
            matches.push(sideEffect);
            continue;
          }
        }
        if (
          description.includes(cleanLower) ||
          (type.length > 0 && type.includes(cleanLower))
        ) {
          matches.push(sideEffect);
        }
      }
    }
    return matches;
  }

  private isActionIrreversible(actionName: string): boolean {
    const matches = this.matchingSideEffectDeclarations(actionName);
    for (const declaration of matches) {
      if (
        isPlainObject(declaration) &&
        declaration["irreversible"] === true
      ) {
        return true;
      }
    }
    if (containsIrreversiblePhrase(actionName)) return true;

    for (const declaration of matches) {
      if (!isPlainObject(declaration)) continue;
      for (const field of ["type", "resource", "description"] as const) {
        const value = declaration[field];
        if (
          typeof value === "string" &&
          containsIrreversiblePhrase(value)
        ) {
          return true;
        }
      }
    }
    return false;
  }

  private checkApprovalRequired(actionName: string): {
    required: boolean;
    config: Record<string, unknown>;
  } {
    const cleanAction = actionName.trim();

    for (const point of this.fieldArray("approval_points")) {
      if (
        typeof point === "string" &&
        (cleanAction === point.trim() || cleanAction.includes(point.trim()))
      ) {
        return {
          required: true,
          config: {
            channel: "manual",
            timeout: "unspecified",
            approver: "human",
          },
        };
      }
    }

    for (const approval of this.fieldArray("approvals")) {
      if (typeof approval === "string") {
        if (
          cleanAction === approval.trim() ||
          cleanAction.includes(approval.trim())
        ) {
          return {
            required: true,
            config: {
              action: approval,
              required: true,
              approver: "human",
            },
          };
        }
      } else if (isPlainObject(approval)) {
        const action = approval["action"];
        const actionText = typeof action === "string" ? action : "";
        const required = approval["required"] ?? true;
        if (
          Boolean(required) &&
          (cleanAction === actionText ||
            (actionText.length > 0 && cleanAction.includes(actionText)) ||
            (actionText.length > 0 && actionText.includes(cleanAction)))
        ) {
          return { required: true, config: { ...approval } };
        }
      }
    }

    if (this.mode === "draft" && this.isActionIrreversible(actionName)) {
      return {
        required: true,
        config: {
          action: actionName,
          required: true,
          approver: "human",
          source: "implicit-irreversible",
        },
      };
    }

    return { required: false, config: {} };
  }

  private guardrailContractPath(): string {
    return basename(this.contractPath);
  }

  private auditGuardrailDenial(
    actionName: string,
    actionType: EffectiveActionType,
    timestamp: string,
    fieldReference: string,
    reason: string,
  ): void {
    this.appendAudit({
      timestamp,
      actionName,
      actionType,
      decision: "DENIED",
      reason,
      contractFieldReference: fieldReference,
      provisional: this.mode === "draft",
    });
  }

  private recordGuardrailAttempt(
    actionName: string,
    actionType: EffectiveActionType,
    auditTimestamp: string,
  ): Date | undefined {
    const guardrails = this.guardrails;
    if (guardrails === undefined) return undefined;

    try {
      const moment = this.clock();
      if (!(moment instanceof Date) || Number.isNaN(moment.getTime())) {
        throw new TypeError("guardrail clock must return a valid Date");
      }
      const cutoff =
        moment.getTime() - RATE_LIMIT_WINDOW_SECONDS * 1000;
      this.guardrailAttempts = this.guardrailAttempts.filter(
        (attempt) => attempt.getTime() >= cutoff,
      );
      this.guardrailAttempts.push(moment);
      return moment;
    } catch (error) {
      if (guardrails.failClosed) {
        const reason =
          `Guardrail evaluation failed for action '${actionName}' and ` +
          `fail_closed is true: ${errorText(error)}. Denying by policy.`;
        this.auditGuardrailDenial(
          actionName,
          actionType,
          auditTimestamp,
          FAIL_CLOSED_FIELD_REFERENCE,
          reason,
        );
        throw new GuardrailViolationError("fail_closed", actionName, {
          reason,
          contractPath: this.guardrailContractPath(),
        });
      }
      return undefined;
    }
  }

  private enforceGuardrails(
    actionName: string,
    actionType: EffectiveActionType,
    moment: Date,
    auditTimestamp: string,
  ): void {
    const guardrails = this.guardrails;
    if (guardrails === undefined) return;

    try {
      const rateLimit = guardrails.rateLimit;
      if (rateLimit !== undefined) {
        const cutoff =
          moment.getTime() - RATE_LIMIT_WINDOW_SECONDS * 1000;
        const recent = this.guardrailAttempts.filter(
          (attempt) => attempt.getTime() >= cutoff,
        );
        this.guardrailAttempts = recent;
        if (recent.length > rateLimit.maxCallsPerMinute) {
          const reason =
            `Guardrail 'rate_limit' denied action '${actionName}': ` +
            `max_calls_per_minute=${rateLimit.maxCallsPerMinute} exceeded ` +
            `(${recent.length} gated attempts in the trailing ` +
            `${RATE_LIMIT_WINDOW_SECONDS}s window).`;
          this.auditGuardrailDenial(
            actionName,
            actionType,
            auditTimestamp,
            RATE_LIMIT_FIELD_REFERENCE,
            reason,
          );
          throw new GuardrailViolationError("rate_limit", actionName, {
            reason,
            limit: rateLimit.maxCallsPerMinute,
            window: `${RATE_LIMIT_WINDOW_SECONDS}s`,
            contractPath: this.guardrailContractPath(),
          });
        }
      }

      const budgets = guardrails.budgets;
      if (budgets !== undefined && actionType === "side_effect") {
        const cutoff =
          moment.getTime() - budgets.windowSeconds * 1000;
        const admitted = this.guardrailAdmissions.filter(
          (admission) => admission.getTime() >= cutoff,
        );
        this.guardrailAdmissions = admitted;
        if (admitted.length >= budgets.sideEffectsPerWindow) {
          const reason =
            `Guardrail 'budgets' denied action '${actionName}': ` +
            `side_effects_per_window=${budgets.sideEffectsPerWindow} reached ` +
            `within window '${budgets.window}'.`;
          this.auditGuardrailDenial(
            actionName,
            actionType,
            auditTimestamp,
            BUDGETS_FIELD_REFERENCE,
            reason,
          );
          throw new GuardrailViolationError("budgets", actionName, {
            reason,
            limit: budgets.sideEffectsPerWindow,
            window: budgets.window,
            contractPath: this.guardrailContractPath(),
          });
        }
        this.guardrailAdmissions.push(moment);
      }
    } catch (error) {
      if (error instanceof GuardrailViolationError) throw error;
      if (guardrails.failClosed) {
        const reason =
          `Guardrail evaluation failed for action '${actionName}' and ` +
          `fail_closed is true: ${errorText(error)}. Denying by policy.`;
        this.auditGuardrailDenial(
          actionName,
          actionType,
          auditTimestamp,
          FAIL_CLOSED_FIELD_REFERENCE,
          reason,
        );
        throw new GuardrailViolationError("fail_closed", actionName, {
          reason,
          contractPath: this.guardrailContractPath(),
        });
      }
    }
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
