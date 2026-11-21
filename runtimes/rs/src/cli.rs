//! CLI argument handling and command execution.
//!
//! The logic lives in the library (not in `main.rs`) so the exit-code contract
//! can be tested in-process: tests pass buffers as `stdout`/`stderr` and assert
//! the exact output, without spawning a subprocess.
//!
//! Exit-code constitution (shared with the Python and TypeScript runtimes):
//!   0  pass / allowed
//!   1  vector failure / gate denial or pending / validation findings
//!   2  usage, IO, or suite-configuration error

use std::io::Write;
use std::path::PathBuf;

use crate::contract::{validate_file, Mode};
use crate::enforcer::{ActionType, ContractEnforcer, Decision};
use crate::errors::Error;
use crate::vectors::{
    category_counts, load_suite, run_suite, VectorRun, VectorSuite, PINNED_SUITE_VERSION,
};

pub const USAGE: &str = "\
scyvera-rs — native Rust runtime for Agent Contracts

Usage:
  scyvera-rs vectors [--root <dir>] [--category <name>] [--json]
  scyvera-rs gate --contract <file> [--mode <full|draft>] \\
      --action <name> --action-type <permission|side_effect|read> \\
      [--approve] [--token <text>] [--audit]
  scyvera-rs validate <contract.yaml>
  scyvera-rs --version
  scyvera-rs --help

Categories: contract-model, gate-decision, trace-roundtrip

Exit codes: 0 pass/allowed, 1 failure/denied/pending, 2 usage/config.

`lint`, `check`, and `audit` are Python-owned in this release: the audit rule
registry is not part of the cross-runtime surface (RFC 0005 section 6.10), and
the Rust audit binary is the deferred GE-6 lane.
";

fn write_line(out: &mut dyn Write, line: &str) {
    // Broken pipes are not a policy failure: the caller may have closed stdout.
    let _ = writeln!(out, "{line}");
}

/// Run one CLI invocation and return its exit code.
pub fn run(mut args: Vec<String>, out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    if args.is_empty() {
        let _ = write!(err, "{USAGE}");
        return 2;
    }
    let command = args.remove(0);
    match command.as_str() {
        "--help" | "-h" | "help" => {
            let _ = write!(out, "{USAGE}");
            0
        }
        "--version" | "version" => {
            write_line(out, &format!("scyvera-rs {}", crate::VERSION));
            0
        }
        "vectors" => run_vectors(args, out, err),
        "gate" => run_gate(args, out, err),
        "validate" => run_validate(args, out, err),
        "lint" | "check" | "audit" => {
            let _ = writeln!(
                err,
                "scyvera-rs: '{command}' is not implemented in the Rust runtime; it remains \
                 Python-owned (RFC 0005 section 6.10), and the Rust audit binary is the deferred \
                 GE-6 lane."
            );
            2
        }
        other => {
            let _ = writeln!(err, "scyvera-rs: unknown command '{other}'\n\n{USAGE}");
            2
        }
    }
}

fn take_option(args: &mut Vec<String>, name: &str) -> Result<Option<String>, Error> {
    let Some(index) = args.iter().position(|argument| argument == name) else {
        return Ok(None);
    };
    if index + 1 >= args.len() {
        return Err(Error::usage(format!("option {name} requires a value")));
    }
    let value = args.remove(index + 1);
    args.remove(index);
    if value.starts_with("--") {
        return Err(Error::usage(format!("option {name} requires a value")));
    }
    Ok(Some(value))
}

fn take_flag(args: &mut Vec<String>, name: &str) -> bool {
    if let Some(index) = args.iter().position(|argument| argument == name) {
        args.remove(index);
        true
    } else {
        false
    }
}

fn unknown_arguments(args: &[String]) -> Option<Error> {
    if args.is_empty() {
        None
    } else {
        Some(Error::usage(format!(
            "unknown argument(s): {}",
            args.join(" ")
        )))
    }
}

fn run_vectors(mut args: Vec<String>, out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let root = match take_option(&mut args, "--root") {
        Ok(value) => value.unwrap_or_else(|| "vectors".to_string()),
        Err(error) => return usage_error(&error, err),
    };
    let category = match take_option(&mut args, "--category") {
        Ok(value) => value,
        Err(error) => return usage_error(&error, err),
    };
    let as_json = take_flag(&mut args, "--json");
    if let Some(error) = unknown_arguments(&args) {
        return usage_error(&error, err);
    }

    let suite = match load_suite(&PathBuf::from(&root)) {
        Ok(suite) => suite,
        Err(error) => {
            let _ = writeln!(err, "scyvera-rs vectors: error: {}", error.message());
            return 2;
        }
    };

    if suite.suite_version != PINNED_SUITE_VERSION {
        let _ = writeln!(
            err,
            "scyvera-rs vectors: error: vectors/suite-version is {}, but this runtime pins {}. \
             Update the runtime or revert the suite bump; do not run a subset.",
            suite.suite_version, PINNED_SUITE_VERSION
        );
        return 2;
    }

    let result = match run_suite(&suite, category.as_deref()) {
        Ok(result) => result,
        Err(error) => {
            let _ = writeln!(err, "scyvera-rs vectors: error: {}", error.message());
            return 2;
        }
    };

    if as_json {
        let _ = write!(out, "{}", result.to_json());
    } else {
        print_human(&suite, &result, category.as_deref(), out);
    }
    if result.failed == 0 {
        0
    } else {
        1
    }
}

fn print_human(
    suite: &VectorSuite,
    result: &VectorRun,
    category: Option<&str>,
    out: &mut dyn Write,
) {
    let status = if result.failed == 0 { "PASS" } else { "FAIL" };
    write_line(
        out,
        &format!(
            "{status}  {} vectors (suite-version {}): {} passed, {} failed",
            result.total, result.suite_version, result.passed, result.failed
        ),
    );
    for (name, ids) in category_counts(suite) {
        if ids.is_empty() || category.is_some_and(|selected| selected != name) {
            continue;
        }
        let failed = ids
            .iter()
            .filter(|id| result.failures.iter().any(|failure| failure.id == **id))
            .count();
        write_line(
            out,
            &format!(
                "      {name}: {} passed, {failed} failed",
                ids.len() - failed
            ),
        );
    }
    for failure in &result.failures {
        write_line(out, &format!("      {}: {}", failure.id, failure.reason));
    }
}

fn run_gate(mut args: Vec<String>, out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    let contract = match take_option(&mut args, "--contract") {
        Ok(value) => value,
        Err(error) => return usage_error(&error, err),
    };
    let mode = match take_option(&mut args, "--mode") {
        Ok(value) => value.unwrap_or_else(|| "full".to_string()),
        Err(error) => return usage_error(&error, err),
    };
    let action = match take_option(&mut args, "--action") {
        Ok(value) => value,
        Err(error) => return usage_error(&error, err),
    };
    let action_type = match take_option(&mut args, "--action-type") {
        Ok(value) => value,
        Err(error) => return usage_error(&error, err),
    };
    let token = match take_option(&mut args, "--token") {
        Ok(value) => value.unwrap_or_default(),
        Err(error) => return usage_error(&error, err),
    };
    let approve = take_flag(&mut args, "--approve");
    let audit = take_flag(&mut args, "--audit");
    if let Some(error) = unknown_arguments(&args) {
        return usage_error(&error, err);
    }

    let (Some(contract), Some(action), Some(action_type)) = (contract, action, action_type) else {
        return usage_error(
            &Error::usage("--contract, --action, and --action-type are required"),
            err,
        );
    };
    let Some(mode) = Mode::parse(&mode) else {
        return usage_error(&Error::usage("--mode must be 'full' or 'draft'"), err);
    };
    let Some(action_type) = ActionType::parse(&action_type) else {
        return usage_error(
            &Error::usage("--action-type must be 'permission', 'side_effect', or 'read'"),
            err,
        );
    };

    let mut enforcer = match ContractEnforcer::load(&PathBuf::from(&contract), mode) {
        Ok(enforcer) => enforcer,
        Err(error) => {
            write_line(err, &format!("ERROR  {contract}"));
            write_line(err, &format!("       {}", error.message()));
            return 2;
        }
    };

    if approve {
        enforcer.approve(&action, &token);
    }
    let outcome = enforcer.decide(&action, action_type);
    let detail = match &outcome.error {
        Some(error) => error.message().to_string(),
        None => format!("Action '{action}' matched declared contract specification."),
    };
    let rendered = if outcome.decision == Decision::Pending {
        enforcer
            .audit_log()
            .last()
            .map(|entry| entry.reason.clone())
            .unwrap_or(detail)
    } else {
        detail
    };
    write_line(out, &format!("{}  {}", outcome.decision.as_str(), action));
    write_line(out, &format!("       {rendered}"));
    if audit {
        for entry in enforcer.audit_log() {
            write_line(
                out,
                &format!(
                    "       [{}] {} ({}) {}",
                    entry.decision.as_str(),
                    entry.action_name,
                    entry.action_type,
                    entry.reason
                ),
            );
        }
    }
    if outcome.decision == Decision::Allowed {
        0
    } else {
        1
    }
}

fn run_validate(mut args: Vec<String>, out: &mut dyn Write, err: &mut dyn Write) -> i32 {
    if args.len() != 1 {
        return usage_error(
            &Error::usage("validate requires exactly one contract path"),
            err,
        );
    }
    let path = PathBuf::from(args.remove(0));
    match validate_file(&path) {
        Ok(()) => {
            write_line(out, &format!("PASS  {}", path.display()));
            0
        }
        Err(error) => {
            write_line(err, &format!("FAIL  {}", path.display()));
            write_line(err, &format!("       {}", error.message()));
            for issue in error.issues() {
                if issue.path.is_empty() {
                    write_line(err, &format!("       {}", issue.message));
                } else {
                    write_line(err, &format!("       {}: {}", issue.path, issue.message));
                }
            }
            if error.issues().is_empty() {
                2
            } else {
                1
            }
        }
    }
}

fn usage_error(error: &Error, err: &mut dyn Write) -> i32 {
    let _ = writeln!(err, "scyvera-rs: {}\n\n{USAGE}", error.message());
    2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn option_parsing_removes_consumed_arguments() {
        let mut args = vec![
            "--root".to_string(),
            "vectors".to_string(),
            "--json".to_string(),
        ];
        assert_eq!(
            take_option(&mut args, "--root").unwrap().as_deref(),
            Some("vectors")
        );
        assert!(take_flag(&mut args, "--json"));
        assert!(args.is_empty());
    }

    #[test]
    fn missing_option_values_are_usage_errors() {
        let mut args = vec!["--root".to_string()];
        assert!(take_option(&mut args, "--root").is_err());
    }

    #[test]
    fn categories_are_the_closed_three() {
        assert_eq!(
            crate::vectors::CATEGORIES,
            ["contract-model", "gate-decision", "trace-roundtrip"]
        );
    }
}
