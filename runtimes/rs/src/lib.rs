//! `scyvera-rs` — the native Rust runtime for Agent Contracts.
//!
//! Scope is the RFC 0005 cross-runtime surface: the contract model (v1, v1.1,
//! v1.2), the default-deny gate with its draft-mode rules, the RFC 0003 §C4
//! trace with the additive `provisional` field, and the shared conformance
//! vector runner.
//!
//! Out of scope by design: the audit rule registry, policy packs, the registry
//! and re-seal machinery, and promotion orchestration. Those stay Python-owned
//! (RFC 0005 §6.10); the Rust audit binary is the separate GE-6 lane.
//!
//! ## Guarantees
//!
//! - **No Python at runtime.** Nothing here shells out, imports, or wraps the
//!   reference implementation.
//! - **One direct dependency.** `yaml-rust2` (with `default-features = false`).
//!   JSON, SHA-256, ISO-8601 formatting, and the JSON Schema subset used by the
//!   contract schemas are implemented here.
//! - **Fail closed.** Unknown schema keywords, unsupported patterns, unknown
//!   trace fields, unknown vector envelope keys, non-canonical vector files,
//!   duplicate JSON keys, and symlinked suite paths are refused rather than
//!   ignored.

pub mod cli;
pub mod contract;
pub mod enforcer;
pub mod errors;
pub mod guardrails;
pub mod json;
pub mod schema;
pub mod sha256;
pub mod time;
pub mod trace;
pub mod vectors;
pub mod yaml;

pub use contract::{load_contract_file, LoadedContract, Mode};
pub use enforcer::{ActionType, AuditEntry, ContractEnforcer, Decision, Outcome};
pub use errors::{Error, ValidationIssue};
pub use json::Json;
pub use trace::{TraceEntry, TraceLog};

/// Package version, printed by `scyvera-rs --version`.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
