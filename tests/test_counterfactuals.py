from __future__ import annotations

import shutil
from pathlib import Path

from quantummindlite.cli import score_family, validate_family
from quantummindlite.evaluation import PublicCase
from quantummindlite.models import DecisionCard, RunState
from quantummindlite.registry import resource_root
from quantummindlite.workflow import Orchestrator


def test_counterfactual_families_respect_opportunity_downgrade(tmp_path: Path) -> None:
    def run_variant(public: PublicCase) -> tuple[RunState, DecisionCard]:
        result = Orchestrator().run(public.model_dump(mode="json"), output_dir=tmp_path)
        return result.state, result.decision

    for family_id in ("PB-001-family", "PB-006-family"):
        assert validate_family(None, family_id)["ok"]
        score = score_family(None, family_id, run_variant)
        if family_id == "PB-006-family":
            assert score["family_exact"], score
            continue
        misses = [item for item in score["details"] if not item["pair_exact"] and not item["diagnostic_only"]]
        assert [item["variant_id"] for item in misses] == ["no_coherent_oracle"], score
        assert misses[0]["predicted_relation"] == "WEAKEN"


def test_family_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    root = resource_root()
    shutil.copytree(root / "paperbench", tmp_path / "paperbench")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tmp'\n", encoding="utf-8")
    shutil.copytree(root / "configs", tmp_path / "configs")
    public = tmp_path / "paperbench" / "families" / "public" / "PB-001-family.yaml"
    public.write_text(
        public.read_text(encoding="utf-8").replace("return any marked item", "return all marked items"),
        encoding="utf-8",
    )
    result = validate_family(tmp_path, "PB-001-family")
    assert not result["ok"]
    assert "digest mismatch" in " ".join(result["errors"])
