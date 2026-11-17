import { mkdtempSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { stringify as stringifyYaml } from "yaml";

/** Create a temp directory whose own path is already canonical (T14-safe). */
export function tempDir(prefix = "scyvera-ts-test-"): string {
  return mkdtempSync(join(realpathSync(tmpdir()), prefix));
}

export function writeContract(
  directory: string,
  contract: Record<string, unknown>,
  filename = "contract.yaml",
): string {
  const path = join(directory, filename);
  writeFileSync(
    path,
    stringifyYaml(contract, { sortMapEntries: true, lineWidth: 0 }),
    "utf8",
  );
  return path;
}

export function baseContract(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    version: 1.1,
    system: { name: "test-agent" },
    lifecycle: { mode: "request-response", initiation: "human-only" },
    permissions: ["github:issues:read"],
    side_effects: [],
    approvals: [],
    ...overrides,
  };
}
