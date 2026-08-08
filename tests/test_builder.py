from pathlib import Path
import tempfile
import yaml

from scyvera import Contract, validate_contract


def test_builder_minimal_contract():
    contract = Contract(name="Minimal Builder System").set_domain("education")
    data = contract.to_dict()

    assert data["version"] == 1.1
    assert data["system"]["name"] == "Minimal Builder System"
    assert data["domain"] == "education"

    res = contract.validate()
    assert res.valid is True
    assert res.errors == ()


def test_builder_full_contract_chaining():
    c = (
        Contract(
            name="Clinical Research Tutor",
            purpose="Assists medical students with clinical paper analysis",
            system_version="1.0.0",
        )
        .add_capability("analyze_papers", description="Analyzes medical literature")
        .add_resource("clinical_papers", type="pdf_store", access="read")
        .add_input("query", type="text", required=True)
        .add_output("summary", type="document")
        .add_permission("clinical_papers", actions=["read", "search"])
        .add_constraint("rate_limit", maximum=30, unit="requests_per_minute")
        .add_side_effect("audit_log", resource="clinical_papers")
        .add_approval("export_notes", required=True, approver="clinical_instructor")
        .add_dependency("pubmed_api", type="api", required=True)
        .set_state("session")
        .set_recovery("human_escalation")
        .set_replay("idempotent")
        .set_observability("audit", sinks=["system_log"])
        .add_artifact("paper_summarizer", type="model", integrity_required=True)
        .set_risk("medium", category="medical_education")
        .set_implementation(framework="langgraph", language="python")
    )

    res = c.validate()
    assert res.valid is True
    assert res.errors == ()

    yaml_str = c.to_yaml()
    assert "Clinical Research Tutor" in yaml_str
    assert "analyze_papers" in yaml_str


def test_builder_save_and_validate():
    c = Contract(name="File Saver Agent", purpose="Tests file saving")
    c.add_capability("save_files")

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "contract.yaml"
        saved_path = c.save(file_path)

        assert saved_path.exists()
        res = validate_contract(saved_path)
        assert res.valid is True
