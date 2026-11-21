//! CLI contract tests: exit codes, output, and the scope statement for
//! commands that remain Python-owned.
//!
//! The CLI runs in-process against in-memory buffers. That keeps the exit-code
//! contract testable without spawning a subprocess (and without importing a
//! process-spawning API into the test suite).

mod common;

use std::path::PathBuf;

use common::TempDir;

struct Run {
    code: i32,
    stdout: String,
    stderr: String,
}

fn run(args: &[&str]) -> Run {
    let mut stdout: Vec<u8> = Vec::new();
    let mut stderr: Vec<u8> = Vec::new();
    let code = scyvera_rs::cli::run(
        args.iter().map(|argument| argument.to_string()).collect(),
        &mut stdout,
        &mut stderr,
    );
    Run {
        code,
        stdout: String::from_utf8(stdout).expect("stdout is UTF-8"),
        stderr: String::from_utf8(stderr).expect("stderr is UTF-8"),
    }
}

fn vectors_root() -> String {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("vectors")
        .to_string_lossy()
        .into_owned()
}

#[test]
fn vectors_json_reports_33_of_33() {
    let output = run(&["vectors", "--root", &vectors_root(), "--json"]);
    assert_eq!(output.code, 0, "stdout: {}", output.stdout);
    assert!(
        output.stdout.starts_with("{\"failed\":0,"),
        "{}",
        output.stdout
    );
    assert!(output.stdout.contains("\"suite_version\":1"));
    assert!(output.stdout.contains("\"total\":33"));
    assert!(output.stdout.contains("\"passed\":33"));
    assert!(output.stdout.ends_with("}\n"));
}

#[test]
fn vectors_human_output_names_every_category() {
    let output = run(&["vectors", "--root", &vectors_root()]);
    assert_eq!(output.code, 0);
    assert!(output
        .stdout
        .starts_with("PASS  33 vectors (suite-version 1): 33 passed, 0 failed"));
    assert!(output
        .stdout
        .contains("contract-model: 11 passed, 0 failed"));
    assert!(output.stdout.contains("gate-decision: 13 passed, 0 failed"));
    assert!(output
        .stdout
        .contains("trace-roundtrip: 9 passed, 0 failed"));
}

#[test]
fn vectors_suite_drift_is_a_configuration_error() {
    let directory = TempDir::new("cli-drift");
    let root = directory.path.clone();
    std::fs::write(root.join("suite-version"), "suite-version: 2\n").unwrap();
    for category in ["contract-model", "gate-decision", "trace-roundtrip"] {
        std::fs::create_dir_all(root.join("v2").join(category)).unwrap();
    }
    let output = run(&["vectors", "--root", &root.to_string_lossy()]);
    assert_eq!(output.code, 2, "stderr: {}", output.stderr);
    assert!(output.stderr.contains("pins 1"), "{}", output.stderr);
    assert!(output.stderr.contains("do not run a subset"));
}

#[test]
fn validate_exit_codes_follow_the_constitution() {
    let directory = TempDir::new("cli-validate");
    let good = directory.write(
        "contract.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\n\
         permissions: []\n",
    );
    let bad = directory.write(
        "bad.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\n\
         permissions: \"*\"\n",
    );

    assert_eq!(run(&["validate", &good.to_string_lossy()]).code, 0);
    assert_eq!(run(&["validate", &bad.to_string_lossy()]).code, 1);
    assert_eq!(
        run(&[
            "validate",
            &directory.join("missing.yaml").to_string_lossy()
        ])
        .code,
        2
    );
    assert_eq!(run(&["validate"]).code, 2);
}

#[test]
fn gate_allow_and_deny_exit_codes() {
    let directory = TempDir::new("cli-gate");
    let contract = directory.write(
        "contract.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\n\
         permissions: [\"github:issues:read\"]\n",
    );
    let contract = contract.to_string_lossy().to_string();

    let allowed = run(&[
        "gate",
        "--contract",
        &contract,
        "--action",
        "github:issues:read",
        "--action-type",
        "permission",
    ]);
    assert_eq!(allowed.code, 0, "stderr: {}", allowed.stderr);
    assert!(allowed.stdout.starts_with("ALLOWED  github:issues:read"));

    let denied = run(&[
        "gate",
        "--contract",
        &contract,
        "--action",
        "github:issues:write",
        "--action-type",
        "permission",
    ]);
    assert_eq!(denied.code, 1);
    assert!(denied.stdout.starts_with("DENIED  github:issues:write"));
    assert!(denied.stdout.contains("not declared"));
}

#[test]
fn python_owned_commands_fail_loudly() {
    for command in ["lint", "check", "audit"] {
        let output = run(&[command, "contract.yaml"]);
        assert_eq!(output.code, 2, "{command}: {}", output.stderr);
        assert!(
            output
                .stderr
                .contains("not implemented in the Rust runtime"),
            "{}",
            output.stderr
        );
        assert!(output.stderr.contains("Python-owned"), "{}", output.stderr);
    }
}

#[test]
fn help_and_version_are_available() {
    let version = run(&["--version"]);
    assert_eq!(version.code, 0);
    assert_eq!(
        version.stdout,
        format!("scyvera-rs {}\n", env!("CARGO_PKG_VERSION"))
    );

    let help = run(&["--help"]);
    assert_eq!(help.code, 0);
    assert!(help.stdout.contains("scyvera-rs vectors"));
}

#[test]
fn unknown_commands_are_usage_errors() {
    let output = run(&["nonsense"]);
    assert_eq!(output.code, 2);
    assert!(output.stderr.contains("unknown command"));
}
