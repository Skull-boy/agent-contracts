//! Gate integration tests: allow, deny, approval, draft-mode irreversibility,
//! tamper detection, guardrails, and the audit trail.

mod common;

use common::{fixed_clock, TempDir};
use scyvera_rs::contract::Mode;
use scyvera_rs::enforcer::{ActionType, ContractEnforcer, Decision};

fn load(directory: &TempDir, body: &str, mode: Mode) -> ContractEnforcer {
    let path = directory.write("contract.yaml", body);
    ContractEnforcer::load_with_clock(&path, mode, fixed_clock()).expect("contract loads")
}

const FULL: &str =
    "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\n\
                    permissions: [\"github:issues:read\"]\nside_effects: []\n";

#[test]
fn declared_permission_is_allowed_and_undeclared_is_denied() {
    let directory = TempDir::new("gate");
    let mut enforcer = load(&directory, FULL, Mode::Full);

    assert_eq!(
        enforcer
            .decide("github:issues:read", ActionType::Permission)
            .decision,
        Decision::Allowed
    );

    let outcome = enforcer.decide("github:issues:write", ActionType::Permission);
    assert_eq!(outcome.decision, Decision::Denied);
    let error = outcome.error.expect("denial carries an error");
    assert_eq!(error.code(), "ContractViolationError");
    assert!(error.message().contains("not declared"));

    let log = enforcer.audit_log();
    assert_eq!(log.len(), 2);
    assert_eq!(log[0].decision, Decision::Allowed);
    assert_eq!(log[1].decision, Decision::Denied);
    assert!(!log[1].provisional);
}

#[test]
fn side_effect_matching_accepts_the_declared_shape() {
    let directory = TempDir::new("gate");
    let mut enforcer = load(
        &directory,
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\npermissions: []\n\
         side_effects:\n  - resource: github\n    type: comment\n",
        Mode::Full,
    );
    assert_eq!(
        enforcer.decide("comment", ActionType::SideEffect).decision,
        Decision::Allowed
    );
    assert_eq!(
        enforcer
            .decide("delete_repo", ActionType::SideEffect)
            .decision,
        Decision::Denied
    );
}

#[test]
fn approval_point_pends_then_allows_after_approval() {
    let directory = TempDir::new("gate");
    let mut enforcer = load(
        &directory,
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\n\
         permissions: [\"prod:deploy\"]\napprovals:\n  - action: prod:deploy\n    required: true\n",
        Mode::Full,
    );

    let pending = enforcer.decide("prod:deploy", ActionType::Permission);
    assert_eq!(pending.decision, Decision::Pending);
    let error = pending.error.expect("pending carries an error");
    assert_eq!(error.code(), "ApprovalPendingError");
    assert!(error.message().contains("requires human approval"));

    enforcer.approve("prod:deploy", "");
    assert_eq!(
        enforcer
            .decide("prod:deploy", ActionType::Permission)
            .decision,
        Decision::Allowed
    );
}

#[test]
fn draft_mode_pends_on_irreversible_side_effects_only() {
    let body = concat!(
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\nprovisional: true\n",
        "permissions: []\nside_effects:\n",
        "  - resource: workspace\n    type: file_delete\n",
        "  - resource: cache\n    type: cache_write\n",
    );
    let directory = TempDir::new("gate");
    let mut draft = load(&directory, body, Mode::Draft);
    let irreversible = draft.decide("file_delete", ActionType::SideEffect);
    assert_eq!(irreversible.decision, Decision::Pending);
    assert_eq!(
        irreversible.error.as_ref().map(|error| error.code()),
        Some("ApprovalPendingError")
    );

    assert_eq!(
        draft.decide("cache_write", ActionType::SideEffect).decision,
        Decision::Allowed
    );

    draft.approve("file_delete", "");
    assert_eq!(
        draft.decide("file_delete", ActionType::SideEffect).decision,
        Decision::Allowed
    );
}

#[test]
fn full_mode_allows_an_irreversible_side_effect_without_approval() {
    let directory = TempDir::new("gate");
    let mut enforcer = load(
        &directory,
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\npermissions: []\n\
         side_effects:\n  - resource: workspace\n    type: file_delete\n",
        Mode::Full,
    );
    assert_eq!(
        enforcer
            .decide("file_delete", ActionType::SideEffect)
            .decision,
        Decision::Allowed
    );
}

#[test]
fn tampering_after_load_is_denied() {
    let directory = TempDir::new("gate");
    let path = directory.write("contract.yaml", FULL);
    let mut enforcer =
        ContractEnforcer::load_with_clock(&path, Mode::Full, fixed_clock()).expect("loads");

    let mut bytes = std::fs::read(&path).unwrap();
    bytes.extend_from_slice(b"\n# tampered\n");
    std::fs::write(&path, bytes).unwrap();

    let outcome = enforcer.decide("github:issues:read", ActionType::Permission);
    assert_eq!(outcome.decision, Decision::Denied);
    let error = outcome.error.expect("denial");
    assert_eq!(error.code(), "ContractViolationError");
    assert!(error.message().contains("tampered"));
}

#[test]
fn guardrail_budget_denies_the_second_side_effect() {
    let directory = TempDir::new("gate");
    let mut enforcer = load(
        &directory,
        "version: 1.2\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\npermissions: []\n\
         side_effects:\n  - resource: github\n    type: comment\n\
         guardrails:\n  budgets:\n    side_effects_per_window: 1\n    window: \"1h\"\n",
        Mode::Full,
    );

    assert_eq!(
        enforcer.decide("comment", ActionType::SideEffect).decision,
        Decision::Allowed
    );
    let denied = enforcer.decide("comment", ActionType::SideEffect);
    assert_eq!(denied.decision, Decision::Denied);
    let error = denied.error.expect("denial");
    assert_eq!(error.code(), "GuardrailViolationError");
    assert!(error
        .message()
        .contains("Guardrail 'budgets' denied action"));
}

#[test]
fn rate_limit_counts_every_gated_attempt() {
    let directory = TempDir::new("gate");
    let mut enforcer = load(
        &directory,
        "version: 1.2\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\n\
         permissions: [\"github:issues:read\"]\n\
         guardrails:\n  rate_limit:\n    max_calls_per_minute: 1\n",
        Mode::Full,
    );
    // The first attempt is admitted; the second exceeds the limit.
    let _ = enforcer.decide("github:issues:read", ActionType::Read);
    let denied = enforcer.decide("github:issues:read", ActionType::Read);
    assert_eq!(denied.decision, Decision::Denied);
    assert_eq!(
        denied.error.as_ref().map(|error| error.code()),
        Some("GuardrailViolationError")
    );
}

#[test]
fn read_is_an_alias_for_permission() {
    let directory = TempDir::new("gate");
    let mut enforcer = load(&directory, FULL, Mode::Full);
    assert_eq!(
        enforcer
            .decide("github:issues:read", ActionType::Read)
            .decision,
        Decision::Allowed
    );
    assert_eq!(
        enforcer
            .audit_log()
            .last()
            .map(|entry| entry.action_type.clone()),
        Some("permission".to_string())
    );
}

#[test]
fn identity_is_pinned_to_the_canonical_path() {
    let directory = TempDir::new("gate");
    let path = directory.write("contract.yaml", FULL);
    let enforcer =
        ContractEnforcer::load_with_clock(&path, Mode::Full, fixed_clock()).expect("loads");
    assert_eq!(
        enforcer.contract_path().canonicalize().unwrap(),
        path.canonicalize().unwrap()
    );
    assert_eq!(enforcer.integrity_hash().len(), 64);
    assert!(!enforcer.is_provisional());
}
