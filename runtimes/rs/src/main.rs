//! `scyvera-rs` binary entry point.
//!
//! All behavior lives in [`scyvera_rs::cli::run`] so it can be tested in-process.
//! This wrapper only supplies the process's arguments and streams, and maps the
//! returned exit code.

use std::io::Write;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let stdout = std::io::stdout();
    let stderr = std::io::stderr();
    let mut out = stdout.lock();
    let mut err = stderr.lock();
    let code = scyvera_rs::cli::run(args, &mut out, &mut err);
    let _ = out.flush();
    let _ = err.flush();
    ExitCode::from(code.clamp(0, 255) as u8)
}
