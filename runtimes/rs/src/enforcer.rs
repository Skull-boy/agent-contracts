//! Native default-deny gate (RFC 0005 §4.2).
//!
//! Pipeline: integrity → declaration → approval → guardrails → allowed. Draft
//! mode changes exactly one decision: an irreversible action carries an
//! implicit human-approval gate even when the draft declares no approvals.
//! Every other check is unchanged, matching the Python reference.

use std::path::Path;

use crate::contract::{field_array, load_contract_file, LoadedContract, Mode};
use crate::errors::Error;
use crate::guardrails::{
    Guardrails, BUDGETS_FIELD_REFERENCE, RATE_LIMIT_FIELD_REFERENCE, RATE_LIMIT_WINDOW_SECONDS,
};
use crate::json::{compact, Json};
use crate::sha256;
use crate::time;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ActionType {
    Permission,
    SideEffect,
    Read,
}

impl ActionType {
    pub fn parse(value: &str) -> Option<ActionType> {
        match value {
            "permission" => Some(ActionType::Permission),
            "side_effect" => Some(ActionType::SideEffect),
            "read" => Some(ActionType::Read),
            _ => None,
        }
    }

    fn effective(self) -> EffectiveActionType {
        match self {
            ActionType::SideEffect => EffectiveActionType::SideEffect,
            // `read` is an alias for `permission`, matching the enforcer.
            ActionType::Permission | ActionType::Read => EffectiveActionType::Permission,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum EffectiveActionType {
    Permission,
    SideEffect,
}

impl EffectiveActionType {
    fn as_str(self) -> &'static str {
        match self {
            EffectiveActionType::Permission => "permission",
            EffectiveActionType::SideEffect => "side_effect",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Decision {
    Allowed,
    Denied,
    Pending,
}

impl Decision {
    pub fn as_str(self) -> &'static str {
        match self {
            Decision::Allowed => "ALLOWED",
            Decision::Denied => "DENIED",
            Decision::Pending => "PENDING",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuditEntry {
    pub timestamp: String,
    pub action_name: String,
    pub action_type: String,
    pub decision: Decision,
    pub reason: String,
    pub contract_field_reference: String,
    pub provisional: bool,
}

#[derive(Clone, Debug)]
pub struct Outcome {
    pub decision: Decision,
    pub error: Option<Error>,
}

/// Microseconds since the Unix epoch.
pub type Clock = Box<dyn Fn() -> i64 + Send + Sync>;

fn default_clock() -> Clock {
    Box::new(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_micros() as i64)
            .unwrap_or(0)
    })
}

fn timestamp_for(micros: i64) -> String {
    time::iso8601_from_unix(
        micros.div_euclid(1_000_000),
        micros.rem_euclid(1_000_000) as u32,
    )
}

const IRREVERSIBLE_PHRASES: [&str; 17] = [
    "delete",
    "destroy",
    "drop",
    "truncate",
    "purge",
    "erase",
    "wipe",
    "force push",
    "remote execution",
    "publish",
    "deploy",
    "merge",
    "close",
    "transfer",
    "payment",
    "overwrite",
    "revoke",
];

fn irreversible_tokens(text: &str) -> Vec<String> {
    let lowered: String = text
        .chars()
        .map(|character| match character {
            '_' | '-' => ' ',
            other => other.to_ascii_lowercase(),
        })
        .collect();
    lowered
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|token| !token.is_empty())
        .map(ToString::to_string)
        .collect()
}

fn contains_irreversible_phrase(text: &str) -> bool {
    let tokens = irreversible_tokens(text);
    if tokens.is_empty() {
        return false;
    }
    for phrase in IRREVERSIBLE_PHRASES {
        let words: Vec<&str> = phrase.split(' ').collect();
        let width = words.len();
        if width > tokens.len() {
            continue;
        }
        for start in 0..=(tokens.len() - width) {
            if words
                .iter()
                .enumerate()
                .all(|(offset, word)| tokens[start + offset] == *word)
            {
                return true;
            }
        }
    }
    false
}

fn text_of(value: &Json) -> String {
    match value {
        Json::String(text) => text.clone(),
        Json::Bool(true) => "true".to_string(),
        Json::Bool(false) => "false".to_string(),
        Json::Null => "null".to_string(),
        Json::Number(number) => number.as_text().to_string(),
        Json::Array(items) => items.iter().map(text_of).collect::<Vec<_>>().join(","),
        Json::Object(_) => compact(value),
    }
}

fn field_text(entries: &std::collections::BTreeMap<String, Json>, key: &str) -> String {
    entries.get(key).map(text_of).unwrap_or_default()
}

fn empty_object() -> Json {
    Json::Object(std::collections::BTreeMap::new())
}

pub struct ContractEnforcer {
    loaded: LoadedContract,
    clock: Clock,
    audit_log: Vec<AuditEntry>,
    granted_approvals: std::collections::BTreeSet<String>,
    guardrail_attempts: Vec<i64>,
    guardrail_admissions: Vec<i64>,
}

impl ContractEnforcer {
    pub fn load(path: &Path, mode: Mode) -> Result<ContractEnforcer, Error> {
        ContractEnforcer::load_with_clock(path, mode, default_clock())
    }

    pub fn load_with_clock(
        path: &Path,
        mode: Mode,
        clock: Clock,
    ) -> Result<ContractEnforcer, Error> {
        let loaded = load_contract_file(path, mode)?;
        Ok(ContractEnforcer {
            loaded,
            clock,
            audit_log: Vec::new(),
            granted_approvals: std::collections::BTreeSet::new(),
            guardrail_attempts: Vec::new(),
            guardrail_admissions: Vec::new(),
        })
    }

    pub fn mode(&self) -> Mode {
        self.loaded.mode
    }

    pub fn contract(&self) -> &Json {
        &self.loaded.contract
    }

    pub fn contract_path(&self) -> &Path {
        &self.loaded.contract_path
    }

    pub fn integrity_hash(&self) -> &str {
        &self.loaded.integrity_hash
    }

    pub fn guardrails(&self) -> Option<&Guardrails> {
        self.loaded.guardrails.as_ref()
    }

    pub fn is_provisional(&self) -> bool {
        self.loaded.is_provisional()
    }

    pub fn audit_log(&self) -> &[AuditEntry] {
        &self.audit_log
    }

    /// Re-read the pinned canonical path and compare its SHA-256 to load time.
    /// Removal, content change, and a path swap all fail closed.
    pub fn verify_integrity(&self) -> Result<(), Error> {
        let canonical = &self.loaded.contract_path;
        let bytes = match std::fs::read(canonical) {
            Ok(bytes) => bytes,
            Err(_) => {
                return Err(Error::tamper(format!(
                    "Contract file '{}' was removed from disk after load, so it cannot be \
                     verified (tampered state). Reload the contract or restart the agent to \
                     recover.",
                    canonical.display()
                )));
            }
        };
        let current = sha256::hex_digest(&bytes);
        if current != self.loaded.integrity_hash {
            return Err(Error::tamper(format!(
                "Contract file '{}' has been tampered with on disk! Load-time hash: {}, Current \
                 hash: {}. Reload the contract or restart the agent to recover.",
                canonical.display(),
                self.loaded.integrity_hash,
                current
            )));
        }

        // Reads always use the pinned canonical path; this second resolution is
        // only there to detect a post-load symlink or path swap (T14).
        let current_target = std::fs::canonicalize(&self.loaded.requested_path).map_err(|_| {
            Error::tamper(format!(
                "Contract path '{}' could not be resolved after load (T14 path swap): the \
                 contract is in a tampered state. Reload the contract or restart the agent.",
                self.loaded.requested_path.display()
            ))
        })?;
        if crate::contract::strip_verbatim(current_target).as_path() != canonical.as_path() {
            return Err(Error::tamper(format!(
                "Contract path '{}' now resolves to a different target than it was pinned to at \
                 load time. A symlink or path swap was detected after load (T14), so the contract \
                 is in a tampered state.",
                self.loaded.requested_path.display()
            )));
        }

        Ok(())
    }

    fn provisional(&self) -> bool {
        self.loaded.mode == Mode::Draft
    }

    fn record(
        &mut self,
        timestamp: String,
        action_name: &str,
        action_type: &str,
        decision: Decision,
        reason: String,
        field_reference: &str,
    ) {
        let provisional = self.provisional();
        self.audit_log.push(AuditEntry {
            timestamp,
            action_name: action_name.to_string(),
            action_type: action_type.to_string(),
            decision,
            reason,
            contract_field_reference: field_reference.to_string(),
            provisional,
        });
    }

    /// Gate one action. Denial and pending are returned as native errors.
    pub fn enforce(&mut self, action_name: &str, action_type: ActionType) -> Result<(), Error> {
        let effective = action_type.effective();
        let moment = self.record_guardrail_attempt();
        let now = moment.map(timestamp_for).unwrap_or_else(time::now_iso8601);

        if let Err(error) = self.verify_integrity() {
            self.record(
                now,
                action_name,
                effective.as_str(),
                Decision::Denied,
                "Contract was tampered with; gate denied.".to_string(),
                "integrity_hash",
            );
            return Err(error);
        }

        if !self.is_action_declared(action_name, effective) {
            let suggestion = match effective {
                EffectiveActionType::SideEffect => "side_effects",
                EffectiveActionType::Permission => "permissions",
            };
            self.record(
                now.clone(),
                action_name,
                effective.as_str(),
                Decision::Denied,
                format!(
                    "Action '{action_name}' is not declared in '{}s'.",
                    effective.as_str()
                ),
                suggestion,
            );
            return Err(Error::undeclared(
                action_name,
                &self.loaded.display_name(),
                suggestion,
            ));
        }

        let approval = self.check_approval_required(action_name);
        if approval.required && !self.granted_approvals.contains(action_name.trim()) {
            let implied = approval
                .config
                .get("source")
                .and_then(Json::as_str)
                .is_some_and(|source| source == "implicit-irreversible");
            let pending_reason = if implied {
                "Action requires human confirmation prior to execution (irreversible in draft \
                 mode)."
            } else {
                "Action requires human confirmation prior to execution."
            };
            self.record(
                now.clone(),
                action_name,
                effective.as_str(),
                Decision::Pending,
                pending_reason.to_string(),
                "approval_points / approvals",
            );
            return Err(Error::approval_pending(action_name, &approval.config));
        }

        if let Some(moment) = moment {
            self.enforce_guardrails(action_name, effective, moment, &now)?;
        }

        self.record(
            now,
            action_name,
            effective.as_str(),
            Decision::Allowed,
            format!("Action '{action_name}' matched declared contract specification."),
            match effective {
                EffectiveActionType::SideEffect => "side_effects",
                EffectiveActionType::Permission => "permissions",
            },
        );
        Ok(())
    }

    /// Gate one action and return the decision instead of propagating denial.
    ///
    /// Approval maps to `PENDING`; declaration, integrity, and guardrail
    /// failures map to `DENIED`, which is the same shape as the reference
    /// (`GuardrailViolationError` is a `ContractViolationError` there).
    pub fn decide(&mut self, action_name: &str, action_type: ActionType) -> Outcome {
        match self.enforce(action_name, action_type) {
            Ok(()) => Outcome {
                decision: Decision::Allowed,
                error: None,
            },
            Err(error) => {
                let decision = match &error {
                    Error::ApprovalPending { .. } => Decision::Pending,
                    _ => Decision::Denied,
                };
                Outcome {
                    decision,
                    error: Some(error),
                }
            }
        }
    }

    pub fn approve(&mut self, action_name: &str, token: &str) {
        let clean = action_name.trim().to_string();
        self.granted_approvals.insert(clean.clone());
        let timestamp = time::now_iso8601();
        self.record(
            timestamp,
            &clean,
            "approval",
            Decision::Allowed,
            format!("Human approval granted manually with token='{token}'."),
            "approval_points / approvals",
        );
    }

    fn is_action_declared(&self, action_name: &str, action_type: EffectiveActionType) -> bool {
        let clean = action_name.trim();
        match action_type {
            EffectiveActionType::Permission => {
                for permission in field_array(&self.loaded.contract, "permissions") {
                    match permission {
                        Json::String(text) => {
                            if clean == text.trim()
                                || clean.replace(' ', "") == text.replace(' ', "")
                            {
                                return true;
                            }
                        }
                        Json::Object(entries) => {
                            for (key, value) in entries {
                                if key == "resource" || key == "actions" {
                                    continue;
                                }
                                let value_text = text_of(value);
                                let combined = format!("{key}:{value_text}").replace(' ', "");
                                if clean.replace(' ', "") == combined
                                    || clean == key.as_str()
                                    || clean == value_text.as_str()
                                {
                                    return true;
                                }
                            }
                            let resource = field_text(entries, "resource");
                            if !resource.is_empty() {
                                if clean == resource.as_str() {
                                    return true;
                                }
                                if let Some(Json::Array(actions)) = entries.get("actions") {
                                    for action in actions {
                                        let text = text_of(action);
                                        if clean == format!("{resource}:{text}")
                                            || clean == format!("{resource}: {text}")
                                            || clean == text.as_str()
                                        {
                                            return true;
                                        }
                                    }
                                }
                            }
                        }
                        _ => {}
                    }
                }
                false
            }
            EffectiveActionType::SideEffect => !self
                .matching_side_effect_declarations(action_name)
                .is_empty(),
        }
    }

    /// RFC 0005 §4.3 requires the irreversible check to use exactly the gate's
    /// side-effect matching algorithm, so this is the single implementation.
    fn matching_side_effect_declarations<'a>(&'a self, action_name: &str) -> Vec<&'a Json> {
        let clean = action_name.trim();
        let clean_lower = clean.to_lowercase();
        let mut matches = Vec::new();

        for side_effect in field_array(&self.loaded.contract, "side_effects") {
            match side_effect {
                Json::String(text) => {
                    let declared = text.to_lowercase();
                    if clean_lower.contains(&declared)
                        || clean == text.as_str()
                        || declared.contains(&clean_lower)
                    {
                        matches.push(side_effect);
                    }
                }
                Json::Object(entries) => {
                    let side_type = field_text(entries, "type").to_lowercase();
                    let resource = field_text(entries, "resource").to_lowercase();
                    let description = field_text(entries, "description").to_lowercase();

                    if clean_lower == side_type
                        || clean_lower == resource
                        || clean_lower == format!("{resource}:{side_type}")
                    {
                        matches.push(side_effect);
                        continue;
                    }
                    if !resource.is_empty() && clean_lower.starts_with(&resource) {
                        let remainder = clean_lower[resource.len()..]
                            .trim_start_matches(&[':', '-', '_', ' '][..]);
                        if !remainder.is_empty()
                            && (side_type.contains(remainder)
                                || remainder.contains(&side_type)
                                || description.contains(remainder))
                        {
                            matches.push(side_effect);
                            continue;
                        }
                    }
                    if description.contains(&clean_lower)
                        || (!side_type.is_empty() && side_type.contains(&clean_lower))
                    {
                        matches.push(side_effect);
                    }
                }
                _ => {}
            }
        }
        matches
    }

    fn is_action_irreversible(&self, action_name: &str) -> bool {
        let matches = self.matching_side_effect_declarations(action_name);
        for declaration in &matches {
            if declaration.get("irreversible") == Some(&Json::Bool(true)) {
                return true;
            }
        }
        if contains_irreversible_phrase(action_name) {
            return true;
        }
        for declaration in &matches {
            let Some(entries) = declaration.as_object() else {
                continue;
            };
            for field in ["type", "resource", "description"] {
                if let Some(Json::String(text)) = entries.get(field) {
                    if contains_irreversible_phrase(text) {
                        return true;
                    }
                }
            }
        }
        false
    }

    fn check_approval_required(&self, action_name: &str) -> ApprovalRequirement {
        let clean = action_name.trim();

        for point in field_array(&self.loaded.contract, "approval_points") {
            if let Json::String(text) = point {
                let point = text.trim();
                if clean == point || clean.contains(point) {
                    return ApprovalRequirement {
                        required: true,
                        config: Json::from_pairs([
                            ("channel", Json::String("manual".to_string())),
                            ("timeout", Json::String("unspecified".to_string())),
                            ("approver", Json::String("human".to_string())),
                        ]),
                    };
                }
            }
        }

        for approval in field_array(&self.loaded.contract, "approvals") {
            match approval {
                Json::String(text) => {
                    let text = text.trim();
                    if clean == text || clean.contains(text) {
                        return ApprovalRequirement {
                            required: true,
                            config: Json::from_pairs([
                                ("action", Json::String(text.to_string())),
                                ("required", Json::Bool(true)),
                                ("approver", Json::String("human".to_string())),
                            ]),
                        };
                    }
                }
                Json::Object(entries) => {
                    let action = field_text(entries, "action");
                    let required = !matches!(entries.get("required"), Some(Json::Bool(false)));
                    if required
                        && (clean == action.as_str()
                            || (!action.is_empty() && clean.contains(&action))
                            || (!action.is_empty() && action.contains(clean)))
                    {
                        return ApprovalRequirement {
                            required: true,
                            config: Json::Object(entries.clone()),
                        };
                    }
                }
                _ => {}
            }
        }

        if self.mode() == Mode::Draft && self.is_action_irreversible(action_name) {
            return ApprovalRequirement {
                required: true,
                config: Json::from_pairs([
                    ("action", Json::String(action_name.to_string())),
                    ("required", Json::Bool(true)),
                    ("approver", Json::String("human".to_string())),
                    ("source", Json::String("implicit-irreversible".to_string())),
                ]),
            };
        }

        ApprovalRequirement {
            required: false,
            config: empty_object(),
        }
    }

    fn record_guardrail_attempt(&mut self) -> Option<i64> {
        self.loaded.guardrails.as_ref()?;
        let moment = (self.clock)();
        let cutoff = moment - RATE_LIMIT_WINDOW_SECONDS * 1_000_000;
        self.guardrail_attempts.retain(|attempt| *attempt >= cutoff);
        self.guardrail_attempts.push(moment);
        Some(moment)
    }

    fn guardrail_denial(
        &mut self,
        action_name: &str,
        action_type: EffectiveActionType,
        timestamp: &str,
        field_reference: &str,
        reason: String,
    ) -> Error {
        self.record(
            timestamp.to_string(),
            action_name,
            action_type.as_str(),
            Decision::Denied,
            reason.clone(),
            field_reference,
        );
        Error::guardrail(reason)
    }

    fn enforce_guardrails(
        &mut self,
        action_name: &str,
        action_type: EffectiveActionType,
        moment: i64,
        timestamp: &str,
    ) -> Result<(), Error> {
        let Some(guardrails) = self.loaded.guardrails.clone() else {
            return Ok(());
        };

        if let Some(rate_limit) = &guardrails.rate_limit {
            let cutoff = moment - RATE_LIMIT_WINDOW_SECONDS * 1_000_000;
            self.guardrail_attempts.retain(|attempt| *attempt >= cutoff);
            if self.guardrail_attempts.len() as i64 > rate_limit.max_calls_per_minute {
                let reason = format!(
                    "Guardrail 'rate_limit' denied action '{action_name}': \
                     max_calls_per_minute={} exceeded ({} gated attempts in the trailing {}s \
                     window).",
                    rate_limit.max_calls_per_minute,
                    self.guardrail_attempts.len(),
                    RATE_LIMIT_WINDOW_SECONDS
                );
                return Err(self.guardrail_denial(
                    action_name,
                    action_type,
                    timestamp,
                    RATE_LIMIT_FIELD_REFERENCE,
                    reason,
                ));
            }
        }

        if let Some(budgets) = &guardrails.budgets {
            if action_type == EffectiveActionType::SideEffect {
                let cutoff = moment - budgets.window_seconds * 1_000_000;
                self.guardrail_admissions
                    .retain(|admission| *admission >= cutoff);
                if self.guardrail_admissions.len() as i64 >= budgets.side_effects_per_window {
                    let reason = format!(
                        "Guardrail 'budgets' denied action '{action_name}': \
                         side_effects_per_window={} reached within window '{}'.",
                        budgets.side_effects_per_window, budgets.window
                    );
                    return Err(self.guardrail_denial(
                        action_name,
                        action_type,
                        timestamp,
                        BUDGETS_FIELD_REFERENCE,
                        reason,
                    ));
                }
                self.guardrail_admissions.push(moment);
            }
        }

        // Guardrail evaluation above cannot fail. `fail_closed` stays part of
        // the parsed model (and of the audit field references) because the
        // Python reference exposes it; there is no fallible clock or arithmetic
        // path here that could bypass it.
        Ok(())
    }
}

struct ApprovalRequirement {
    required: bool,
    config: Json,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn irreversible_phrases_are_token_matched() {
        assert!(contains_irreversible_phrase("file_delete"));
        assert!(contains_irreversible_phrase("force-push main"));
        assert!(contains_irreversible_phrase("prod deploy"));
        assert!(!contains_irreversible_phrase("cache_write"));
        assert!(!contains_irreversible_phrase("comment"));
        assert!(!contains_irreversible_phrase("deleted"));
    }
}
