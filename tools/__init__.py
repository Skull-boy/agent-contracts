"""Release-time helpers for RFC 0003 §C2/§C6 distribution attestation.

These scripts are build/release tooling, not import-time runtime code. They are
stdlib-only (plus the in-package self-check engine) and exist so the release
workflow can generate the self manifest, CycloneDX SBOM, and signed release
manifest without pulling in a third-party SBOM or signing tool.
"""
