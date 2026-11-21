//! Contract-model integration tests: load modes, wildcards, identity, and the
//! monorepo schema guarantee.

mod common;

use std::path::{Path, PathBuf};

use common::TempDir;
use scyvera_rs::contract::{load_contract_file, validate_file, Mode};
use scyvera_rs::json::compact;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn repo_root() -> PathBuf {
    manifest_dir()
        .parent()
        .and_then(Path::parent)
        .expect("runtimes/rs has two parents")
        .to_path_buf()
}

#[test]
fn copied_schemas_match_the_python_reference() {
    let root = repo_root();
    for version in ["v1", "v1.1", "v1.2"] {
        let reference = root
            .join("schemas")
            .join(version)
            .join("contract.schema.json");
        if !reference.exists() {
            // Packaged crate: the monorepo layout is absent by design.
            continue;
        }
        let copy = manifest_dir()
            .join("schemas")
            .join(version)
            .join("contract.schema.json");
        let expected = std::fs::read(&reference).expect("reference schema is readable");
        let actual = std::fs::read(&copy).expect("copied schema is readable");
        assert_eq!(
            expected, actual,
            "{version} schema copy drifted from schemas/{version}/contract.schema.json"
        );
    }
}

#[test]
fn full_mode_rejects_a_provisional_contract_and_draft_mode_loads_it() {
    let directory = TempDir::new("contract-model");
    let path = directory.write(
        "contract.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\nprovisional: true\n\
         permissions: [\"github:issues:read\"]\n",
    );

    let error = load_contract_file(&path, Mode::Full).unwrap_err();
    assert_eq!(error.code(), "ProvisionalContractError");
    assert!(error.message().contains("promotion"));

    let loaded = load_contract_file(&path, Mode::Draft).expect("draft mode loads");
    assert!(loaded.is_provisional());
    assert_eq!(loaded.mode, Mode::Draft);
    assert_eq!(loaded.integrity_hash.len(), 64);
}

#[test]
fn draft_mode_is_not_a_relaxed_mode() {
    let directory = TempDir::new("contract-model");
    let path = directory.write(
        "contract.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\npermissions: []\n",
    );
    let error = load_contract_file(&path, Mode::Draft).unwrap_err();
    assert_eq!(error.code(), "ContractValidationError");
    assert!(error.message().contains("not provisional"));
}

#[test]
fn wildcard_permissions_are_refused_on_load() {
    let directory = TempDir::new("contract-model");
    let path = directory.write(
        "contract.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\npermissions: [\"all\"]\n",
    );
    let error = load_contract_file(&path, Mode::Full).unwrap_err();
    assert!(error.message().contains("Wildcard permission"));
    assert!(error.message().contains("T7"));
}

#[test]
fn lifecycle_defaults_are_applied_after_validation() {
    let directory = TempDir::new("contract-model");
    let path = directory.write(
        "contract.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\npermissions: []\n",
    );
    let loaded = load_contract_file(&path, Mode::Full).expect("loads");
    assert_eq!(
        compact(loaded.contract.get("lifecycle").expect("defaulted")),
        "{\"initiation\":\"human-only\",\"mode\":\"request-response\",\"resumability\":\"stateless\"}"
    );
}

#[test]
fn yml_suffix_is_rejected() {
    let directory = TempDir::new("contract-model");
    let path = directory.write(
        "contract.yml",
        "version: 1.1\nsystem:\n  name: vector-agent\npermissions: []\n",
    );
    let error = validate_file(&path).unwrap_err();
    assert!(error.message().contains("rename to contract.yaml"));
}

#[test]
fn identity_hash_covers_the_exact_bytes() {
    let directory = TempDir::new("contract-model");
    let path = directory.write(
        "contract.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\npermissions: []\n",
    );
    let loaded = load_contract_file(&path, Mode::Full).expect("loads");
    let expected = scyvera_rs::sha256::hex_digest(&std::fs::read(&path).unwrap());
    assert_eq!(loaded.integrity_hash, expected);
    assert_eq!(
        loaded.contract_path.canonicalize().unwrap(),
        path.canonicalize().unwrap()
    );
}

#[test]
fn v1_contracts_do_not_gain_a_lifecycle_block() {
    let directory = TempDir::new("contract-model");
    let path = directory.write(
        "contract.yaml",
        "version: 1\nworkflow: demo\npermissions: []\nside_effects: []\n\
         approval_points: []\ndependencies: []\ninputs: []\noutputs: []\n\
         observability: []\nrecovery_strategy: retry\nreplay_semantics: idempotent\n\
         state: none\n",
    );
    let loaded = load_contract_file(&path, Mode::Full).expect("v1 loads");
    assert!(loaded.contract.get("lifecycle").is_none());
}

#[cfg(unix)]
#[test]
fn t14_symlink_escape_is_refused() {
    use std::os::unix::fs::symlink;

    let outside = TempDir::new("contract-outside");
    let target = outside.write(
        "real.yaml",
        "version: 1.1\nsystem:\n  name: vector-agent\nlifecycle:\n  mode: request-response\npermissions: []\n",
    );
    let inside = TempDir::new("contract-inside");
    let link = inside.join("contract.yaml");
    symlink(&target, &link).expect("symlink");

    let error = load_contract_file(&link, Mode::Full).unwrap_err();
    assert!(error.message().contains("T14"), "{}", error.message());
}
