from __future__ import annotations

import pytest

from quantummindlite.openai_provider import OpenAIStructuredProvider


def test_live_provider_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTUMMINDLITE_LIVE_OPENAI", raising=False)
    with pytest.raises(RuntimeError):
        OpenAIStructuredProvider(model="test-model")
