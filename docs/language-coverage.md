# Language coverage

Audit language support is **pattern-level, review-grade coverage — not AST or conformance-grade**.
It is designed to make the first `scyvera audit .` on a real repository say
something true about the boundaries it can see, not to certify a language.

## What the scanner does

Every rule is a pure `(path, text, filename)` function over decoded UTF-8
text (a UTF-8 BOM is stripped before matching). Coverage below is a set of
documented line patterns applied to the file's own suffix. It does not parse,
type-check, resolve aliases, or build call/data-flow graphs. Generated code,
reflection, wrappers around wrappers, and dynamically constructed commands can
be missed. Tier 1 adapters own syntax- and graph-aware conformance checks.

## Matrix

| Language | Example client patterns | What is caught | What is NOT caught |
|---|---|---|---|
| Go (`.go`) | `"net/http"`, `http.Get/Post/NewRequest`, `"os/exec"`, `exec.Command` | standard HTTP and process launches on the matching line | interfaces, wrappers, aliased imports, reflection |
| Java / Kotlin (`.java/.kt/.kts`) | `java.net.URL`, `HttpURLConnection`, `java.net.http`, `HttpClient.new*`, `Runtime.exec`, `ProcessBuilder` | legacy and modern HTTP/process clients | Spring/OkHttp helpers, injected clients, reflection |
| Rust (`.rs`) | `std::process::Command`, `reqwest`, `ureq`, `isahc` | direct crate paths/imports and process commands | macro-generated clients, trait objects, indirect calls |
| C / C++ (`.c/.h/.cc/.cpp/.hpp`) | `system(`, `popen(`, `exec*`, `WinHttp*`, `WinExec` | process launch and Windows network APIs | inlined syscalls, function pointers, library abstractions |
| C# (`.cs`) | `HttpClient`, `Process.Start`, `WebClient` | direct client/process construction | DI-injected clients, `HttpClientFactory`, IL generation |
| PHP (`.php`) | `curl_init`, `file_get_contents("http...")`, `exec(` | cURL, URL reads, shell wrappers | framework HTTP clients, stream contexts assembled at runtime |
| JavaScript / TypeScript (`.js/.jsx/.ts/.tsx/.mjs/.cjs`) | `fetch`, `axios`, `got`, `node:https`, `FetchEvent`, `createObject` | common browser/Node clients | bundled/minified code, dynamic `import()`, framework wrappers |
| Python + agent/ML SDKs (`.py/.pyi`) | `requests`, `httpx`, `urllib`, `openai`, `wandb`, `huggingface_hub`, ... | imports and combined imports on one line | dynamic `__import__`, SDK helpers imported elsewhere |
| Shell / workflows | `curl ... \| sh`, `rm -rf`, destructive git | existing executable-line rules, including wrapper payloads | obfuscated strings, encoded commands |

## Wrapper-aware commands

`system("...")`, `os.system("...")`, `subprocess.*("...")`, `Runtime.exec`,
`ProcessBuilder`, `exec.Command`, `child_process.exec`, and `Process.Start`
have their quoted payload fed to the existing piped-install, recursive-delete,
and destructive-git checks. This is string extraction, not shell emulation: a
command split across variables or concatenated fragments is not reconstructed.

## Source credentials

AU-SECRET-001 recognizes `name = "..."`, `name := "..."`, `name: "..."`,
`String TOKEN = "..."`, `let key = "..."`, `var apiKey = "..."`, and
credential-like callees such as `setApiKey("...")`. The value floor is shared
with AU-ENV-002: at least 16 characters, no whitespace, entropy >= 3.0, and a
placeholder allowlist. Provider prefixes (`sk-`, `ghp_`, `wb_`, `hf_`, `AKIA`,
`pat_`) are recognized even when the variable name is not credential-like.

## Deliberate boundaries

- No AST, no type inference, no data-flow analysis.
- No framework graphs or route analysis; Tier 1 adapters handle those.
- No exhaustive per-language conformance claim: absence of a finding is not
  evidence of absence.
- Fixtures under `tests/fixtures/` remain visible in reports but are
  quarantined from score, band, and scored stats.
