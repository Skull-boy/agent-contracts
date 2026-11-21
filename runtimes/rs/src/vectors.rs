//! RFC 0005 §6 conformance-vector loader and native runner.
//!
//! The suite bytes are the contract; this runner never writes to `vectors/`,
//! never executes a target, and never delegates to Python. Configuration
//! problems fail closed with exit code 2 at the CLI boundary.

use std::path::{Path, PathBuf};

use crate::contract::Mode;
use crate::enforcer::{ActionType, ContractEnforcer};
use crate::errors::{Error, ValidationIssue};
use crate::json::{compact, parse as parse_json, pretty, Json, Number};
use crate::schema::validate_contract_file;
use crate::trace::TraceLog;
use crate::yaml;

pub const CATEGORIES: [&str; 3] = ["contract-model", "gate-decision", "trace-roundtrip"];
pub const SUITE_VERSION_FILENAME: &str = "suite-version";

/// The suite version this runtime implements (RFC 0005 §6.2 / anchor A6). The
/// CLI enforces the same pin before running any vector.
pub const PINNED_SUITE_VERSION: u64 = 1;

const CANONICAL_CODES: [&str; 6] = [
    "ContractViolationError",
    "ApprovalPendingError",
    "ProvisionalContractError",
    "ContractValidationError",
    "TraceError",
    "GuardrailViolationError",
];

const ENVELOPE_REQUIRED: [&str; 7] = [
    "vector_version",
    "suite_version",
    "category",
    "id",
    "description",
    "input",
    "expect",
];

#[derive(Clone, Debug)]
pub struct Vector {
    pub suite_version: u64,
    pub category: &'static str,
    pub id: String,
    pub description: String,
    pub input: Json,
    pub expect: Json,
    pub notes: Option<String>,
    pub path: PathBuf,
}

#[derive(Clone, Debug)]
pub struct VectorSuite {
    pub suite_version: u64,
    pub root: PathBuf,
    pub vectors: Vec<Vector>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VectorFailure {
    pub id: String,
    pub reason: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VectorRun {
    pub suite_version: u64,
    pub total: usize,
    pub passed: usize,
    pub failed: usize,
    pub failures: Vec<VectorFailure>,
}

impl VectorRun {
    pub fn to_dict(&self) -> Json {
        Json::from_pairs([
            (
                "suite_version",
                Json::Number(Number::new(self.suite_version.to_string())),
            ),
            ("total", Json::Number(Number::new(self.total.to_string()))),
            ("passed", Json::Number(Number::new(self.passed.to_string()))),
            ("failed", Json::Number(Number::new(self.failed.to_string()))),
            (
                "failures",
                Json::Array(
                    self.failures
                        .iter()
                        .map(|failure| {
                            Json::from_pairs([
                                ("id", Json::String(failure.id.clone())),
                                ("reason", Json::String(failure.reason.clone())),
                            ])
                        })
                        .collect(),
                ),
            ),
        ])
    }

    /// Canonical result: sorted keys, compact separators, one trailing newline.
    pub fn to_json(&self) -> String {
        format!("{}\n", compact(&self.to_dict()))
    }
}

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------

fn fail(message: impl Into<String>) -> Error {
    Error::vector_suite(message)
}

fn read_text(path: &Path, what: &str) -> Result<String, Error> {
    let bytes = std::fs::read(path)
        .map_err(|error| fail(format!("cannot read {what} '{}': {error}", path.display())))?;
    String::from_utf8(bytes)
        .map_err(|_| fail(format!("{what} '{}' is not valid UTF-8", path.display())))
}

fn reject_symlink(path: &Path, what: &str) -> Result<(), Error> {
    let metadata = std::fs::symlink_metadata(path).map_err(|error| {
        fail(format!(
            "cannot inspect {what} '{}': {error}",
            path.display()
        ))
    })?;
    if metadata.file_type().is_symlink() {
        return Err(fail(format!(
            "{what} '{}' must not be a symlink (RFC 0005 section 6.1)",
            path.display()
        )));
    }
    Ok(())
}

fn category_for(name: &str) -> Option<&'static str> {
    CATEGORIES
        .iter()
        .copied()
        .find(|category| *category == name)
}

fn category_prefix(category: &str) -> &'static str {
    match category {
        "contract-model" => "cm",
        "gate-decision" => "gd",
        _ => "tr",
    }
}

fn parse_suite_version(text: &str) -> Option<u64> {
    let rest = text.strip_prefix("suite-version: ")?;
    let number = rest.strip_suffix('\n')?;
    if number.is_empty() || (number.len() > 1 && number.starts_with('0')) {
        return None;
    }
    if !number.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    number.parse().ok()
}

fn is_vector_id(candidate: &str) -> bool {
    let bytes = candidate.as_bytes();
    if bytes.len() < 4 || !matches!(&candidate[..3], "cm-" | "gd-" | "tr-") {
        return false;
    }
    let rest = &candidate[3..];
    if rest.len() < 6 {
        return false;
    }
    let (digits, remainder) = rest.split_at(4);
    if !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return false;
    }
    let Some(remainder) = remainder.strip_prefix('-') else {
        return false;
    };
    !remainder.is_empty()
        && remainder.split('-').all(|segment| {
            !segment.is_empty()
                && segment
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
        })
}

fn require_object<'a>(
    value: &'a Json,
    where_: &str,
) -> Result<&'a std::collections::BTreeMap<String, Json>, Error> {
    value.as_object().ok_or_else(|| {
        fail(format!(
            "{where_} must be a JSON object, got {}",
            value.kind()
        ))
    })
}

fn require_non_empty_string(value: Option<&Json>, where_: &str) -> Result<String, Error> {
    match value {
        Some(Json::String(text)) if !text.is_empty() => Ok(text.clone()),
        _ => Err(fail(format!("{where_} must be a non-empty string"))),
    }
}

fn require_bool(value: Option<&Json>, where_: &str) -> Result<bool, Error> {
    match value {
        Some(Json::Bool(flag)) => Ok(*flag),
        _ => Err(fail(format!("{where_} must be a boolean"))),
    }
}

fn require_error_code(value: Option<&Json>, where_: &str) -> Result<String, Error> {
    let code = require_non_empty_string(value, where_)?;
    if !CANONICAL_CODES.contains(&code.as_str()) {
        let mut allowed = CANONICAL_CODES;
        allowed.sort_unstable();
        return Err(fail(format!(
            "{where_} must be one of {}, got '{code}'",
            allowed.join(", ")
        )));
    }
    Ok(code)
}

fn reject_unknown(
    map: &std::collections::BTreeMap<String, Json>,
    allowed: &[&str],
    where_: &str,
) -> Result<(), Error> {
    let unknown: Vec<&str> = map
        .keys()
        .map(String::as_str)
        .filter(|key| !allowed.contains(key))
        .collect();
    if unknown.is_empty() {
        Ok(())
    } else {
        Err(fail(format!(
            "{where_} has unknown key(s): {}",
            unknown.join(", ")
        )))
    }
}

fn validate_contract_model_input(
    input: &std::collections::BTreeMap<String, Json>,
    where_: &str,
) -> Result<(), Error> {
    reject_unknown(
        input,
        &["operation", "mode", "filename", "contract"],
        where_,
    )?;
    match input.get("operation") {
        Some(Json::String(operation)) if operation == "validate" || operation == "load" => {}
        _ => {
            return Err(fail(format!(
                "{where_}.operation must be 'validate' or 'load'"
            )))
        }
    }
    let operation = input
        .get("operation")
        .and_then(Json::as_str)
        .unwrap_or_default();
    if operation == "load" {
        match input.get("mode") {
            None => {
                return Err(fail(format!(
                    "{where_}.mode is required for operation 'load'"
                )))
            }
            Some(Json::String(mode)) if mode == "full" || mode == "draft" => {}
            Some(_) => return Err(fail(format!("{where_}.mode must be 'full' or 'draft'"))),
        }
    } else if input.contains_key("mode") {
        return Err(fail(format!(
            "{where_}.mode must be absent for operation 'validate'"
        )));
    }
    if let Some(filename) = input.get("filename") {
        match filename {
            Json::String(text) if text.ends_with(".yaml") => {}
            _ => {
                return Err(fail(format!(
                    "{where_}.filename must be a string ending in '.yaml'"
                )))
            }
        }
    }
    require_object(
        input
            .get("contract")
            .ok_or_else(|| fail(format!("{where_}.contract is required")))?,
        &format!("{where_}.contract"),
    )?;
    Ok(())
}

fn validate_gate_input(
    input: &std::collections::BTreeMap<String, Json>,
    where_: &str,
) -> Result<(), Error> {
    reject_unknown(
        input,
        &["mode", "contract", "scenario", "tamper_before"],
        where_,
    )?;
    match input.get("mode") {
        Some(Json::String(mode)) if mode == "full" || mode == "draft" => {}
        _ => return Err(fail(format!("{where_}.mode must be 'full' or 'draft'"))),
    }
    require_object(
        input
            .get("contract")
            .ok_or_else(|| fail(format!("{where_}.contract is required")))?,
        &format!("{where_}.contract"),
    )?;
    let scenario = match input.get("scenario") {
        Some(Json::Array(steps)) if !steps.is_empty() => steps,
        _ => return Err(fail(format!("{where_}.scenario must be a non-empty array"))),
    };
    for (index, step) in scenario.iter().enumerate() {
        let step_where = format!("{where_}.scenario[{index}]");
        let step_map = require_object(step, &step_where)?;
        reject_unknown(step_map, &["action", "action_type", "approve"], &step_where)?;
        require_non_empty_string(step_map.get("action"), &format!("{step_where}.action"))?;
        match step_map.get("action_type") {
            Some(Json::String(kind))
                if kind == "permission" || kind == "side_effect" || kind == "read" => {}
            _ => {
                return Err(fail(format!(
                    "{step_where}.action_type must be 'permission', 'side_effect', or 'read'"
                )))
            }
        }
        if let Some(approve) = step_map.get("approve") {
            require_bool(Some(approve), &format!("{step_where}.approve"))?;
        }
    }
    if let Some(tamper) = input.get("tamper_before") {
        require_bool(Some(tamper), &format!("{where_}.tamper_before"))?;
    }
    Ok(())
}

fn validate_trace_input(
    input: &std::collections::BTreeMap<String, Json>,
    where_: &str,
) -> Result<(), Error> {
    reject_unknown(input, &["jsonl", "operation"], where_)?;
    match input.get("operation") {
        Some(Json::String(operation)) if operation == "roundtrip" || operation == "parse" => {}
        _ => {
            return Err(fail(format!(
                "{where_}.operation must be 'roundtrip' or 'parse'"
            )))
        }
    }
    match input.get("jsonl") {
        Some(Json::String(_)) => Ok(()),
        _ => Err(fail(format!("{where_}.jsonl must be a string"))),
    }
}

fn validate_contract_model_expect(
    expect: &std::collections::BTreeMap<String, Json>,
    where_: &str,
) -> Result<(), Error> {
    let result = match expect.get("result") {
        Some(Json::String(text))
            if matches!(text.as_str(), "valid" | "invalid" | "loaded" | "rejected") =>
        {
            text.as_str()
        }
        _ => {
            return Err(fail(format!(
                "{where_}.result is not a valid contract-model result"
            )))
        }
    };
    let errors = match expect.get("errors") {
        None => &[][..],
        Some(Json::Array(items)) => items.as_slice(),
        Some(_) => return Err(fail(format!("{where_}.errors must be an array"))),
    };
    if result == "invalid" {
        if !expect.contains_key("errors") {
            return Err(fail(format!(
                "{where_}.errors is required for result 'invalid'"
            )));
        }
    } else if !errors.is_empty() {
        return Err(fail(format!(
            "{where_}.errors must be [] unless result is 'invalid'"
        )));
    }
    for (index, item) in errors.iter().enumerate() {
        let item_where = format!("{where_}.errors[{index}]");
        let item_map = require_object(item, &item_where)?;
        reject_unknown(item_map, &["path", "message_contains"], &item_where)?;
        match item_map.get("path") {
            None => {
                return Err(fail(format!(
                    "{item_where}.path is required (use null for any path)"
                )))
            }
            Some(Json::Null) | Some(Json::String(_)) => {}
            Some(_) => return Err(fail(format!("{item_where}.path must be a string or null"))),
        }
        require_non_empty_string(
            item_map.get("message_contains"),
            &format!("{item_where}.message_contains"),
        )?;
    }
    if result == "rejected" {
        require_error_code(expect.get("error_code"), &format!("{where_}.error_code"))?;
        require_non_empty_string(
            expect.get("message_contains"),
            &format!("{where_}.message_contains"),
        )?;
    } else if expect.contains_key("error_code") || expect.contains_key("message_contains") {
        return Err(fail(format!(
            "{where_}.error_code/message_contains are only valid for 'rejected'"
        )));
    }
    Ok(())
}

fn validate_gate_expect(
    expect: &std::collections::BTreeMap<String, Json>,
    where_: &str,
) -> Result<(), Error> {
    reject_unknown(expect, &["decisions", "errors"], where_)?;
    let decisions = match expect.get("decisions") {
        Some(Json::Array(items)) if !items.is_empty() => items,
        _ => {
            return Err(fail(format!(
                "{where_}.decisions must be a non-empty array"
            )))
        }
    };
    for (index, decision) in decisions.iter().enumerate() {
        match decision {
            Json::String(text) if matches!(text.as_str(), "ALLOWED" | "DENIED" | "PENDING") => {}
            _ => {
                return Err(fail(format!(
                    "{where_}.decisions[{index}] must be ALLOWED, DENIED, or PENDING"
                )))
            }
        }
    }
    let errors = match expect.get("errors") {
        None => &[][..],
        Some(Json::Array(items)) => items.as_slice(),
        Some(_) => return Err(fail(format!("{where_}.errors must be an array"))),
    };
    for (index, item) in errors.iter().enumerate() {
        let item_where = format!("{where_}.errors[{index}]");
        let item_map = require_object(item, &item_where)?;
        reject_unknown(
            item_map,
            &["index", "error_code", "message_contains"],
            &item_where,
        )?;
        let error_index = match item_map.get("index") {
            Some(Json::Number(number)) => number.as_i64().unwrap_or(-1),
            _ => return Err(fail(format!("{item_where}.index must be an integer"))),
        };
        if error_index < 0 {
            return Err(fail(format!("{item_where}.index must be non-negative")));
        }
        require_error_code(
            item_map.get("error_code"),
            &format!("{item_where}.error_code"),
        )?;
        require_non_empty_string(
            item_map.get("message_contains"),
            &format!("{item_where}.message_contains"),
        )?;
    }
    Ok(())
}

fn validate_trace_expect(
    expect: &std::collections::BTreeMap<String, Json>,
    where_: &str,
) -> Result<(), Error> {
    reject_unknown(
        expect,
        &[
            "result",
            "canonical_jsonl",
            "error_code",
            "message_contains",
        ],
        where_,
    )?;
    let result = match expect.get("result") {
        Some(Json::String(text))
            if matches!(text.as_str(), "roundtrip" | "parsed" | "rejected") =>
        {
            text.as_str()
        }
        _ => {
            return Err(fail(format!(
                "{where_}.result is not a valid trace-roundtrip result"
            )))
        }
    };
    if result == "roundtrip" {
        match expect.get("canonical_jsonl") {
            Some(Json::String(_)) => {}
            _ => return Err(fail(format!("{where_}.canonical_jsonl must be a string"))),
        }
    } else if expect.contains_key("canonical_jsonl") {
        return Err(fail(format!(
            "{where_}.canonical_jsonl is only valid for 'roundtrip'"
        )));
    }
    if result == "rejected" {
        require_error_code(expect.get("error_code"), &format!("{where_}.error_code"))?;
        require_non_empty_string(
            expect.get("message_contains"),
            &format!("{where_}.message_contains"),
        )?;
    } else if expect.contains_key("error_code") || expect.contains_key("message_contains") {
        return Err(fail(format!(
            "{where_}.error_code/message_contains are only valid for 'rejected'"
        )));
    }
    Ok(())
}

fn build_vector(
    payload: &Json,
    category: &'static str,
    suite_version: u64,
    path: &Path,
) -> Result<Vector, Error> {
    let where_ = format!("vector '{}'", path.display());
    let map = require_object(payload, &where_)?;
    let mut allowed: Vec<&str> = ENVELOPE_REQUIRED.to_vec();
    allowed.push("notes");
    reject_unknown(map, &allowed, &where_)?;

    let missing: Vec<&str> = ENVELOPE_REQUIRED
        .iter()
        .copied()
        .filter(|key| !map.contains_key(*key))
        .collect();
    if !missing.is_empty() {
        return Err(fail(format!(
            "{where_} is missing key(s): {}",
            missing.join(", ")
        )));
    }

    match map.get("vector_version") {
        Some(Json::Number(number)) if number.as_i64() == Some(1) => {}
        _ => return Err(fail(format!("{where_}.vector_version must be 1"))),
    }
    match map.get("suite_version") {
        Some(Json::Number(number)) if number.as_i64() == Some(suite_version as i64) => {}
        _ => {
            return Err(fail(format!(
                "{where_}.suite_version must equal suite-version {suite_version}"
            )))
        }
    }
    match map.get("category") {
        Some(Json::String(value)) if value == category => {}
        _ => {
            return Err(fail(format!(
                "{where_}.category must equal the directory name '{category}'"
            )))
        }
    }

    let id = require_non_empty_string(map.get("id"), &format!("{where_}.id"))?;
    if !is_vector_id(&id) {
        return Err(fail(format!("{where_}.id is not a valid vector ID")));
    }
    if !id.starts_with(&format!("{}-", category_prefix(category))) {
        return Err(fail(format!(
            "{where_}.id must start with '{}-' for category '{category}'",
            category_prefix(category)
        )));
    }

    let description =
        require_non_empty_string(map.get("description"), &format!("{where_}.description"))?;
    if description.contains('\n') {
        return Err(fail(format!(
            "{where_}.description must be one line with no newline"
        )));
    }

    let notes = match map.get("notes") {
        None | Some(Json::Null) => None,
        Some(Json::String(text)) => Some(text.clone()),
        Some(_) => {
            return Err(fail(format!(
                "{where_}.notes must be a string when present"
            )))
        }
    };

    let input = require_object(
        map.get("input")
            .ok_or_else(|| fail(format!("{where_}.input is required")))?,
        &format!("{where_}.input"),
    )?;
    let expect = require_object(
        map.get("expect")
            .ok_or_else(|| fail(format!("{where_}.expect is required")))?,
        &format!("{where_}.expect"),
    )?;

    match category {
        "contract-model" => {
            validate_contract_model_input(input, &format!("{where_}.input"))?;
            validate_contract_model_expect(expect, &format!("{where_}.expect"))?;
        }
        "gate-decision" => {
            validate_gate_input(input, &format!("{where_}.input"))?;
            validate_gate_expect(expect, &format!("{where_}.expect"))?;
            let steps = input
                .get("scenario")
                .and_then(Json::as_array)
                .map(Vec::len)
                .unwrap_or(0);
            let decisions = expect
                .get("decisions")
                .and_then(Json::as_array)
                .map(Vec::len)
                .unwrap_or(0);
            if steps != decisions {
                return Err(fail(format!(
                    "{where_}.expect.decisions must have one entry per scenario step ({steps}), \
                     got {decisions}"
                )));
            }
        }
        _ => {
            validate_trace_input(input, &format!("{where_}.input"))?;
            validate_trace_expect(expect, &format!("{where_}.expect"))?;
        }
    }

    Ok(Vector {
        suite_version,
        category,
        id,
        description,
        input: Json::Object(input.clone()),
        expect: Json::Object(expect.clone()),
        notes,
        path: path.to_path_buf(),
    })
}

fn category_files(directory: &Path) -> Result<Vec<PathBuf>, Error> {
    let entries = std::fs::read_dir(directory).map_err(|error| {
        fail(format!(
            "cannot read category directory '{}': {error}",
            directory.display()
        ))
    })?;
    let mut files = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|error| {
            fail(format!(
                "cannot read category directory '{}': {error}",
                directory.display()
            ))
        })?;
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        reject_symlink(&path, "vector entry")?;
        if entry.file_type().map(|kind| kind.is_dir()).unwrap_or(false) {
            return Err(fail(format!(
                "vector file '{}' must not be nested deeper than the category directory",
                path.display()
            )));
        }
        if !name.ends_with(".json") {
            return Err(fail(format!(
                "unexpected file '{}' in a category directory; vectors must be named \
                 '<id>.json'",
                path.display()
            )));
        }
        files.push(path);
    }
    files.sort();
    Ok(files)
}

pub fn load_suite(root: &Path) -> Result<VectorSuite, Error> {
    if !root.exists() {
        return Err(fail(format!(
            "vector suite not found at '{}'",
            root.display()
        )));
    }
    if !root.is_dir() {
        return Err(fail(format!(
            "vector suite root '{}' is not a directory",
            root.display()
        )));
    }
    reject_symlink(root, "vector suite root")?;

    let version_path = root.join(SUITE_VERSION_FILENAME);
    if !version_path.exists() {
        return Err(fail(format!(
            "vector suite is missing '{}'",
            version_path.display()
        )));
    }
    let version_text = read_text(&version_path, "suite-version")?;
    let suite_version = parse_suite_version(&version_text).ok_or_else(|| {
        fail(format!(
            "'{}' must be exactly 'suite-version: <integer>\\n' with no BOM, comments, or extra \
             keys",
            version_path.display()
        ))
    })?;
    if suite_version == 0 {
        return Ok(VectorSuite {
            suite_version: 0,
            root: root.to_path_buf(),
            vectors: Vec::new(),
        });
    }

    let version_dir = root.join(format!("v{suite_version}"));
    if !version_dir.is_dir() {
        return Err(fail(format!(
            "suite-version is {suite_version} but '{}' is missing",
            version_dir.display()
        )));
    }
    reject_symlink(&version_dir, "version directory")?;

    for entry in std::fs::read_dir(&version_dir).map_err(|error| {
        fail(format!(
            "cannot read version directory '{}': {error}",
            version_dir.display()
        ))
    })? {
        let entry = entry.map_err(|error| {
            fail(format!(
                "cannot read version directory '{}': {error}",
                version_dir.display()
            ))
        })?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if category_for(&name).is_none() {
            return Err(fail(format!(
                "unknown category '{name}' in '{}'; allowed categories are {}",
                version_dir.display(),
                CATEGORIES.join(", ")
            )));
        }
    }

    let mut vectors = Vec::new();
    let mut seen: Vec<(String, PathBuf)> = Vec::new();
    for category in CATEGORIES {
        let category_dir = version_dir.join(category);
        if !category_dir.is_dir() {
            return Err(fail(format!(
                "missing category directory '{}'",
                category_dir.display()
            )));
        }
        reject_symlink(&category_dir, "category directory")?;
        for vector_path in category_files(&category_dir)? {
            let text = read_text(&vector_path, "vector")?;
            let payload = parse_json(&text).map_err(|error| {
                fail(format!(
                    "vector '{}': {}",
                    vector_path.display(),
                    error.message()
                ))
            })?;
            if pretty(&payload) != text {
                return Err(fail(format!(
                    "vector '{}' is not in canonical JSON form (sorted keys, two-space indent, \
                     one trailing newline)",
                    vector_path.display()
                )));
            }
            let vector = build_vector(&payload, category, suite_version, &vector_path)?;

            let stem = vector_path
                .file_stem()
                .map(|stem| stem.to_string_lossy().into_owned())
                .unwrap_or_default();
            if stem != vector.id {
                return Err(fail(format!(
                    "vector file '{}' must be named '{}.json'",
                    vector_path.display(),
                    vector.id
                )));
            }
            if let Some((_, previous)) = seen.iter().find(|(id, _)| *id == vector.id) {
                return Err(fail(format!(
                    "duplicate vector ID '{}' in '{}' and '{}'",
                    vector.id,
                    vector_path.display(),
                    previous.display()
                )));
            }
            seen.push((vector.id.clone(), vector_path.clone()));
            vectors.push(vector);
        }
    }

    vectors.sort_by(|left, right| left.id.cmp(&right.id));
    Ok(VectorSuite {
        suite_version,
        root: root.to_path_buf(),
        vectors,
    })
}

// ---------------------------------------------------------------------------
// Execution
// ---------------------------------------------------------------------------

struct TempDir {
    path: PathBuf,
}

impl TempDir {
    fn create() -> Result<TempDir, Error> {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);

        let base = std::env::temp_dir();
        let base = std::fs::canonicalize(&base).unwrap_or(base);
        for _ in 0..1_000 {
            let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|duration| duration.subsec_nanos())
                .unwrap_or(0);
            let candidate = base.join(format!(
                "scyvera-rs-vector-{}-{unique}-{nanos}",
                std::process::id()
            ));
            match std::fs::create_dir(&candidate) {
                Ok(()) => return Ok(TempDir { path: candidate }),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => {
                    return Err(Error::io(format!(
                        "cannot create a scratch directory in '{}': {error}",
                        base.display()
                    )))
                }
            }
        }
        Err(Error::io("cannot create a unique scratch directory"))
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn write_contract(contract: &Json, directory: &Path, filename: &str) -> Result<PathBuf, Error> {
    let path = directory.join(filename);
    std::fs::write(&path, yaml::to_yaml(contract)).map_err(|error| {
        Error::io(format!(
            "cannot write vector contract '{}': {error}",
            path.display()
        ))
    })?;
    Ok(path)
}

fn scrub(reason: String, directory: &Path) -> String {
    reason.replace(&directory.display().to_string(), "<tmp>")
}

fn match_contract_errors(
    expected: &[Json],
    actual: &[ValidationIssue],
    where_: &str,
) -> Option<String> {
    let mut remaining: Vec<&ValidationIssue> = actual.iter().collect();
    for item in expected {
        let Some(map) = item.as_object() else {
            return Some(format!("{where_}: internal vector shape error"));
        };
        let path = map.get("path").cloned().unwrap_or(Json::Null);
        let needle = map
            .get("message_contains")
            .and_then(Json::as_str)
            .unwrap_or_default();
        let found = remaining.iter().position(|candidate| {
            let path_matches = match &path {
                Json::Null => true,
                Json::String(expected_path) => candidate.path == expected_path.as_str(),
                _ => false,
            };
            path_matches && candidate.message.contains(needle)
        });
        match found {
            Some(index) => {
                remaining.remove(index);
            }
            None => {
                return Some(format!(
                    "{where_}: no error matched path={} message_contains={}",
                    compact(&path),
                    compact(&Json::String(needle.to_string()))
                ))
            }
        }
    }
    if expected.is_empty() && !actual.is_empty() {
        return Some(format!(
            "{where_}: expected no errors, got {}",
            actual.len()
        ));
    }
    None
}

fn run_contract_model(vector: &Vector) -> Result<Option<String>, Error> {
    let input = &vector.input;
    let expect = &vector.expect;
    let operation = input.get("operation").and_then(Json::as_str).unwrap_or("");
    let directory = TempDir::create()?;

    let filename = input
        .get("filename")
        .and_then(Json::as_str)
        .unwrap_or("contract.yaml");
    let contract = input
        .get("contract")
        .ok_or_else(|| fail("input.contract is missing"))?;
    let contract_path = write_contract(contract, &directory.path, filename)?;

    let outcome = (|| -> Result<Option<String>, Error> {
        if operation == "validate" {
            let validation = validate_contract_file(&contract_path);
            let actual_result = if validation.is_ok() {
                "valid"
            } else {
                "invalid"
            };
            let expected_result = expect.get("result").and_then(Json::as_str).unwrap_or("");
            if actual_result != expected_result {
                let detail = match &validation {
                    Ok(()) => "no validation errors".to_string(),
                    Err(error) => match error.issues().first() {
                        Some(issue) if !issue.path.is_empty() => {
                            format!("{}: {}", issue.path, issue.message)
                        }
                        Some(issue) => issue.message.clone(),
                        None => error.message().to_string(),
                    },
                };
                return Ok(Some(format!(
                    "expected result \"{expected_result}\", got \"{actual_result}\" ({detail})"
                )));
            }
            if expected_result == "invalid" {
                let expected_errors = expect
                    .get("errors")
                    .and_then(Json::as_array)
                    .cloned()
                    .unwrap_or_default();
                let actual_errors = validation
                    .err()
                    .map(|error| error.issues().to_vec())
                    .unwrap_or_default();
                return Ok(match_contract_errors(
                    &expected_errors,
                    &actual_errors,
                    "validation errors",
                ));
            }
            return Ok(None);
        }

        let mode = match input.get("mode").and_then(Json::as_str) {
            Some("draft") => Mode::Draft,
            _ => Mode::Full,
        };
        let (actual_result, code, message) = match ContractEnforcer::load(&contract_path, mode) {
            Ok(_) => ("loaded", String::new(), String::new()),
            Err(error) => (
                "rejected",
                error.code().to_string(),
                error.message().to_string(),
            ),
        };
        let expected_result = expect.get("result").and_then(Json::as_str).unwrap_or("");
        if actual_result != expected_result {
            let suffix = if code.is_empty() {
                String::new()
            } else {
                format!(" ({code}: {message})")
            };
            return Ok(Some(format!(
                "expected result \"{expected_result}\", got \"{actual_result}\"{suffix}"
            )));
        }
        if expected_result == "rejected" {
            let expected_code = expect
                .get("error_code")
                .and_then(Json::as_str)
                .unwrap_or_default();
            if code != expected_code {
                return Ok(Some(format!(
                    "expected error_code \"{expected_code}\", got \"{code}\""
                )));
            }
            let needle = expect
                .get("message_contains")
                .and_then(Json::as_str)
                .unwrap_or_default();
            if !message.contains(needle) {
                return Ok(Some(format!(
                    "expected message_contains \"{needle}\", got \"{message}\""
                )));
            }
        }
        Ok(None)
    })();

    Ok(outcome?.map(|reason| scrub(reason, &directory.path)))
}

fn run_gate(vector: &Vector) -> Result<Option<String>, Error> {
    let input = &vector.input;
    let expect = &vector.expect;
    let scenario = input
        .get("scenario")
        .and_then(Json::as_array)
        .cloned()
        .unwrap_or_default();
    let decisions = expect
        .get("decisions")
        .and_then(Json::as_array)
        .cloned()
        .unwrap_or_default();
    if decisions.len() != scenario.len() {
        return Ok(Some(format!(
            "expected {} decisions for {} steps",
            decisions.len(),
            scenario.len()
        )));
    }

    let directory = TempDir::create()?;
    let outcome = (|| -> Result<Option<String>, Error> {
        let contract = input
            .get("contract")
            .ok_or_else(|| fail("input.contract is missing"))?;
        let contract_path = write_contract(contract, &directory.path, "contract.yaml")?;

        let mode = match input.get("mode").and_then(Json::as_str) {
            Some("draft") => Mode::Draft,
            _ => Mode::Full,
        };
        let mut enforcer = match ContractEnforcer::load(&contract_path, mode) {
            Ok(enforcer) => enforcer,
            Err(error) => {
                return Ok(Some(format!(
                    "contract failed to load: {}: {}",
                    error.code(),
                    error.message()
                )))
            }
        };

        if input.get("tamper_before").and_then(Json::as_bool) == Some(true) {
            let mut bytes = std::fs::read(&contract_path)
                .map_err(|error| Error::io(format!("cannot read the vector contract: {error}")))?;
            bytes.extend_from_slice(b"\n# tampered\n");
            std::fs::write(&contract_path, bytes).map_err(|error| {
                Error::io(format!("cannot tamper with the vector contract: {error}"))
            })?;
        }

        let mut actual_decisions: Vec<String> = Vec::new();
        let mut actual_errors: Vec<(usize, String, String)> = Vec::new();

        for (index, raw_step) in scenario.iter().enumerate() {
            let step = raw_step
                .as_object()
                .ok_or_else(|| fail("scenario step is not an object"))?;
            let action = step
                .get("action")
                .and_then(Json::as_str)
                .unwrap_or_default()
                .to_string();
            if step.get("approve").and_then(Json::as_bool) == Some(true) {
                enforcer.approve(&action, "");
            }
            let action_type = match step.get("action_type").and_then(Json::as_str) {
                Some("side_effect") => ActionType::SideEffect,
                Some("read") => ActionType::Read,
                _ => ActionType::Permission,
            };
            let outcome = enforcer.decide(&action, action_type);
            actual_decisions.push(outcome.decision.as_str().to_string());
            if let Some(error) = outcome.error {
                actual_errors.push((index, error.code().to_string(), error.message().to_string()));
            }
        }

        let expected_decisions: Vec<String> = decisions
            .iter()
            .map(|item| item.as_str().unwrap_or_default().to_string())
            .collect();
        if actual_decisions != expected_decisions {
            return Ok(Some(format!(
                "expected decisions {}, got {}",
                compact(&Json::Array(
                    expected_decisions
                        .iter()
                        .map(|text| Json::String(text.clone()))
                        .collect()
                )),
                compact(&Json::Array(
                    actual_decisions
                        .iter()
                        .map(|text| Json::String(text.clone()))
                        .collect()
                ))
            )));
        }

        let expected_errors = expect
            .get("errors")
            .and_then(Json::as_array)
            .cloned()
            .unwrap_or_default();
        if actual_errors.len() != expected_errors.len() {
            return Ok(Some(format!(
                "expected {} error(s), got {}: {}",
                expected_errors.len(),
                actual_errors.len(),
                compact(&Json::Array(
                    actual_errors
                        .iter()
                        .map(|(index, code, _)| Json::Array(vec![
                            Json::Number(Number::new(index.to_string())),
                            Json::String(code.clone())
                        ]))
                        .collect()
                ))
            )));
        }

        for raw_expected in &expected_errors {
            let expected = raw_expected
                .as_object()
                .ok_or_else(|| fail("expect.errors[] is not an object"))?;
            let expected_index = expected
                .get("index")
                .and_then(|value| match value {
                    Json::Number(number) => number.as_i64(),
                    _ => None,
                })
                .unwrap_or(-1);
            let Some((_, code, message)) = actual_errors
                .iter()
                .find(|(index, _, _)| *index as i64 == expected_index)
            else {
                return Ok(Some(format!(
                    "expected error(s) at step(s) [{expected_index}] but none occurred"
                )));
            };
            let expected_code = expected
                .get("error_code")
                .and_then(Json::as_str)
                .unwrap_or_default();
            if code.as_str() != expected_code {
                return Ok(Some(format!(
                    "step {expected_index}: expected error_code \"{expected_code}\", got \
                     \"{code}\""
                )));
            }
            let needle = expected
                .get("message_contains")
                .and_then(Json::as_str)
                .unwrap_or_default();
            if !message.contains(needle) {
                return Ok(Some(format!(
                    "step {expected_index}: expected message_contains \"{needle}\", got \
                     \"{message}\""
                )));
            }
        }

        Ok(None)
    })();

    Ok(outcome?.map(|reason| scrub(reason, &directory.path)))
}

fn run_trace(vector: &Vector) -> Result<Option<String>, Error> {
    let input = &vector.input;
    let expect = &vector.expect;
    let jsonl = input.get("jsonl").and_then(Json::as_str);
    let Some(jsonl) = jsonl else {
        return Ok(Some("input.jsonl is not a string".to_string()));
    };
    let operation = input.get("operation").and_then(Json::as_str).unwrap_or("");

    if operation == "roundtrip" {
        let canonical = match TraceLog::from_jsonl(jsonl) {
            Ok(log) => log.to_jsonl(),
            Err(error) => {
                return Ok(Some(format!(
                    "roundtrip raised {}: {}",
                    error.code(),
                    error.message()
                )))
            }
        };
        if expect.get("result").and_then(Json::as_str) != Some("roundtrip") {
            return Ok(Some(format!(
                "expected result {}, got 'roundtrip'",
                compact(expect.get("result").unwrap_or(&Json::Null))
            )));
        }
        let expected = expect
            .get("canonical_jsonl")
            .and_then(Json::as_str)
            .unwrap_or_default();
        if canonical != expected {
            return Ok(Some(format!(
                "canonical_jsonl mismatch: expected {}, got {}",
                compact(&Json::String(expected.to_string())),
                compact(&Json::String(canonical))
            )));
        }
        return Ok(None);
    }

    let (actual_result, code, message) = match TraceLog::from_jsonl(jsonl) {
        Ok(_) => ("parsed", String::new(), String::new()),
        Err(error) => (
            "rejected",
            error.code().to_string(),
            error.message().to_string(),
        ),
    };
    let expected_result = expect.get("result").and_then(Json::as_str).unwrap_or("");
    if actual_result != expected_result {
        return Ok(Some(format!(
            "expected result \"{expected_result}\", got \"{actual_result}\""
        )));
    }
    if expected_result == "rejected" {
        let expected_code = expect
            .get("error_code")
            .and_then(Json::as_str)
            .unwrap_or_default();
        if code != expected_code {
            return Ok(Some(format!(
                "expected error_code \"{expected_code}\", got \"{code}\""
            )));
        }
        let needle = expect
            .get("message_contains")
            .and_then(Json::as_str)
            .unwrap_or_default();
        if !message.contains(needle) {
            return Ok(Some(format!(
                "expected message_contains \"{needle}\", got \"{message}\""
            )));
        }
    }
    Ok(None)
}

pub fn run_suite(suite: &VectorSuite, category: Option<&str>) -> Result<VectorRun, Error> {
    if let Some(name) = category {
        if category_for(name).is_none() {
            return Err(fail(format!(
                "unknown category '{name}'; allowed categories are {}",
                CATEGORIES.join(", ")
            )));
        }
    }

    let mut failures = Vec::new();
    let mut selected = 0usize;
    for vector in &suite.vectors {
        if let Some(name) = category {
            if vector.category != name {
                continue;
            }
        }
        selected += 1;
        let outcome = match vector.category {
            "contract-model" => run_contract_model(vector),
            "gate-decision" => run_gate(vector),
            _ => run_trace(vector),
        };
        match outcome {
            Ok(None) => {}
            Ok(Some(reason)) => failures.push(VectorFailure {
                id: vector.id.clone(),
                reason,
            }),
            Err(error) => failures.push(VectorFailure {
                id: vector.id.clone(),
                reason: format!("runner error: {}", error.code()),
            }),
        }
    }

    failures.sort_by(|left, right| left.id.cmp(&right.id));
    let failed = failures.len();
    Ok(VectorRun {
        suite_version: suite.suite_version,
        total: selected,
        passed: selected - failed,
        failed,
        failures,
    })
}

/// Categories present in a suite, with their vector counts (used by the CLI's
/// human-readable summary).
pub fn category_counts(suite: &VectorSuite) -> Vec<(&'static str, Vec<&str>)> {
    CATEGORIES
        .iter()
        .map(|category| {
            let ids = suite
                .vectors
                .iter()
                .filter(|vector| vector.category == *category)
                .map(|vector| vector.id.as_str())
                .collect();
            (*category, ids)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn suite_version_parser_is_exact() {
        assert_eq!(parse_suite_version("suite-version: 1\n"), Some(1));
        assert_eq!(parse_suite_version("suite-version: 0\n"), Some(0));
        assert_eq!(parse_suite_version("suite-version: 01\n"), None);
        assert_eq!(parse_suite_version("suite-version: 1"), None);
        assert_eq!(parse_suite_version("suite-version: 1 \n"), None);
        assert_eq!(parse_suite_version("suite-version: 1\n\n"), None);
    }

    #[test]
    fn vector_ids_are_validated() {
        assert!(is_vector_id("cm-0001-provisional-flag-valid"));
        assert!(is_vector_id("gd-0013-guardrail-budget-denied"));
        assert!(!is_vector_id("cm-0001"));
        assert!(!is_vector_id("cm-1-provisional"));
        assert!(!is_vector_id("cm-0001-Provisional"));
        assert!(!is_vector_id("xx-0001-slug"));
    }
}
