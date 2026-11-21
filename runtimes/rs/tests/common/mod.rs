//! Shared helpers for the integration tests.
//!
//! Deliberately dependency-free: the runtime itself must not grow a tempdir
//! crate, and neither should its tests.

#![allow(dead_code)]

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

static COUNTER: AtomicU64 = AtomicU64::new(0);

pub struct TempDir {
    pub path: PathBuf,
}

impl TempDir {
    pub fn new(label: &str) -> TempDir {
        let path = std::env::temp_dir().join(format!(
            "scyvera-rs-test-{label}-{}-{}",
            std::process::id(),
            COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&path).expect("scratch dir");
        TempDir { path }
    }

    pub fn write(&self, name: &str, body: &str) -> PathBuf {
        let target = self.path.join(name);
        std::fs::write(&target, body).expect("write scratch file");
        target
    }

    pub fn join(&self, name: &str) -> PathBuf {
        self.path.join(name)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

/// A fixed clock: 2026-11-21T00:00:00Z in microseconds.
pub const FIXED_MICROS: i64 = 1_795_219_200_000_000;

pub fn fixed_clock() -> scyvera_rs::enforcer::Clock {
    Box::new(|| FIXED_MICROS)
}
