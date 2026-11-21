//! The real conformance suite: every vector, at the pinned version, through the
//! native Rust runner.

mod common;

use std::path::PathBuf;

use scyvera_rs::vectors::{
    category_counts, load_suite, run_suite, CATEGORIES, PINNED_SUITE_VERSION,
};

fn vectors_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("vectors")
}

fn suite() -> scyvera_rs::vectors::VectorSuite {
    load_suite(&vectors_root()).expect("the shared suite loads")
}

#[test]
fn suite_is_pinned_and_complete() {
    let suite = suite();
    assert_eq!(suite.suite_version, PINNED_SUITE_VERSION);
    assert_eq!(suite.suite_version, 1);
    assert_eq!(suite.vectors.len(), 33);

    let counts: Vec<(String, usize)> = category_counts(&suite)
        .into_iter()
        .map(|(category, ids)| (category.to_string(), ids.len()))
        .collect();
    assert_eq!(
        counts,
        vec![
            ("contract-model".to_string(), 11),
            ("gate-decision".to_string(), 13),
            ("trace-roundtrip".to_string(), 9),
        ]
    );
    assert_eq!(CATEGORIES.len(), 3);
}

#[test]
fn every_vector_passes() {
    let suite = suite();
    let run = run_suite(&suite, None).expect("the suite runs");
    assert_eq!(run.total, 33);
    assert_eq!(run.passed, 33, "failures: {:?}", run.failures);
    assert_eq!(run.failed, 0);
    assert!(run.failures.is_empty());
}

#[test]
fn each_category_passes_on_its_own() {
    let suite = suite();
    for category in CATEGORIES {
        let run = run_suite(&suite, Some(category)).expect("category runs");
        assert!(run.total > 0, "{category} selected no vectors");
        assert_eq!(run.failed, 0, "{category} failures: {:?}", run.failures);
    }
}

#[test]
fn the_run_is_deterministic() {
    let suite = suite();
    let first = run_suite(&suite, None).unwrap().to_json();
    let second = run_suite(&suite, None).unwrap().to_json();
    assert_eq!(first, second);
    assert!(first.starts_with("{\"failed\":0,"));
    assert!(first.ends_with("}\n"));
    assert!(first.contains("\"suite_version\":1"));
    assert!(first.contains("\"total\":33"));
}

#[test]
fn unknown_categories_fail_closed() {
    let suite = suite();
    let error = run_suite(&suite, Some("promotion")).unwrap_err();
    assert_eq!(error.code(), "VectorSuiteError");
    assert!(error.message().contains("unknown category"));
}

#[test]
fn unsupported_contract_surface_is_not_silently_skipped() {
    // RFC 0005 §6.10 keeps promotion and audit out of the cross-runtime suite.
    // The runner must still execute all three categories: a suite that lost one
    // would be a configuration error, not a smaller conformance claim.
    let suite = suite();
    for category in CATEGORIES {
        assert!(
            suite
                .vectors
                .iter()
                .any(|vector| vector.category == category),
            "{category} is empty in the suite"
        );
    }
}
