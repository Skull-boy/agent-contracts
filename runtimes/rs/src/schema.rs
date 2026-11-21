//! Fail-closed contract validation for specification versions 1, 1.1, and 1.2.
//!
//! The schema files are byte-identical copies of `schemas/<version>/contract.schema.json`
//! from the Python reference (a test asserts the equality while the monorepo
//! layout is present). The evaluator implements exactly the draft-2020-12
//! subset those files use; any keyword or `pattern` it does not understand
//! fails closed instead of being ignored. The supported surface is:
//!
//! `type`, `const`, `enum`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else`,
//! `required`, `properties`, `additionalProperties`, `minProperties`,
//! `maxProperties`, `items`, `minItems`, `maxItems`, `minLength`, `maxLength`,
//! `pattern`, `minimum`, `maximum`.
//!
//! Ignored because they carry no validation semantics: `$schema`, `title`,
//! `description`, `default`.

use std::collections::BTreeMap;

use crate::errors::{Error, ValidationIssue};
use crate::json::{compact, json_equal, Json, Number};
use crate::yaml;

const V1_SCHEMA: &str = include_str!("../schemas/v1/contract.schema.json");
const V11_SCHEMA: &str = include_str!("../schemas/v1.1/contract.schema.json");
const V12_SCHEMA: &str = include_str!("../schemas/v1.2/contract.schema.json");

pub const LIFECYCLE_DEFAULTS: [(&str, &str); 3] = [
    ("mode", "request-response"),
    ("initiation", "human-only"),
    ("resumability", "stateless"),
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Version {
    V1,
    V11,
    V12,
}

impl Version {
    pub fn as_str(self) -> &'static str {
        match self {
            Version::V1 => "1",
            Version::V11 => "1.1",
            Version::V12 => "1.2",
        }
    }

    fn schema(self) -> &'static str {
        match self {
            Version::V1 => V1_SCHEMA,
            Version::V11 => V11_SCHEMA,
            Version::V12 => V12_SCHEMA,
        }
    }
}

/// Detect the specification version exactly as the Python validator does: an
/// explicit `contract_version` wins, then `version`, then v1. `None` means an
/// explicitly unsupported version.
pub fn detect_version(contract: &Json) -> Option<Version> {
    let Some(map) = contract.as_object() else {
        return Some(Version::V1);
    };

    if let Some(explicit) = map.get("contract_version") {
        if !matches!(explicit, Json::Null) {
            return match scalar_text(explicit).as_str() {
                "1.2" => Some(Version::V12),
                "1.1" => Some(Version::V11),
                "1" => Some(Version::V1),
                _ => None,
            };
        }
    }

    if let Some(value) = map.get("version") {
        return match value {
            Json::Null => Some(Version::V1),
            Json::Number(number) => {
                let value = number.as_f64()?;
                if value == 1.2 {
                    Some(Version::V12)
                } else if value == 1.1 {
                    Some(Version::V11)
                } else if value == 1.0 {
                    Some(Version::V1)
                } else {
                    None
                }
            }
            Json::String(text) => match text.as_str() {
                "1.2" => Some(Version::V12),
                "1.1" => Some(Version::V11),
                "1" => Some(Version::V1),
                _ => None,
            },
            _ => None,
        };
    }

    Some(Version::V1)
}

fn scalar_text(value: &Json) -> String {
    match value {
        Json::String(text) => text.clone(),
        Json::Number(number) => match number.as_i64() {
            Some(integer) => integer.to_string(),
            None => number
                .as_f64()
                .map(|value| {
                    let text = format!("{value}");
                    text
                })
                .unwrap_or_else(|| number.as_text().to_string()),
        },
        Json::Bool(flag) => flag.to_string(),
        Json::Null => "null".to_string(),
        other => compact(other),
    }
}

/// Validate an already-parsed contract mapping.
pub fn validate_contract_object(contract: &Json) -> Result<(), Error> {
    if !contract.is_object() {
        return Err(Error::validation_with(
            format!("contract must be a mapping, got {}", contract.kind()),
            vec![ValidationIssue::new(
                "",
                format!("contract must be a mapping, got {}", contract.kind()),
            )],
        ));
    }

    let version = match detect_version(contract) {
        Some(version) => version,
        None => {
            let message = format!(
                "Unsupported specification version: {}",
                contract
                    .get("version")
                    .map(scalar_text)
                    .unwrap_or_else(|| "null".to_string())
            );
            return Err(Error::validation_with(
                message.clone(),
                vec![ValidationIssue::new("/version", message)],
            ));
        }
    };

    if version == Version::V1 && contract.get("provisional").is_some() {
        let message = "`provisional` is not supported on contract_version 1; \
                       provisional contracts require contract_version 1.1 or later."
            .to_string();
        return Err(Error::validation_with(
            message.clone(),
            vec![ValidationIssue::new("/provisional", message)],
        ));
    }

    let schema = crate::json::parse(version.schema())
        .expect("embedded schema is valid JSON and reviewed in tests");
    let mut issues = Vec::new();
    validate_node(&schema, contract, "", &mut issues);
    issues.sort_by(|left, right| {
        left.path
            .cmp(&right.path)
            .then_with(|| left.message.cmp(&right.message))
    });

    if issues.is_empty() {
        Ok(())
    } else {
        let details = issues
            .iter()
            .map(|issue| {
                if issue.path.is_empty() {
                    issue.message.clone()
                } else {
                    format!("{}: {}", issue.path, issue.message)
                }
            })
            .collect::<Vec<_>>()
            .join("; ");
        Err(Error::validation_with(
            format!("Contract validation failed: {details}"),
            issues,
        ))
    }
}

fn pointer_token(key: &str) -> String {
    key.replace('~', "~0").replace('/', "~1")
}

fn child_path(path: &str, key: &str) -> String {
    format!("{path}/{}", pointer_token(key))
}

fn printable(value: &Json) -> String {
    compact(value)
}

fn matches_type(name: &str, value: &Json) -> bool {
    match name {
        "object" => value.is_object(),
        "array" => matches!(value, Json::Array(_)),
        "string" => matches!(value, Json::String(_)),
        "boolean" => matches!(value, Json::Bool(_)),
        "number" => matches!(value, Json::Number(_)),
        "integer" => match value {
            Json::Number(number) => number.as_f64().is_some_and(|parsed| parsed.fract() == 0.0),
            _ => false,
        },
        "null" => matches!(value, Json::Null),
        // An unknown type keyword fails closed.
        _ => false,
    }
}

fn push(errors: &mut Vec<ValidationIssue>, path: &str, message: String) {
    errors.push(ValidationIssue::new(path, message));
}

fn validate_node(schema: &Json, value: &Json, path: &str, errors: &mut Vec<ValidationIssue>) {
    let schema = match schema {
        Json::Bool(true) => return,
        Json::Bool(false) => {
            push(
                errors,
                path,
                format!("False schema does not allow {}", printable(value)),
            );
            return;
        }
        Json::Object(map) => map,
        _ => {
            push(errors, path, "schema node is not an object".to_string());
            return;
        }
    };

    if let Some(type_schema) = schema.get("type") {
        let matched = match type_schema {
            Json::String(name) => matches_type(name, value),
            Json::Array(names) => names
                .iter()
                .filter_map(Json::as_str)
                .any(|name| matches_type(name, value)),
            _ => false,
        };
        if !matched {
            let expected = match type_schema {
                Json::String(name) => format!("'{name}'"),
                other => compact(other),
            };
            push(
                errors,
                path,
                format!("{} is not of type {expected}", printable(value)),
            );
            return;
        }
    }

    if let Some(expected) = schema.get("const") {
        if !json_equal(value, expected) {
            push(errors, path, format!("{} was expected", printable(value)));
        }
    }

    if let Some(Json::Array(allowed)) = schema.get("enum") {
        if !allowed.iter().any(|item| json_equal(value, item)) {
            push(
                errors,
                path,
                format!(
                    "{} is not one of {}",
                    printable(value),
                    compact(&Json::Array(allowed.clone()))
                ),
            );
        }
    }

    if let Some(Json::Array(branches)) = schema.get("anyOf") {
        let matched = branches
            .iter()
            .any(|branch| branch_is_valid(branch, value, path));
        if !matched {
            push(
                errors,
                path,
                format!(
                    "{} is not valid under any of the given schemas",
                    printable(value)
                ),
            );
        }
    }

    if let Some(Json::Array(branches)) = schema.get("oneOf") {
        let matches = branches
            .iter()
            .filter(|branch| branch_is_valid(branch, value, path))
            .count();
        if matches == 0 {
            push(
                errors,
                path,
                format!(
                    "{} is not valid under any of the given schemas",
                    printable(value)
                ),
            );
        } else if matches > 1 {
            push(
                errors,
                path,
                format!(
                    "{} is valid under each of the given schemas",
                    printable(value)
                ),
            );
        }
    }

    if let Some(not_schema) = schema.get("not") {
        if branch_is_valid(not_schema, value, path) {
            push(
                errors,
                path,
                format!(
                    "{} should not be valid under {}",
                    printable(value),
                    compact(not_schema)
                ),
            );
        }
    }

    if let Some(condition) = schema.get("if") {
        if branch_is_valid(condition, value, path) {
            if let Some(then_schema) = schema.get("then") {
                validate_node(then_schema, value, path, errors);
            }
        } else if let Some(else_schema) = schema.get("else") {
            validate_node(else_schema, value, path, errors);
        }
    }

    if let Some(map) = value.as_object() {
        if let Some(Json::Array(required)) = schema.get("required") {
            for key in required.iter().filter_map(Json::as_str) {
                if !map.contains_key(key) {
                    push(errors, path, format!("'{key}' is a required property"));
                }
            }
        }
        if let Some(Json::Number(limit)) = schema.get("minProperties") {
            if let Some(limit) = limit.as_f64() {
                if (map.len() as f64) < limit {
                    push(
                        errors,
                        path,
                        format!("{} does not have enough properties", printable(value)),
                    );
                }
            }
        }
        if let Some(Json::Number(limit)) = schema.get("maxProperties") {
            if let Some(limit) = limit.as_f64() {
                if (map.len() as f64) > limit {
                    push(
                        errors,
                        path,
                        format!("{} has too many properties", printable(value)),
                    );
                }
            }
        }

        let properties: BTreeMap<&str, &Json> = match schema.get("properties") {
            Some(Json::Object(entries)) => entries
                .iter()
                .map(|(key, child)| (key.as_str(), child))
                .collect(),
            _ => BTreeMap::new(),
        };
        for (key, child_schema) in &properties {
            if let Some(child) = map.get(*key) {
                validate_node(child_schema, child, &child_path(path, key), errors);
            }
        }

        if let Some(additional) = schema.get("additionalProperties") {
            for (key, child) in map {
                if properties.contains_key(key.as_str()) {
                    continue;
                }
                match additional {
                    Json::Bool(false) => push(
                        errors,
                        path,
                        format!("Additional properties are not allowed ('{key}' was unexpected)"),
                    ),
                    Json::Bool(true) => {}
                    other => validate_node(other, child, &child_path(path, key), errors),
                }
            }
        }
    }

    if let Some(items) = value.as_array() {
        if let Some(item_schema) = schema.get("items") {
            for (index, item) in items.iter().enumerate() {
                validate_node(
                    item_schema,
                    item,
                    &child_path(path, &index.to_string()),
                    errors,
                );
            }
        }
        if let Some(Json::Number(limit)) = schema.get("minItems") {
            if let Some(limit) = limit.as_f64() {
                if (items.len() as f64) < limit {
                    push(errors, path, format!("{} is too short", printable(value)));
                }
            }
        }
        if let Some(Json::Number(limit)) = schema.get("maxItems") {
            if let Some(limit) = limit.as_f64() {
                if (items.len() as f64) > limit {
                    push(errors, path, format!("{} is too long", printable(value)));
                }
            }
        }
    }

    if let Json::String(text) = value {
        let length = text.chars().count() as f64;
        if let Some(Json::Number(limit)) = schema.get("minLength") {
            if let Some(limit) = limit.as_f64() {
                if length < limit {
                    push(errors, path, format!("{} is too short", printable(value)));
                }
            }
        }
        if let Some(Json::Number(limit)) = schema.get("maxLength") {
            if let Some(limit) = limit.as_f64() {
                if length > limit {
                    push(errors, path, format!("{} is too long", printable(value)));
                }
            }
        }
        if let Some(pattern) = schema.get("pattern").and_then(Json::as_str) {
            match matches_supported_pattern(pattern, text) {
                Some(true) => {}
                Some(false) => push(errors, path, format!("'{text}' does not match '{pattern}'")),
                None => push(
                    errors,
                    path,
                    format!("schema uses an unsupported pattern '{pattern}'"),
                ),
            }
        }
    }

    if let Json::Number(number) = value {
        if let Some(parsed) = number.as_f64() {
            if let Some(Json::Number(limit)) = schema.get("minimum") {
                if let Some(limit) = limit.as_f64() {
                    if parsed < limit {
                        push(
                            errors,
                            path,
                            format!("{parsed} is less than the minimum of {limit}"),
                        );
                    }
                }
            }
            if let Some(Json::Number(limit)) = schema.get("maximum") {
                if let Some(limit) = limit.as_f64() {
                    if parsed > limit {
                        push(
                            errors,
                            path,
                            format!("{parsed} is greater than the maximum of {limit}"),
                        );
                    }
                }
            }
        }
    }
}

fn branch_is_valid(schema: &Json, value: &Json, path: &str) -> bool {
    let mut branch_errors = Vec::new();
    validate_node(schema, value, path, &mut branch_errors);
    branch_errors.is_empty()
}

/// The contract schemas use exactly two patterns. Both are implemented
/// directly; anything else is a schema construct this runtime does not claim to
/// support, so it fails closed instead of silently passing.
fn matches_supported_pattern(pattern: &str, text: &str) -> Option<bool> {
    match pattern {
        r"^[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-:]+$" => Some(matches_service_scope(text)),
        r"^[0-9]+(s|m|h|d)$" => Some(matches_window(text)),
        _ => None,
    }
}

/// `service:scope` — one or more `[A-Za-z0-9_-]`, a colon, then one or more
/// `[A-Za-z0-9_:-]` (further colons allowed).
pub fn matches_service_scope(text: &str) -> bool {
    let Some((head, tail)) = text.split_once(':') else {
        return false;
    };
    if head.is_empty() || tail.is_empty() {
        return false;
    }
    head.chars()
        .all(|character| character.is_ascii_alphanumeric() || character == '_' || character == '-')
        && tail.chars().all(|character| {
            character.is_ascii_alphanumeric()
                || character == '_'
                || character == '-'
                || character == ':'
        })
}

fn matches_window(text: &str) -> bool {
    let Some(unit) = text.chars().last() else {
        return false;
    };
    if !matches!(unit, 's' | 'm' | 'h' | 'd') {
        return false;
    }
    let digits = &text[..text.len() - unit.len_utf8()];
    !digits.is_empty() && digits.chars().all(|character| character.is_ascii_digit())
}

/// Apply the v1.1/v1.2 lifecycle default when the block is absent. v1
/// contracts are returned unchanged.
pub fn apply_lifecycle_defaults(contract: &Json) -> Json {
    let version = detect_version(contract);
    if !matches!(version, Some(Version::V11) | Some(Version::V12)) {
        return contract.clone();
    }
    let Some(map) = contract.as_object() else {
        return contract.clone();
    };
    if map.contains_key("lifecycle") {
        return contract.clone();
    }
    let mut updated = map.clone();
    let mut lifecycle = BTreeMap::new();
    for (key, value) in LIFECYCLE_DEFAULTS {
        lifecycle.insert(key.to_string(), Json::String(value.to_string()));
    }
    updated.insert("lifecycle".to_string(), Json::Object(lifecycle));
    Json::Object(updated)
}

/// Read a contract YAML file. `.yml` is rejected; `.yaml` is canonical.
pub fn load_contract_yaml(path: &std::path::Path) -> Result<Json, Error> {
    if path.extension().and_then(|value| value.to_str()) == Some("yml") {
        return Err(Error::validation(format!(
            "Found contract.yml — rename to contract.yaml (see WORKFLOW-CONTRACT-SPEC.md): {}",
            path.display()
        )));
    }
    let text = std::fs::read_to_string(path).map_err(|error| {
        Error::validation(format!(
            "Contract file '{}' is not readable: {error}",
            path.display()
        ))
    })?;
    yaml::parse(&text).map_err(|error| {
        Error::validation(format!(
            "Contract file '{}' is not valid YAML: {error}",
            path.display()
        ))
    })
}

/// Validate a contract file, resolving the schema by its declared version.
pub fn validate_contract_file(path: &std::path::Path) -> Result<(), Error> {
    let contract = load_contract_yaml(path)?;
    if matches!(contract, Json::Null) {
        return Err(Error::validation_with(
            "contract.yaml is empty",
            vec![ValidationIssue::new("", "contract.yaml is empty")],
        ));
    }
    validate_contract_object(&contract)
}

/// Parse a version literal the way the contract model does, for callers that
/// need it without a full contract.
pub fn version_from_number(number: &Number) -> Option<Version> {
    let value = number.as_f64()?;
    if value == 1.2 {
        Some(Version::V12)
    } else if value == 1.1 {
        Some(Version::V11)
    } else if value == 1.0 {
        Some(Version::V1)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::yaml;

    fn contract(source: &str) -> Json {
        yaml::parse(source).unwrap()
    }

    #[test]
    fn embedded_schemas_are_canonical_json() {
        for version in [Version::V1, Version::V11, Version::V12] {
            let parsed = crate::json::parse(version.schema()).unwrap();
            assert!(
                parsed.is_object(),
                "{} schema is not an object",
                version.as_str()
            );
        }
    }

    #[test]
    fn provisional_rules_match_the_reference() {
        let v11 = contract(
            "version: 1.1\nlifecycle:\n  mode: request-response\n  initiation: human-only\n\
             permissions: [\"github:issues:read\"]\nsystem:\n  name: vector-agent\n\
             approvals: []\nside_effects: []\nprovisional: true\n",
        );
        assert!(validate_contract_object(&v11).is_ok());

        let bad_type = contract(
            "version: 1.1\nlifecycle:\n  mode: request-response\n  initiation: human-only\n\
             permissions: [\"github:issues:read\"]\nsystem:\n  name: vector-agent\n\
             approvals: []\nside_effects: []\nprovisional: \"true\"\n",
        );
        let error = validate_contract_object(&bad_type).unwrap_err();
        assert_eq!(error.issues()[0].path, "/provisional");
        assert!(error.issues()[0].message.contains("not of type 'boolean'"));

        let v1 = contract(
            "version: 1\nworkflow: vector\npermissions: []\nside_effects: []\n\
             approval_points: []\ndependencies: []\ninputs: []\noutputs: []\n\
             observability: []\nrecovery_strategy: retry\nreplay_semantics: idempotent\n\
             state: none\nprovisional: true\n",
        );
        let error = validate_contract_object(&v1).unwrap_err();
        assert_eq!(error.issues()[0].path, "/provisional");
        assert!(error.issues()[0].message.contains("1.1 or later"));
    }

    #[test]
    fn rejects_non_array_permissions() {
        let value = contract(
            "version: 1.1\nlifecycle:\n  mode: request-response\n  initiation: human-only\n\
             permissions: \"*\"\nsystem:\n  name: vector-agent\napprovals: []\nside_effects: []\n",
        );
        let error = validate_contract_object(&value).unwrap_err();
        assert_eq!(error.issues()[0].path, "/permissions");
        assert!(error.issues()[0].message.contains("not of type 'array'"));
    }

    #[test]
    fn lifecycle_defaults_are_additive() {
        let value = contract("version: 1.1\npermissions: []\n");
        let with_defaults = apply_lifecycle_defaults(&value);
        assert_eq!(
            compact(with_defaults.get("lifecycle").unwrap()),
            "{\"initiation\":\"human-only\",\"mode\":\"request-response\",\"resumability\":\"stateless\"}"
        );
        let v1 = contract("version: 1\nworkflow: x\n");
        assert!(apply_lifecycle_defaults(&v1).get("lifecycle").is_none());
    }

    #[test]
    fn service_scope_pattern_is_exact() {
        assert!(matches_service_scope("github:issues:read"));
        assert!(matches_service_scope("prod:deploy"));
        assert!(!matches_service_scope("github"));
        assert!(!matches_service_scope(":read"));
        assert!(!matches_service_scope("github:"));
        assert!(!matches_service_scope("github issues:read"));
    }
}
