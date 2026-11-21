//! Native error type and the RFC 0005 §6.7 canonical-code mapping.
//!
//! Cross-runtime vectors cannot compare host-language type names, so every
//! native error maps to one canonical code at the runner boundary. The mapping
//! is part of the runtime's conformance, not an excuse to skip a case:
//!
//! | Variant | Canonical code |
//! |---|---|
//! | [`Error::ContractViolation`] (undeclared action) | `ContractViolationError` |
//! | [`Error::Tamper`] (post-load integrity failure) | `ContractViolationError` |
//! | [`Error::Provisional`] | `ProvisionalContractError` |
//! | [`Error::ContractValidation`] | `ContractValidationError` |
//! | [`Error::ApprovalPending`] | `ApprovalPendingError` |
//! | [`Error::GuardrailViolation`] | `GuardrailViolationError` |
//! | [`Error::Trace`] | `TraceError` |
//!
//! Integrity denials have no dedicated §6.7 code. `vectors/CHANGELOG.md` pins
//! the agreed mapping: `ContractViolationError` plus `message_contains:
//! "tampered"`, which is why [`Error::Tamper`] maps as it does.

use std::fmt;

use crate::json::{compact, Json};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidationIssue {
    /// RFC 6901 JSON Pointer for the failing location (`""` for the root).
    pub path: String,
    pub message: String,
}

impl ValidationIssue {
    pub fn new(path: impl Into<String>, message: impl Into<String>) -> Self {
        ValidationIssue {
            path: path.into(),
            message: message.into(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    ContractValidation {
        message: String,
        issues: Vec<ValidationIssue>,
    },
    ContractViolation {
        message: String,
    },
    Provisional {
        message: String,
    },
    ApprovalPending {
        message: String,
        action: String,
        config: Json,
    },
    GuardrailViolation {
        message: String,
    },
    Trace {
        message: String,
    },
    VectorSuite {
        message: String,
    },
    Usage {
        message: String,
    },
    Io {
        message: String,
    },
    Tamper {
        message: String,
    },
}

impl Error {
    pub fn validation(message: impl Into<String>) -> Self {
        Error::ContractValidation {
            message: message.into(),
            issues: Vec::new(),
        }
    }

    pub fn validation_with(message: impl Into<String>, issues: Vec<ValidationIssue>) -> Self {
        Error::ContractValidation {
            message: message.into(),
            issues,
        }
    }

    /// The default-deny path: an action the contract does not declare.
    pub fn undeclared(action: &str, contract_path: &str, field: &str) -> Self {
        Error::ContractViolation {
            message: format!(
                "Contract violation: Action '{action}' is not declared in '{contract_path}'. \
                 Suggestion: Declare this action in the '{field}' field of your contract."
            ),
        }
    }

    /// Full-mode load of a provisional contract (RFC 0005 §4.1).
    pub fn provisional(contract_path: &str) -> Self {
        Error::Provisional {
            message: format!(
                "Contract '{contract_path}' is provisional (`provisional: true`) and cannot be \
                 loaded in full mode. Promote it first through the human promotion ritual, or \
                 load the draft with mode=\"draft\". The promoted contract MUST omit \
                 `provisional`."
            ),
        }
    }

    pub fn approval_pending(action: &str, config: &Json) -> Self {
        Error::ApprovalPending {
            message: format!(
                "Action '{action}' requires human approval before execution. Approval config: {}",
                compact(config)
            ),
            action: action.to_string(),
            config: config.clone(),
        }
    }

    pub fn guardrail(message: impl Into<String>) -> Self {
        Error::GuardrailViolation {
            message: message.into(),
        }
    }

    pub fn trace(message: impl Into<String>) -> Self {
        Error::Trace {
            message: message.into(),
        }
    }

    pub fn vector_suite(message: impl Into<String>) -> Self {
        Error::VectorSuite {
            message: message.into(),
        }
    }

    pub fn usage(message: impl Into<String>) -> Self {
        Error::Usage {
            message: message.into(),
        }
    }

    pub fn io(message: impl Into<String>) -> Self {
        Error::Io {
            message: message.into(),
        }
    }

    pub fn tamper(message: impl Into<String>) -> Self {
        Error::Tamper {
            message: message.into(),
        }
    }

    /// RFC 0005 §6.7 canonical code for this error.
    pub fn code(&self) -> &'static str {
        match self {
            Error::ContractValidation { .. } => "ContractValidationError",
            Error::ContractViolation { .. } => "ContractViolationError",
            Error::Tamper { .. } => "ContractViolationError",
            Error::Provisional { .. } => "ProvisionalContractError",
            Error::ApprovalPending { .. } => "ApprovalPendingError",
            Error::GuardrailViolation { .. } => "GuardrailViolationError",
            Error::Trace { .. } => "TraceError",
            Error::VectorSuite { .. } => "VectorSuiteError",
            Error::Usage { .. } => "UsageError",
            Error::Io { .. } => "IoError",
        }
    }

    pub fn message(&self) -> &str {
        match self {
            Error::ContractValidation { message, .. }
            | Error::ContractViolation { message }
            | Error::Provisional { message }
            | Error::ApprovalPending { message, .. }
            | Error::GuardrailViolation { message }
            | Error::Trace { message }
            | Error::VectorSuite { message }
            | Error::Usage { message }
            | Error::Io { message }
            | Error::Tamper { message } => message,
        }
    }

    pub fn issues(&self) -> &[ValidationIssue] {
        match self {
            Error::ContractValidation { issues, .. } => issues,
            _ => &[],
        }
    }

    /// Exit code for the CLI constitution: `2` for usage/configuration/IO,
    /// `1` for a policy denial, `0` never (success is not an error).
    pub fn exit_code(&self) -> i32 {
        match self {
            Error::Usage { .. } | Error::Io { .. } | Error::VectorSuite { .. } => 2,
            _ => 1,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message())
    }
}

impl std::error::Error for Error {}

#[cfg(test)]
mod tests {
    use super::Error;

    #[test]
    fn maps_canonical_codes() {
        assert_eq!(
            Error::undeclared("x", "contract.yaml", "permissions").code(),
            "ContractViolationError"
        );
        assert_eq!(
            Error::tamper("hash mismatch").code(),
            "ContractViolationError"
        );
        assert_eq!(
            Error::provisional("contract.yaml").code(),
            "ProvisionalContractError"
        );
        assert_eq!(Error::validation("bad").code(), "ContractValidationError");
        assert_eq!(Error::trace("bad").code(), "TraceError");
    }

    #[test]
    fn provisional_message_mentions_promotion() {
        assert!(Error::provisional("contract.yaml")
            .message()
            .contains("promotion"));
    }
}
