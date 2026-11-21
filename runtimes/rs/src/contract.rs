//! Contract loading, security constraints, and identity pinning.
//!
//! This is the native port of the load path in `src/scyvera/enforcer.py` and
//! `runtimes/ts/src/contract.ts`: v1/v1.1/v1.2 YAML, the RFC 0005 §4.1
//! load-mode gate, T14 symlink-escape refusal, wildcard refusal, fail-closed
//! schema validation, and a pinned SHA-256 identity used by the gate's
//! post-load integrity check.
//!
//! The registry and re-seal machinery are deliberately absent: they remain
//! Python-owned per RFC 0005 §6.10.

use std::path::{Path, PathBuf};

use crate::errors::Error;
use crate::guardrails::{parse_guardrails, Guardrails};
use crate::json::Json;
use crate::schema::{
    apply_lifecycle_defaults, detect_version, matches_service_scope, validate_contract_object,
};
use crate::sha256;
use crate::yaml;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Full,
    Draft,
}

impl Mode {
    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Full => "full",
            Mode::Draft => "draft",
        }
    }

    pub fn parse(value: &str) -> Option<Mode> {
        match value {
            "full" => Some(Mode::Full),
            "draft" => Some(Mode::Draft),
            _ => None,
        }
    }
}

#[derive(Clone, Debug)]
pub struct LoadedContract {
    /// Canonical filesystem path pinned at load time.
    pub contract_path: PathBuf,
    /// Path the caller asked for (used to detect a post-load symlink swap).
    pub requested_path: PathBuf,
    /// Parsed contract with lifecycle defaults applied.
    pub contract: Json,
    /// SHA-256 of the exact bytes read at load time.
    pub integrity_hash: String,
    pub mode: Mode,
    pub resolved_symlink: bool,
    pub guardrails: Option<Guardrails>,
}

impl LoadedContract {
    pub fn is_provisional(&self) -> bool {
        self.contract.get("provisional") == Some(&Json::Bool(true))
    }

    /// File name used in user-facing gate messages (`contract.yaml`).
    pub fn display_name(&self) -> String {
        self.contract_path
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_else(|| self.contract_path.display().to_string())
    }
}

const WILDCARDS: [&str; 3] = ["*", "all", "any"];

fn is_wildcard(text: &str) -> bool {
    WILDCARDS.contains(&text.trim())
}

/// Windows `canonicalize` returns a verbatim path (`\\?\C:\...`). Stripping the
/// prefix keeps identity hashes, messages, and `--audit` output readable and
/// keeps `requested == canonical` for ordinary files.
pub(crate) fn strip_verbatim(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{rest}"));
    }
    if let Some(rest) = text.strip_prefix(r"\\?\") {
        return PathBuf::from(rest.to_string());
    }
    path
}

fn absolute(path: &Path) -> Result<PathBuf, Error> {
    std::path::absolute(path).map_err(|error| {
        Error::io(format!(
            "cannot resolve contract path '{}': {error}",
            path.display()
        ))
    })
}

fn validate_version_invariants(contract: &Json, path: &Path) -> Result<(), Error> {
    let explicit = contract.get("contract_version");
    if explicit == Some(&Json::String("1.1".to_string())) && contract.get("lifecycle").is_none() {
        return Err(Error::validation(format!(
            "Contract at '{}' explicitly declares contract_version: '1.1' but is missing the \
             required 'lifecycle' field. Declare a 'lifecycle' block (e.g. {{mode: \
             request-response}}).",
            path.display()
        )));
    }
    if detect_version(contract).is_none() {
        return Err(Error::validation(format!(
            "Unsupported or unrecognized contract version in '{}'. Expected '1', '1.1', or '1.2'.",
            path.display()
        )));
    }
    Ok(())
}

fn validate_security_constraints(contract: &Json, path: &Path) -> Result<(), Error> {
    if let Some(Json::Array(permissions)) = contract.get("permissions") {
        for permission in permissions {
            match permission {
                Json::String(text) => {
                    let cleaned = text.trim();
                    if is_wildcard(cleaned) {
                        return Err(Error::validation(format!(
                            "Wildcard permission '{cleaned}' is prohibited in '{}' (Threat T7).",
                            path.display()
                        )));
                    }
                    if !matches_service_scope(cleaned) {
                        return Err(Error::validation(format!(
                            "Permission string '{cleaned}' does not match required service:scope \
                             pattern (e.g. 'github:issues:write') in '{}'.",
                            path.display()
                        )));
                    }
                }
                Json::Object(entries) => {
                    for (key, value) in entries {
                        let value_text = match value {
                            Json::String(text) => text.clone(),
                            other => crate::json::compact(other),
                        };
                        if is_wildcard(key) || is_wildcard(&value_text) {
                            return Err(Error::validation(format!(
                                "Wildcard entry '{key}: {value_text}' in permissions is \
                                 prohibited in '{}' (Threat T7).",
                                path.display()
                            )));
                        }
                        if let Json::Array(actions) = value {
                            for action in actions {
                                let action_text = match action {
                                    Json::String(text) => text.clone(),
                                    other => crate::json::compact(other),
                                };
                                if is_wildcard(&action_text) {
                                    return Err(Error::validation(format!(
                                        "Wildcard action '{action_text}' in permission '{key}' is \
                                         prohibited in '{}' (Threat T7).",
                                        path.display()
                                    )));
                                }
                            }
                        }
                    }
                }
                _ => {}
            }
        }
    }

    if let Some(Json::Array(side_effects)) = contract.get("side_effects") {
        for side_effect in side_effects {
            if let Json::String(text) = side_effect {
                if is_wildcard(text) {
                    return Err(Error::validation(format!(
                        "Wildcard side effect '{text}' is prohibited in '{}' (Threat T7).",
                        path.display()
                    )));
                }
            }
        }
    }

    Ok(())
}

/// Load and validate a file contract.
pub fn load_contract_file(raw_path: &Path, mode: Mode) -> Result<LoadedContract, Error> {
    let lexical = absolute(raw_path)?;
    if !lexical.exists() {
        return Err(Error::io(format!(
            "Contract file not found at: {}",
            lexical.display()
        )));
    }

    let canonical = strip_verbatim(std::fs::canonicalize(&lexical).map_err(|error| {
        Error::io(format!(
            "cannot canonicalize contract '{}': {error}",
            lexical.display()
        ))
    })?);

    let addressed_dir = lexical
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let addressed_canonical =
        strip_verbatim(std::fs::canonicalize(&addressed_dir).unwrap_or(addressed_dir));

    // T14: a contract that resolves outside the directory it was addressed in
    // is refused even when the bytes are readable.
    if !canonical.starts_with(&addressed_canonical) {
        return Err(Error::ContractViolation {
            message: format!(
                "Refusing to load contract '{}': it resolves to '{}', which is outside the \
                 addressed directory '{}' (T14 symlink escape).",
                lexical.display(),
                canonical.display(),
                addressed_canonical.display()
            ),
        });
    }
    let resolved_symlink = canonical != lexical;

    let bytes = std::fs::read(&canonical).map_err(|error| {
        Error::io(format!(
            "cannot read contract '{}': {error}",
            canonical.display()
        ))
    })?;
    let integrity_hash = sha256::hex_digest(&bytes);

    let text = std::str::from_utf8(&bytes).map_err(|_| {
        Error::validation(format!(
            "Contract file '{}' is not valid UTF-8",
            canonical.display()
        ))
    })?;

    // The YAML reader is also used directly (not only through the file helper)
    // so a `.yml` suffix is rejected before the file is parsed.
    if canonical.extension().and_then(|value| value.to_str()) == Some("yml") {
        return Err(Error::validation(format!(
            "Found contract.yml — rename to contract.yaml (see WORKFLOW-CONTRACT-SPEC.md): {}",
            canonical.display()
        )));
    }
    let raw_data = yaml::parse(text).map_err(|error| {
        Error::validation(format!(
            "Contract file '{}' is not valid YAML: {error}",
            canonical.display()
        ))
    })?;

    if !raw_data.is_object() {
        return Err(Error::validation_with(
            format!(
                "Contract file '{}' must contain a YAML mapping, got {}.",
                canonical.display(),
                raw_data.kind()
            ),
            Vec::new(),
        ));
    }

    validate_version_invariants(&raw_data, &canonical)?;
    validate_security_constraints(&raw_data, &canonical)?;
    validate_contract_object(&raw_data)?;

    let guardrails = parse_guardrails(raw_data.get("guardrails")).map_err(|error| {
        Error::validation(format!(
            "Contract validation failed for '{}': invalid guardrails block: {}",
            canonical.display(),
            error.message()
        ))
    })?;

    let file_is_provisional = raw_data.get("provisional") == Some(&Json::Bool(true));
    if mode == Mode::Draft && !file_is_provisional {
        return Err(Error::validation(format!(
            "Contract '{}' is not provisional; draft mode (mode=\"draft\") is only for contracts \
             with `provisional: true`.",
            canonical.display()
        )));
    }
    if mode == Mode::Full && file_is_provisional {
        return Err(Error::provisional(&canonical.display().to_string()));
    }

    Ok(LoadedContract {
        contract_path: canonical,
        requested_path: lexical,
        contract: apply_lifecycle_defaults(&raw_data),
        integrity_hash,
        mode,
        resolved_symlink,
        guardrails,
    })
}

/// Validate a contract file without applying load-mode rules. Used by
/// `scyvera-rs validate` and by `contract-model` vectors with operation
/// `validate`.
pub fn validate_file(path: &Path) -> Result<(), Error> {
    crate::schema::validate_contract_file(path)
}

/// Field arrays used by the gate; a missing or non-array field is empty.
pub fn field_array<'a>(contract: &'a Json, name: &str) -> &'a [Json] {
    match contract.get(name) {
        Some(Json::Array(items)) => items,
        _ => &[],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wildcard_permissions_are_refused() {
        let contract = yaml::parse(
            "version: 1.1\nlifecycle:\n  mode: request-response\npermissions: [\"*\"]\n",
        )
        .unwrap();
        let error =
            validate_security_constraints(&contract, Path::new("contract.yaml")).unwrap_err();
        assert!(error.message().contains("Wildcard permission"));
    }

    #[test]
    fn service_scope_is_enforced_on_load_constraints() {
        let contract = yaml::parse(
            "version: 1.1\nlifecycle:\n  mode: request-response\npermissions: [\"not-a-scope\"]\n",
        )
        .unwrap();
        let error =
            validate_security_constraints(&contract, Path::new("contract.yaml")).unwrap_err();
        assert!(error.message().contains("service:scope"));
    }

    #[test]
    fn strip_verbatim_handles_windows_prefixes() {
        assert_eq!(
            strip_verbatim(PathBuf::from(r"\\?\C:\work\contract.yaml")),
            PathBuf::from(r"C:\work\contract.yaml")
        );
    }
}
