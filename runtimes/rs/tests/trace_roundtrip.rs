//! Trace integration tests: canonical JSONL, the additive `provisional` field,
//! and fail-closed parsing.

mod common;

use scyvera_rs::enforcer::{AuditEntry, Decision};
use scyvera_rs::trace::{is_iso_timestamp, trace_from_audit, TraceEntry, TraceLog};

const HASH: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn entry(result: &str, provisional: Option<bool>) -> TraceEntry {
    TraceEntry {
        node_id: Some("node-1".to_string()),
        action_name: "github:issues:read".to_string(),
        action_type: "permission".to_string(),
        declared: true,
        result: result.to_string(),
        hash_of_contract: HASH.to_string(),
        timestamp: "2026-11-21T10:00:00Z".to_string(),
        reason: "ok".to_string(),
        contract_field_reference: "permissions".to_string(),
        provisional,
    }
}

#[test]
fn full_mode_roundtrip_omits_provisional() {
    let log = TraceLog::new(vec![entry("allowed", None)]);
    let jsonl = log.to_jsonl();
    assert!(!jsonl.contains("provisional"));
    assert_eq!(TraceLog::from_jsonl(&jsonl).unwrap(), log);
}

#[test]
fn draft_mode_roundtrip_emits_provisional_true() {
    let log = TraceLog::new(vec![entry("allowed", Some(true))]);
    let jsonl = log.to_jsonl();
    assert!(jsonl.contains("\"provisional\":true"));
    assert_eq!(TraceLog::from_jsonl(&jsonl).unwrap(), log);
}

#[test]
fn absent_provisional_parses_as_full_mode() {
    let jsonl = TraceLog::new(vec![entry("allowed", None)]).to_jsonl();
    let parsed = TraceLog::from_jsonl(&jsonl).unwrap();
    assert_eq!(parsed.entries[0].provisional, None);
}

#[test]
fn null_and_string_provisional_are_rejected() {
    for bad in ["null", "\"true\""] {
        let jsonl = format!(
            "{{\"action_name\":\"a\",\"action_type\":\"permission\",\
             \"contract_field_reference\":\"permissions\",\"declared\":true,\
             \"hash_of_contract\":\"{HASH}\",\"node_id\":null,\"provisional\":{bad},\
             \"reason\":\"r\",\"result\":\"allowed\",\
             \"timestamp\":\"2026-11-21T10:00:00Z\"}}"
        );
        let error = TraceLog::from_jsonl(&jsonl).unwrap_err();
        assert_eq!(error.code(), "TraceError");
        assert!(error.message().contains("must be a boolean"));
    }
}

#[test]
fn unknown_fields_are_rejected() {
    let jsonl = format!(
        "{{\"action_name\":\"a\",\"action_type\":\"permission\",\
         \"contract_field_reference\":\"permissions\",\"declared\":true,\
         \"hash_of_contract\":\"{HASH}\",\"node_id\":null,\"reason\":\"r\",\
         \"result\":\"allowed\",\"timestamp\":\"2026-11-21T10:00:00Z\",\"extra\":1}}"
    );
    let error = TraceLog::from_jsonl(&jsonl).unwrap_err();
    assert!(error.message().contains("unknown field"));
}

#[test]
fn bad_hash_timestamp_and_result_are_rejected() {
    let bad_hash = TraceLog::new(vec![TraceEntry {
        hash_of_contract: "zz".to_string(),
        ..entry("allowed", None)
    }])
    .to_jsonl();
    assert!(TraceLog::from_jsonl(&bad_hash)
        .unwrap_err()
        .message()
        .contains("hexadecimal"));

    let bad_timestamp = TraceLog::new(vec![TraceEntry {
        timestamp: "21/11/2026".to_string(),
        ..entry("allowed", None)
    }])
    .to_jsonl();
    assert!(TraceLog::from_jsonl(&bad_timestamp)
        .unwrap_err()
        .message()
        .contains("ISO-8601"));

    let bad_result = TraceLog::new(vec![entry("maybe", None)]).to_jsonl();
    assert!(TraceLog::from_jsonl(&bad_result)
        .unwrap_err()
        .message()
        .contains("result"));
}

#[test]
fn timestamps_accept_the_reference_subset() {
    assert!(is_iso_timestamp("2026-11-21T10:00:00Z"));
    assert!(is_iso_timestamp("2026-11-21T10:00:00.123456+05:30"));
    assert!(!is_iso_timestamp("2026-13-01T00:00:00Z"));
    assert!(!is_iso_timestamp("2026-02-30T00:00:00Z"));
}

#[test]
fn trace_from_audit_derives_declared_and_result() {
    let allowed = AuditEntry {
        timestamp: "2026-11-21T10:00:00Z".to_string(),
        action_name: "github:issues:read".to_string(),
        action_type: "permission".to_string(),
        decision: Decision::Allowed,
        reason: "Action 'github:issues:read' matched declared contract specification.".to_string(),
        contract_field_reference: "permissions".to_string(),
        provisional: false,
    };
    let trace = trace_from_audit(&allowed, Some("node-1".to_string()), HASH);
    assert!(trace.declared);
    assert_eq!(trace.result, "allowed");
    assert_eq!(trace.provisional, None);

    let denied = AuditEntry {
        decision: Decision::Denied,
        reason: "Action 'x' is not declared in 'permissions'.".to_string(),
        ..allowed
    };
    let trace = trace_from_audit(&denied, None, HASH);
    assert!(!trace.declared);
    assert_eq!(trace.result, "violation");
}

#[test]
fn empty_log_and_empty_lines() {
    assert_eq!(TraceLog::from_jsonl("").unwrap().entries, Vec::new());
    assert!(TraceLog::from_jsonl("\n")
        .unwrap_err()
        .message()
        .contains("empty line"));

    let valid = TraceLog::new(vec![entry("allowed", None)]).to_jsonl();
    let with_blank = format!("{valid}\n");
    assert!(TraceLog::from_jsonl(&with_blank)
        .unwrap_err()
        .message()
        .contains("empty line"));
}
