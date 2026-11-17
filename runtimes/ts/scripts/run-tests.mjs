import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";

// Node's test runner does not recursively expand a directory on every
// supported Node version (and Windows shells do not expand globs), so discover
// the compiled test files explicitly.
const files = readdirSync("dist/test")
  .filter((name) => name.endsWith(".test.js"))
  .sort()
  .map((name) => `dist/test/${name}`);

if (files.length === 0) {
  console.error("no compiled tests found under dist/test");
  process.exit(1);
}

const result = spawnSync(process.execPath, ["--test", ...files], {
  stdio: "inherit",
});
process.exit(result.status ?? 1);
