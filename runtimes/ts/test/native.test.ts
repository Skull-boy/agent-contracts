import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

function sourceFiles(directory = "src"): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(path));
    } else if (entry.name.endsWith(".ts")) {
      files.push(path);
    }
  }
  return files;
}

test("the runtime is native: no Python, child process, or WASM bridge", () => {
  const forbidden = [
    /node:child_process/,
    /\bchild_process\b/,
    /\bpyodide\b/i,
    /WebAssembly/,
    /\.wasm\b/,
    /\bspawnSync\(/,
    /\bexecFileSync\(/,
    /\bexecSync\(/,
    /\bpython3\b/,
    /"python"/,
  ];
  for (const file of sourceFiles()) {
    const text = readFileSync(file, "utf8");
    for (const pattern of forbidden) {
      assert.equal(
        pattern.test(text),
        false,
        `${file} matches forbidden native-only pattern ${pattern}`,
      );
    }
  }
});

test("the only runtime dependency is the pinned YAML parser", () => {
  const manifest = JSON.parse(readFileSync("package.json", "utf8")) as {
    name: string;
    version: string;
    type: string;
    engines: { node: string };
    dependencies: Record<string, string>;
    devDependencies: Record<string, string>;
  };
  assert.equal(manifest.name, "scyvera-ts");
  assert.equal(manifest.version, "0.1.0");
  assert.equal(manifest.type, "module");
  assert.equal(manifest.engines.node, ">=20");
  assert.deepEqual(Object.keys(manifest.dependencies), ["yaml"]);
  assert.equal(manifest.dependencies["yaml"], "2.9.1");
  assert.equal("scyvera" in manifest.dependencies, false);
  assert.deepEqual(
    Object.keys(manifest.devDependencies).sort(),
    ["@types/node", "typescript"],
  );
});

test("the README cross-links RFC 0005 and states the honest scope", () => {
  const readme = readFileSync("README.md", "utf8");
  assert.match(readme, /0005-provisional-contracts\.md/);
  assert.match(readme, /Not implemented/);
  assert.match(readme, /vectors\//);
});

test("the CI workflow pins the suite version as a checked constant", () => {
  const workflow = readFileSync(
    join("..", "..", ".github", "workflows", "scyvera-ts.yml"),
    "utf8",
  );
  assert.match(workflow, /PINNED_SUITE_VERSION: "1"/);
  assert.match(workflow, /suite-version/);
  assert.match(workflow, /node-version: \[20, 22\]/);
});
