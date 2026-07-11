from __future__ import annotations

from quantummindlite.cli import count_loc


def test_production_loc_budget() -> None:
    result = count_loc()
    assert result["ok"], result
    assert "_graph_projection.py" in result["per_file"]
