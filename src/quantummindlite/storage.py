from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def digest_json(data: Any) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class RunStore:
    run_dir: Path
    run_id: str

    @classmethod
    def create(cls, output_dir: Path, run_id: str | None = None) -> RunStore:
        run_id = run_id or "qml-" + uuid.uuid4().hex[:12]
        run_dir = output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
        return cls(run_dir=run_dir, run_id=run_id)

    def write_json(self, name: str, data: Any) -> None:
        if name not in {
            "input.json",
            "state.json",
            "decision.json",
            "score.json",
            "partial_state.json",
            "error.json",
            "evidence_graph.json",
            "graph_verifier_report.json",
            "graph_summary.json",
        }:
            raise ValueError("runs may only write configured artifact files")
        path = self.run_dir / name
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def append_trace(self, item: dict[str, Any]) -> None:
        path = self.run_dir / "trace.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
