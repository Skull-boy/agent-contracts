import { cpSync, existsSync } from "node:fs";

// tsc does not emit JSON assets. The contract schemas are copied verbatim so
// the published package carries the same bytes as src/scyvera/schemas/.
if (!existsSync("src/schemas")) {
  throw new Error("src/schemas is missing");
}
cpSync("src/schemas", "dist/src/schemas", { recursive: true });
