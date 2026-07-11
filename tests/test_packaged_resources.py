from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from quantummindlite.evaluation import load_public_case


def _run_cli(tmp_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    return subprocess.run(
        [sys.executable, "-m", "quantummindlite.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def test_cli_finds_packaged_resources_outside_repo(tmp_path: Path) -> None:
    validation = _run_cli(tmp_path, "validate-paperbench", check=False)
    payload = json.loads(validation.stdout)
    assert validation.returncode == 0 or all(error.startswith("freeze ") for error in payload["errors"])

    out = tmp_path / "runs"
    benchmark = _run_cli(tmp_path, "benchmark", "--case-id", "QM-PB-001", "--output-dir", str(out / "benchmark"))
    assert '"system_pass": true' in benchmark.stdout

    case_path = tmp_path / "case.yaml"
    case_path.write_text(yaml.safe_dump(load_public_case("QM-PB-001").model_dump(mode="json")), encoding="utf-8")
    analyze = _run_cli(tmp_path, "analyze", "--input", str(case_path), "--provider", "mock", "--output-dir", str(out / "analyze"))
    assert (Path(analyze.stdout.strip()) / "decision.json").exists()
