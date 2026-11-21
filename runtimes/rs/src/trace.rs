//! RFC 0003 §C4 trace schema with the additive RFC 0005 §4.4 field.
//!
//! Parsing is fail-closed: unknown fields, missing fields, wrong types,
//! non-boolean `provisional`, bad SHA-256 strings, non-ISO-8601 timestamps, and
//! unknown result values are rejected. Serialization is canonical: sorted keys,
//! compact separators, UTF-8 (`ensure_ascii=False`), one object per line,
//! newline-terminated. A full-mode entry omits `provisional` and is
//! byte-identical to the pre-RFC-0005 output.

use std::collections::BTreeMap;

use crate::enforcer::{AuditEntry, Decision};
use crate::errors::Error;
use crate::json::{compact_utf8, parse as parse_json, Json};

pub const TRACE_RESULT_ALLOWED: &str = "allowed";
pub const TRACE_RESULT_PENDING_APPROVAL: &str = "pending_approval";
pub const TRACE_RESULT_VIOLATION: &str = "violation";

const REQUIRED_FIELDS: [&str; 9] = [
    "node_id",
    "action_name",
    "action_type",
    "declared",
    "result",
    "hash_of_contract",
    "timestamp",
    "reason",
    "contract_field_reference",
];

const OPTIONAL_FIELDS: [&str; 1] = ["provisional"];

const UNDECLARED_MARKER: &str = " is not declared in ";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TraceEntry {
    pub node_id: Option<String>,
    pub action_name: String,
    pub action_type: String,
    pub declared: bool,
    pub result: String,
    pub hash_of_contract: String,
    pub timestamp: String,
    pub reason: String,
    pub contract_field_reference: String,
    pub provisional: Option<bool>,
}

impl TraceEntry {
    pub fn from_dict(data: &Json) -> Result<TraceEntry, Error> {
        let map = match data.as_object() {
            Some(map) => map,
            None => {
                return Err(Error::trace(format!(
                    "trace entry must be a JSON object, got {}",
                    data.kind()
                )))
            }
        };

        let missing: Vec<&str> = REQUIRED_FIELDS
            .iter()
            .copied()
            .filter(|field| !map.contains_key(*field))
            .collect();
        if !missing.is_empty() {
            return Err(Error::trace(format!(
                "trace entry is missing field(s): {}",
                missing.join(", ")
            )));
        }

        let unknown: Vec<&str> = map
            .keys()
            .map(String::as_str)
            .filter(|key| !REQUIRED_FIELDS.contains(key) && !OPTIONAL_FIELDS.contains(key))
            .collect();
        if !unknown.is_empty() {
            return Err(Error::trace(format!(
                "trace entry has unknown field(s): {}",
                unknown.join(", ")
            )));
        }

        let provisional = match map.get("provisional") {
            None => None,
            Some(Json::Bool(flag)) => Some(*flag),
            Some(_) => {
                return Err(Error::trace(
                    "trace field 'provisional' must be a boolean when present",
                ))
            }
        };

        let node_id = match map.get("node_id") {
            Some(Json::Null) => None,
            Some(Json::String(text)) if !text.is_empty() => Some(text.clone()),
            Some(Json::String(_)) => {
                return Err(Error::trace("trace field 'node_id' must be non-empty"))
            }
            Some(_) => return Err(Error::trace("trace field 'node_id' must be a string")),
            None => unreachable!("missing fields are rejected above"),
        };

        let action_name = require_non_empty(map, "action_name")?;
        let action_type = require_non_empty(map, "action_type")?;

        let declared = match map.get("declared") {
            Some(Json::Bool(flag)) => *flag,
            _ => return Err(Error::trace("trace field 'declared' must be a boolean")),
        };

        let result = match map.get("result") {
            Some(Json::String(text))
                if matches!(
                    text.as_str(),
                    TRACE_RESULT_ALLOWED | TRACE_RESULT_PENDING_APPROVAL | TRACE_RESULT_VIOLATION
                ) =>
            {
                text.clone()
            }
            Some(Json::String(text)) => {
                return Err(Error::trace(format!(
                    "trace field 'result' must be one of [\"allowed\",\"pending_approval\",\
                     \"violation\"], got \"{text}\""
                )))
            }
            _ => {
                return Err(Error::trace(
                    "trace field 'result' must be one of [\"allowed\",\"pending_approval\",\
                     \"violation\"]",
                ))
            }
        };

        let hash_of_contract = validate_hash(map.get("hash_of_contract"))?;
        let timestamp = validate_timestamp(map.get("timestamp"))?;
        let reason = require_string(map, "reason", true)?;
        let contract_field_reference = require_string(map, "contract_field_reference", true)?;

        Ok(TraceEntry {
            node_id,
            action_name,
            action_type,
            declared,
            result,
            hash_of_contract,
            timestamp,
            reason,
            contract_field_reference,
            provisional,
        })
    }

    pub fn to_dict(&self) -> Json {
        let mut map = BTreeMap::new();
        map.insert(
            "node_id".to_string(),
            match &self.node_id {
                Some(text) => Json::String(text.clone()),
                None => Json::Null,
            },
        );
        map.insert(
            "action_name".to_string(),
            Json::String(self.action_name.clone()),
        );
        map.insert(
            "action_type".to_string(),
            Json::String(self.action_type.clone()),
        );
        map.insert("declared".to_string(), Json::Bool(self.declared));
        map.insert("result".to_string(), Json::String(self.result.clone()));
        map.insert(
            "hash_of_contract".to_string(),
            Json::String(self.hash_of_contract.clone()),
        );
        map.insert(
            "timestamp".to_string(),
            Json::String(self.timestamp.clone()),
        );
        map.insert("reason".to_string(), Json::String(self.reason.clone()));
        map.insert(
            "contract_field_reference".to_string(),
            Json::String(self.contract_field_reference.clone()),
        );
        if self.provisional == Some(true) {
            map.insert("provisional".to_string(), Json::Bool(true));
        }
        Json::Object(map)
    }
}

fn require_string(
    map: &BTreeMap<String, Json>,
    field: &str,
    allow_empty: bool,
) -> Result<String, Error> {
    match map.get(field) {
        Some(Json::String(text)) if allow_empty || !text.is_empty() => Ok(text.clone()),
        Some(Json::String(_)) => Err(Error::trace(format!(
            "trace field '{field}' must be non-empty"
        ))),
        Some(_) => Err(Error::trace(format!(
            "trace field '{field}' must be a string"
        ))),
        None => unreachable!("missing fields are rejected before this point"),
    }
}

fn require_non_empty(map: &BTreeMap<String, Json>, field: &str) -> Result<String, Error> {
    require_string(map, field, false)
}

fn validate_hash(value: Option<&Json>) -> Result<String, Error> {
    let text =
        match value {
            Some(Json::String(text)) if text.len() == 64 => text,
            _ => return Err(Error::trace(
                "trace field 'hash_of_contract' must be a 64-character hexadecimal SHA-256 string",
            )),
        };
    if !text.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(Error::trace(
            "trace field 'hash_of_contract' must be hexadecimal",
        ));
    }
    Ok(text.clone())
}

fn validate_timestamp(value: Option<&Json>) -> Result<String, Error> {
    let text = match value {
        Some(Json::String(text)) if !text.is_empty() => text,
        _ => {
            return Err(Error::trace(
                "trace field 'timestamp' must be a non-empty string",
            ))
        }
    };
    if !is_iso_timestamp(text) {
        return Err(Error::trace(format!(
            "trace field 'timestamp' is not ISO-8601: \"{text}\""
        )));
    }
    Ok(text.clone())
}

fn is_leap_year(year: u32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if is_leap_year(year) {
                29
            } else {
                28
            }
        }
        _ => 0,
    }
}

struct Scanner<'a> {
    bytes: &'a [u8],
    index: usize,
}

impl<'a> Scanner<'a> {
    fn new(text: &'a str) -> Scanner<'a> {
        Scanner {
            bytes: text.as_bytes(),
            index: 0,
        }
    }

    fn digits(&mut self, count: usize) -> Option<u32> {
        if self.index + count > self.bytes.len() {
            return None;
        }
        let slice = &self.bytes[self.index..self.index + count];
        if !slice.iter().all(u8::is_ascii_digit) {
            return None;
        }
        self.index += count;
        Some(slice.iter().fold(0u32, |accumulator, byte| {
            accumulator * 10 + u32::from(byte - b'0')
        }))
    }

    fn take(&mut self, byte: u8) -> bool {
        if self.bytes.get(self.index) == Some(&byte) {
            self.index += 1;
            true
        } else {
            false
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.index).copied()
    }

    fn at_end(&self) -> bool {
        self.index == self.bytes.len()
    }
}

/// Accept the ISO-8601 subset the Python reference accepts via
/// `datetime.fromisoformat` (dates, `T`/`t`/space separators, fractional
/// seconds, `Z` or `±HH:MM`/`±HHMM` offsets).
pub fn is_iso_timestamp(value: &str) -> bool {
    if value.is_empty() {
        return false;
    }
    let mut scanner = Scanner::new(value);
    let (Some(year), Some(_), Some(month), Some(_), Some(day)) = (
        scanner.digits(4),
        if scanner.take(b'-') { Some(()) } else { None },
        scanner.digits(2),
        if scanner.take(b'-') { Some(()) } else { None },
        scanner.digits(2),
    ) else {
        return false;
    };
    if !(1..=12).contains(&month) || day < 1 || day > days_in_month(year, month) {
        return false;
    }
    if scanner.at_end() {
        return true;
    }

    if !matches!(scanner.peek(), Some(b'T') | Some(b't') | Some(b' ')) {
        return false;
    }
    scanner.index += 1;

    let (Some(hour), Some(_), Some(minute)) = (
        scanner.digits(2),
        if scanner.take(b':') { Some(()) } else { None },
        scanner.digits(2),
    ) else {
        return false;
    };
    if hour > 23 || minute > 59 {
        return false;
    }

    if scanner.take(b':') {
        let Some(second) = scanner.digits(2) else {
            return false;
        };
        if second > 59 {
            return false;
        }
        if scanner.take(b'.') {
            let start = scanner.index;
            while matches!(scanner.peek(), Some(byte) if byte.is_ascii_digit()) {
                scanner.index += 1;
            }
            if scanner.index == start {
                return false;
            }
        }
    }

    if scanner.at_end() {
        return true;
    }

    if matches!(scanner.peek(), Some(b'Z') | Some(b'z')) {
        scanner.index += 1;
        return scanner.at_end();
    }

    if !matches!(scanner.peek(), Some(b'+') | Some(b'-')) {
        return false;
    }
    scanner.index += 1;
    let Some(offset_hour) = scanner.digits(2) else {
        return false;
    };
    scanner.take(b':');
    let Some(offset_minute) = scanner.digits(2) else {
        return false;
    };
    if offset_hour > 23 || offset_minute > 59 {
        return false;
    }
    scanner.at_end()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TraceLog {
    pub entries: Vec<TraceEntry>,
}

impl TraceLog {
    pub fn new(entries: Vec<TraceEntry>) -> TraceLog {
        TraceLog { entries }
    }

    /// Canonical JSONL (empty log -> empty string).
    pub fn to_jsonl(&self) -> String {
        let mut output = String::new();
        for entry in &self.entries {
            output.push_str(&compact_utf8(&entry.to_dict()));
            output.push('\n');
        }
        output
    }

    pub fn from_jsonl(text: &str) -> Result<TraceLog, Error> {
        let mut entries = Vec::new();
        for (index, line) in split_lines(text).iter().enumerate() {
            let number = index + 1;
            if line.trim().is_empty() {
                return Err(Error::trace(format!(
                    "trace JSONL line {number}: empty line"
                )));
            }
            let payload = parse_json(line).map_err(|error| {
                Error::trace(format!(
                    "trace JSONL line {number}: invalid JSON ({})",
                    error.message()
                ))
            })?;
            let entry = TraceEntry::from_dict(&payload).map_err(|error| {
                Error::trace(format!("trace JSONL line {number}: {}", error.message()))
            })?;
            entries.push(entry);
        }
        Ok(TraceLog { entries })
    }
}

fn split_lines(text: &str) -> Vec<&str> {
    if text.is_empty() {
        return Vec::new();
    }
    let bytes = text.as_bytes();
    let mut lines = Vec::new();
    let mut start = 0;
    let mut index = 0;
    while index < bytes.len() {
        match bytes[index] {
            b'\r' => {
                lines.push(&text[start..index]);
                index += if bytes.get(index + 1) == Some(&b'\n') {
                    2
                } else {
                    1
                };
                start = index;
            }
            b'\n' => {
                lines.push(&text[start..index]);
                index += 1;
                start = index;
            }
            _ => index += 1,
        }
    }
    // A trailing newline leaves `start == len` and produces no extra line; an
    // interior empty line is kept so the caller can reject it.
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

/// Convert an enforcer audit entry to a trace entry, mirroring the Python
/// reference's `trace_from_audit`. `declared` is derived from the audit reason:
/// only the default-deny path carries the undeclared marker.
pub fn trace_from_audit(
    entry: &AuditEntry,
    node_id: Option<String>,
    contract_hash: &str,
) -> TraceEntry {
    TraceEntry {
        node_id,
        action_name: entry.action_name.clone(),
        action_type: entry.action_type.clone(),
        declared: !(entry.decision == Decision::Denied && entry.reason.contains(UNDECLARED_MARKER)),
        result: match entry.decision {
            Decision::Allowed => TRACE_RESULT_ALLOWED.to_string(),
            Decision::Pending => TRACE_RESULT_PENDING_APPROVAL.to_string(),
            Decision::Denied => TRACE_RESULT_VIOLATION.to_string(),
        },
        hash_of_contract: contract_hash.to_string(),
        timestamp: entry.timestamp.clone(),
        reason: entry.reason.clone(),
        contract_field_reference: entry.contract_field_reference.clone(),
        provisional: if entry.provisional { Some(true) } else { None },
    }
}

// Trace entries are constructed directly (struct literal) by callers; there is
// deliberately no 10-argument builder helper.

#[cfg(test)]
mod tests {
    use super::*;

    const HASH: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    #[test]
    fn accepts_the_iso8601_subset() {
        assert!(is_iso_timestamp("2026-11-21T10:00:00Z"));
        assert!(is_iso_timestamp("2026-11-21"));
        assert!(is_iso_timestamp("2026-11-21 10:00"));
        assert!(is_iso_timestamp("2026-11-21T10:00:00.123456+05:30"));
        assert!(is_iso_timestamp("2026-11-21T10:00:00.5-0800"));
        assert!(!is_iso_timestamp("2026-02-30"));
        assert!(!is_iso_timestamp("2026-11-21T25:00:00Z"));
        assert!(!is_iso_timestamp("21-11-2026"));
        assert!(!is_iso_timestamp(""));
    }

    #[test]
    fn round_trips_full_and_draft_entries() {
        let full = TraceEntry {
            node_id: None,
            action_name: "github:issues:read".to_string(),
            action_type: "permission".to_string(),
            declared: true,
            result: "allowed".to_string(),
            hash_of_contract: HASH.to_string(),
            timestamp: "2026-11-21T10:00:00Z".to_string(),
            reason: "ok".to_string(),
            contract_field_reference: "permissions".to_string(),
            provisional: None,
        };
        let jsonl = TraceLog::new(vec![full.clone()]).to_jsonl();
        assert!(!jsonl.contains("provisional"));
        assert_eq!(
            TraceLog::from_jsonl(&jsonl).unwrap().entries,
            vec![full.clone()]
        );

        let draft = TraceEntry {
            provisional: Some(true),
            ..full
        };
        let jsonl = TraceLog::new(vec![draft.clone()]).to_jsonl();
        assert!(jsonl.contains("\"provisional\":true"));
        assert_eq!(TraceLog::from_jsonl(&jsonl).unwrap().entries, vec![draft]);
    }

    #[test]
    fn rejects_unknown_fields_and_bad_provisional() {
        let mut map = BTreeMap::new();
        map.insert("extra".to_string(), Json::Bool(true));
        let error = TraceEntry::from_dict(&Json::Object(map)).unwrap_err();
        assert!(error.message().contains("missing field"));

        let jsonl = format!(
            "{{\"action_name\":\"a\",\"action_type\":\"permission\",\"contract_field_reference\":\"permissions\",\"declared\":true,\"hash_of_contract\":\"{HASH}\",\"node_id\":null,\"provisional\":null,\"reason\":\"r\",\"result\":\"allowed\",\"timestamp\":\"2026-11-21T10:00:00Z\"}}"
        );
        let error = TraceLog::from_jsonl(&jsonl).unwrap_err();
        assert!(error.message().contains("must be a boolean"));
    }

    #[test]
    fn canonical_jsonl_is_sorted_and_compact() {
        let entry = TraceEntry {
            node_id: Some("node-1".to_string()),
            action_name: "a".to_string(),
            action_type: "permission".to_string(),
            declared: true,
            result: "allowed".to_string(),
            hash_of_contract: HASH.to_string(),
            timestamp: "2026-11-21T10:00:00Z".to_string(),
            reason: "réason".to_string(),
            contract_field_reference: "permissions".to_string(),
            provisional: Some(true),
        };
        let jsonl = TraceLog::new(vec![entry.clone()]).to_jsonl();
        assert!(jsonl.starts_with("{\"action_name\":\"a\",\"action_type\":\"permission\","));
        assert!(jsonl.contains("réason"));
        assert!(jsonl.ends_with("}\n"));
        assert_eq!(jsonl.matches('\n').count(), 1);
        let parsed = TraceLog::from_jsonl(&jsonl).unwrap();
        assert_eq!(parsed.entries[0].timestamp, entry.timestamp);
    }

    #[test]
    fn split_lines_normalizes_crlf_and_trailing_newline() {
        assert_eq!(split_lines("a\r\nb\n"), vec!["a", "b"]);
        assert_eq!(split_lines("a\rb"), vec!["a", "b"]);
        assert_eq!(split_lines(""), Vec::<&str>::new());
    }
}
