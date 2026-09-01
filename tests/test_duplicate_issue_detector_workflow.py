import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "implementations" / "n8n" / "duplicate-issue-detector" / "workflow.json"
README_PATH = ROOT / "implementations" / "n8n" / "duplicate-issue-detector" / "README.md"


def _workflow() -> dict:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _node(workflow: dict, name: str) -> dict:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def _targets(workflow: dict, source: str) -> set[str]:
    return {
        edge["node"]
        for output in workflow["connections"][source]["main"]
        for edge in output
    }


def test_duplicate_detector_supports_swappable_ollama_embeddings():
    workflow = _workflow()
    live_ollama = _node(workflow, "Embed New Issue (Ollama)")
    backfill_ollama = _node(workflow, "Embed Issue (Ollama)")

    for node in (live_ollama, backfill_ollama):
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert node["disabled"] is True
        assert node["parameters"]["url"] == "=REPLACE_OLLAMA_BASE_URL/api/embed"
        assert 'model: "nomic-embed-text"' in node["parameters"]["jsonBody"]

    assert _targets(workflow, "Prepare Issue Text") == {
        "Embed New Issue (OpenAI)",
        "Embed New Issue (Ollama)",
    }
    assert _targets(workflow, "Prepare Issue Text (Backfill)") == {
        "Embed Issue (OpenAI)",
        "Embed Issue (Ollama)",
    }
    assert _targets(workflow, "Embed New Issue (Ollama)") == {"Extract Vector"}
    assert _targets(workflow, "Embed Issue (Ollama)") == {"Extract Vector (Backfill)"}

    for name in ("Extract Vector", "Extract Vector (Backfill)"):
        code = _node(workflow, name)["parameters"]["jsCode"]
        assert "data?.[0]?.embedding" in code
        assert "embeddings?.[0]" in code
        assert "Embedding response did not contain a vector" in code

    readme = README_PATH.read_text(encoding="utf-8")
    assert "REPLACE_OLLAMA_BASE_URL" in readme
    assert "768" in readme
    assert "Do not leave both providers enabled" in readme
