/**
 * Native error types for scyvera-ts.
 *
 * The canonical cross-runtime codes are the RFC 0005 §6.7 strings. A native
 * error keeps its own class (so callers get precise semantics) and is mapped to
 * a canonical code at the vector-runner boundary. This mirrors the Python
 * reference: the class is native, the code is the shared contract.
 */

export type CanonicalErrorCode =
  | "ContractViolationError"
  | "ApprovalPendingError"
  | "ProvisionalContractError"
  | "ContractValidationError"
  | "TraceError"
  | "GuardrailViolationError";

export interface ValidationIssue {
  /** RFC 6901 JSON Pointer, e.g. `/permissions/0`. */
  readonly path: string;
  readonly message: string;
}

export class ScyveraError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class ContractFileNameError extends ScyveraError {
  readonly path: string;

  constructor(path: string) {
    super(
      `Found contract.yml — rename to contract.yaml ` +
        `(see WORKFLOW-CONTRACT-SPEC.md): ${path}`,
    );
    this.path = path;
  }
}

export class ContractFileNotFoundError extends ScyveraError {
  readonly path: string;

  constructor(path: string) {
    super(`Contract file not found at: ${path}`);
    this.path = path;
  }
}

export class ContractValidationError extends ScyveraError {
  readonly issues: readonly ValidationIssue[];

  constructor(message: string, issues: readonly ValidationIssue[] = []) {
    super(message);
    this.issues = [...issues];
  }
}

export class ContractViolationError extends ScyveraError {
  readonly actionName: string;
  readonly contractPath: string;
  readonly suggestion: string;
  readonly reason: string | undefined;

  constructor(
    actionName: string,
    contractPath: string,
    suggestion: string,
    reason?: string,
  ) {
    super(
      reason ??
        `Contract violation: Action '${actionName}' is not declared in ` +
          `'${contractPath}'. Suggestion: Declare this action in the ` +
          `'${suggestion}' field of your contract.`,
    );
    this.actionName = actionName;
    this.contractPath = contractPath;
    this.suggestion = suggestion;
    this.reason = reason;
  }
}

export class ProvisionalContractError extends ContractViolationError {
  constructor(contractPath: string, reason?: string) {
    super(
      "load",
      contractPath,
      'Run the human promotion ritual (`scyvera promote ...` or ' +
        '`scyvera.reseal.reseal()` with a PromotionIntent), or load the draft ' +
        'with mode="draft".',
      reason ??
        `Contract '${contractPath}' is provisional (\`provisional: true\`) ` +
          `and cannot be loaded in full mode. Promote it first through the ` +
          `human promotion ritual (\`scyvera.reseal.reseal()\` with a ` +
          `PromotionIntent); the promoted contract MUST omit \`provisional\`.`,
    );
  }
}

export class ContractTamperError extends ScyveraError {}

export class ContractVersionError extends ScyveraError {}

export class GuardrailViolationError extends ContractViolationError {
  readonly guardrail: "rate_limit" | "budgets" | "fail_closed";
  readonly limit: number | undefined;
  readonly window: string | undefined;

  constructor(
    guardrail: "rate_limit" | "budgets" | "fail_closed",
    actionName: string,
    options: {
      reason: string;
      limit?: number;
      window?: string;
      contractPath?: string;
    },
  ) {
    super(
      actionName,
      options.contractPath ?? "contract",
      `Adjust 'guardrails.${guardrail}' in contract.yaml, wait for the ` +
        `window to pass, or remove the guardrail block.`,
      options.reason,
    );
    this.guardrail = guardrail;
    this.limit = options.limit;
    this.window = options.window;
  }
}

export class ApprovalPendingError extends ScyveraError {
  readonly actionName: string;
  readonly approvalConfig: Record<string, unknown>;

  constructor(actionName: string, approvalConfig: Record<string, unknown>) {
    super(
      `Action '${actionName}' requires human approval before execution. ` +
        `Approval config: ${JSON.stringify(approvalConfig)}`,
    );
    this.actionName = actionName;
    this.approvalConfig = approvalConfig;
  }
}

export class TraceError extends ScyveraError {}

export class VectorSuiteError extends ScyveraError {}

export class GuardrailConfigError extends ScyveraError {}

/**
 * Map a native error to the RFC 0005 §6.7 canonical code.
 *
 * `ContractTamperError` has no dedicated §6.7 code. Integrity denials map to
 * `ContractViolationError`; the vector's `message_contains: "tampered"` still
 * distinguishes the case (see vectors/CHANGELOG.md).
 */
export function canonicalErrorCode(error: unknown): string {
  if (error instanceof ProvisionalContractError) {
    return "ProvisionalContractError";
  }
  if (error instanceof ApprovalPendingError) {
    return "ApprovalPendingError";
  }
  if (error instanceof GuardrailViolationError) {
    return "GuardrailViolationError";
  }
  if (error instanceof ContractValidationError) {
    return "ContractValidationError";
  }
  if (error instanceof TraceError) {
    return "TraceError";
  }
  if (error instanceof ContractTamperError) {
    return "ContractViolationError";
  }
  if (error instanceof ContractViolationError) {
    return "ContractViolationError";
  }
  if (error instanceof Error) {
    return error.name;
  }
  return "Error";
}
