from __future__ import annotations

from pathlib import Path

from quantummindlite.evaluation import PUBLIC_FORBIDDEN_TERMS, load_manifest, load_public_case
from quantummindlite.registry import project_root, resource_root
from quantummindlite.validation import RULE_IDS


def test_public_files_have_no_answer_or_source_clues() -> None:
    for case_id in load_manifest()["ready_cases"]:
        text = load_public_case(case_id).model_dump_json().lower()
        for term in PUBLIC_FORBIDDEN_TERMS:
            assert term not in text


def test_registry_prompts_and_rules_have_no_case_ids_or_gold_paths() -> None:
    root = resource_root()
    registry_text = (root / "configs" / "primitives.yaml").read_text(encoding="utf-8")
    assert "QM-PB-" not in registry_text
    assert "paperbench/gold" not in registry_text.lower()
    for prompt in (root / "prompts").glob("*.md"):
        text = prompt.read_text(encoding="utf-8")
        assert "QM-PB-" not in text
        assert "expected_primitive" not in text
        assert "official_url" not in text
    assert len(RULE_IDS) == 10
    assert all("QM-PB-" not in rule for rule in RULE_IDS)


def test_no_old_quantummind_import_or_runtime_path() -> None:
    root = project_root()
    for path in (root / "src" / "quantummindlite").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "projects\\\\QuantumMind" not in text
        assert "projects/QuantumMind" not in text
        assert "import quantummind " not in text
        assert "from quantummind " not in text


def test_no_secret_literals() -> None:
    root = project_root()
    for path in list((root / "src").rglob("*.py")) + list((root / "tests").rglob("*.py")):
        text = Path(path).read_text(encoding="utf-8")
        assert ("s" + "k-") not in text
        assert ("OPENAI_API_KEY" + "=") not in text
