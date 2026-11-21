#!/usr/bin/env node
/**
 * scyvera-ts CLI.
 *
 * Exit-code constitution (mirrors the Python CLI):
 *   0  pass / allowed
 *   1  vector failure / gate denial or pending
 *   2  usage, IO, or suite-configuration error
 */

import { readFileSync } from "node:fs";
import { ContractEnforcer, type ActionType } from "./enforcer.js";
import {
  ScyveraError,
  VectorSuiteError,
} from "./errors.js";
import {
  CATEGORIES,
  PINNED_SUITE_VERSION,
  loadSuite,
  runSuite,
  type Category,
} from "./vectors.js";

const USAGE = `scyvera-ts — native TypeScript runtime for Agent Contracts

Usage:
  scyvera-ts vectors [--root <dir>] [--category <name>] [--json]
  scyvera-ts gate --contract <file> --mode <full|draft> \\
    --action <name> --action-type <permission|side_effect|read> \\
    [--approve] [--token <text>] [--audit]
  scyvera-ts --version
  scyvera-ts --help

Categories: ${CATEGORIES.join(", ")}

Exit codes: 0 pass/allowed, 1 failure/denied/pending, 2 usage/config.
`;

function readVersion(): string {
  try {
    const packageJson = JSON.parse(
      readFileSync(new URL("../../package.json", import.meta.url), "utf8"),
    ) as { version?: unknown };
    if (typeof packageJson.version === "string") return packageJson.version;
  } catch {
    // Fall through to the package version this source line belongs to.
  }
  return "0.1.1";
}

function takeOption(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  if (index < 0) return undefined;
  const value = args[index + 1];
  if (value === undefined || value.startsWith("--")) {
    throw new UsageError(`option ${name} requires a value`);
  }
  args.splice(index, 2);
  return value;
}

function takeFlag(args: string[], name: string): boolean {
  const index = args.indexOf(name);
  if (index < 0) return false;
  args.splice(index, 1);
  return true;
}

class UsageError extends Error {}

function unknownArguments(args: string[]): never {
  throw new UsageError(
    args.length > 0
      ? `unknown argument(s): ${args.join(" ")}`
      : "missing required argument(s)",
  );
}

function runVectors(args: string[]): number {
  const root = takeOption(args, "--root") ?? "vectors";
  const category = takeOption(args, "--category");
  const asJson = takeFlag(args, "--json");
  if (args.length > 0) unknownArguments(args);

  let suite;
  try {
    suite = loadSuite(root);
    if (suite.suiteVersion !== PINNED_SUITE_VERSION) {
      process.stderr.write(
        `scyvera-ts vectors: error: vectors/suite-version is ` +
          `${suite.suiteVersion}, but this runtime pins ` +
          `${PINNED_SUITE_VERSION}. Update the runtime or revert the suite ` +
          `bump; do not run a subset.\n`,
      );
      return 2;
    }
    const selectedCategory =
      category === undefined ? undefined : (category as Category);
    const result = runSuite(suite, { category: selectedCategory });

    if (asJson) {
      process.stdout.write(result.toJson());
    } else {
      const failedIds = new Set(result.failures.map((failure) => failure.id));
      const status = result.failed === 0 ? "PASS" : "FAIL";
      const lines = [
        `${status}  ${result.total} vectors (suite-version ` +
          `${result.suiteVersion}): ${result.passed} passed, ` +
          `${result.failed} failed`,
      ];
      for (const name of CATEGORIES) {
        const ids = suite.vectors
          .filter((vector) => vector.category === name)
          .map((vector) => vector.id);
        if (ids.length === 0 || (category !== undefined && category !== name)) {
          continue;
        }
        const failed = ids.filter((id) => failedIds.has(id)).length;
        lines.push(
          `      ${name}: ${ids.length - failed} passed, ${failed} failed`,
        );
      }
      for (const failure of result.failures) {
        lines.push(`      ${failure.id}: ${failure.reason}`);
      }
      process.stdout.write(`${lines.join("\n")}\n`);
    }
    return result.failed === 0 ? 0 : 1;
  } catch (error) {
    if (error instanceof VectorSuiteError) {
      process.stderr.write(`scyvera-ts vectors: error: ${error.message}\n`);
      return 2;
    }
    throw error;
  }
}

function runGate(args: string[]): number {
  const contract = takeOption(args, "--contract");
  const mode = takeOption(args, "--mode") ?? "full";
  const action = takeOption(args, "--action");
  const actionType = takeOption(args, "--action-type");
  const token = takeOption(args, "--token") ?? "";
  const approve = takeFlag(args, "--approve");
  const audit = takeFlag(args, "--audit");
  if (args.length > 0) unknownArguments(args);
  if (contract === undefined || action === undefined || actionType === undefined) {
    throw new UsageError(
      "--contract, --action, and --action-type are required",
    );
  }
  if (mode !== "full" && mode !== "draft") {
    throw new UsageError("--mode must be 'full' or 'draft'");
  }
  if (
    actionType !== "permission" &&
    actionType !== "side_effect" &&
    actionType !== "read"
  ) {
    throw new UsageError(
      "--action-type must be 'permission', 'side_effect', or 'read'",
    );
  }

  let enforcer: ContractEnforcer;
  try {
    enforcer = ContractEnforcer.load(contract, { mode });
  } catch (error) {
    if (
      error instanceof ScyveraError ||
      error instanceof Error
    ) {
      process.stderr.write(`ERROR  ${contract}\n`);
      process.stderr.write(`       ${error.message}\n`);
      return 2;
    }
    throw error;
  }

  if (approve) enforcer.approve(action, token);
  const outcome = enforcer.decide(action, actionType as ActionType);
  const detail =
    outcome.error instanceof Error
      ? outcome.error.message
      : outcome.error === undefined
        ? `Action '${action}' matched declared contract specification.`
        : String(outcome.error);
  const lastAudit = enforcer.getAuditLog().at(-1);
  const renderedDetail =
    outcome.decision === "PENDING" && lastAudit !== undefined
      ? lastAudit.reason
      : detail;
  process.stdout.write(`${outcome.decision}  ${action}\n`);
  process.stdout.write(`       ${renderedDetail}\n`);
  if (audit) {
    for (const entry of enforcer.getAuditLog()) {
      process.stdout.write(
        `       [${entry.decision}] ${entry.actionName} ` +
          `(${entry.actionType}) ${entry.reason}\n`,
      );
    }
  }
  return outcome.decision === "ALLOWED" ? 0 : 1;
}

function main(argv: string[]): number {
  const args = [...argv];
  const command = args.shift();
  if (command === undefined) {
    process.stderr.write(USAGE);
    return 2;
  }
  if (command === "--help" || command === "-h" || command === "help") {
    process.stdout.write(USAGE);
    return 0;
  }
  if (command === "--version" || command === "version") {
    process.stdout.write(`scyvera-ts ${readVersion()}\n`);
    return 0;
  }

  try {
    if (command === "vectors") return runVectors(args);
    if (command === "gate") return runGate(args);
    throw new UsageError(`unknown command '${command}'`);
  } catch (error) {
    if (error instanceof UsageError) {
      process.stderr.write(`scyvera-ts: ${error.message}\n\n${USAGE}`);
      return 2;
    }
    const name = error instanceof Error ? error.name : "Error";
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`scyvera-ts: ${name}: ${message}\n`);
    return 2;
  }
}

process.exitCode = main(process.argv.slice(2));
