from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from quantummindlite.llm import ProviderError
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import FormalizationOutput
from quantummindlite.openai_provider import OpenAIStructuredProvider


class FakeResponses:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.responses = FakeResponses(outcomes)


def _formalization_payload() -> FormalizationOutput:
    return FormalizationOutput(ambiguities=["oracle construction cost is unspecified"])


def _provider(outcomes: list[Any]) -> tuple[OpenAIStructuredProvider, FakeClient]:
    client = FakeClient(outcomes)
    return OpenAIStructuredProvider(model="test-model", client=client), client


def test_structured_output_parsed_success() -> None:
    provider, client = _provider([SimpleNamespace(output_parsed=_formalization_payload(), model="actual-model", status="completed")])
    result = provider.generate(Role.FORMALIZER, ActionType.FORMALIZE, "prompt", {"public_case": {}}, FormalizationOutput)
    assert result.payload["ambiguities"] == ["oracle construction cost is unspecified"]
    assert result.trace.model == "actual-model"
    assert client.responses.calls[0]["text_format"] is FormalizationOutput


def test_refusal_is_typed_and_not_retried() -> None:
    provider, client = _provider([SimpleNamespace(output_parsed=None, model="m", status="completed", refusal="no")])
    with pytest.raises(ProviderError) as exc:
        provider.generate(Role.FORMALIZER, ActionType.FORMALIZE, "prompt", {}, FormalizationOutput)
    assert exc.value.trace.status == "refusal"
    assert len(client.responses.calls) == 1


def test_incomplete_response_retries_once_then_fails() -> None:
    incomplete = SimpleNamespace(
        output_parsed=None,
        model="m",
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
    )
    provider, client = _provider([incomplete, incomplete])
    with pytest.raises(ProviderError) as exc:
        provider.generate(Role.FORMALIZER, ActionType.FORMALIZE, "prompt", {}, FormalizationOutput)
    assert exc.value.trace.status == "incomplete"
    assert exc.value.trace.attempt_count == 2
    assert len(client.responses.calls) == 2


def test_malformed_schema_retries_once_then_fails() -> None:
    malformed = SimpleNamespace(output_parsed={"statement": "missing required fields"}, model="m", status="completed")
    provider, client = _provider([malformed, malformed])
    with pytest.raises(ProviderError) as exc:
        provider.generate(Role.FORMALIZER, ActionType.FORMALIZE, "prompt", {}, FormalizationOutput)
    assert exc.value.trace.status == "parse_error"
    assert exc.value.trace.parse_status == "schema_error"
    assert len(client.responses.calls) == 2


def test_transient_retry_success_and_no_third_attempt() -> None:
    provider, client = _provider(
        [TimeoutError("slow"), TimeoutError("still slow"), SimpleNamespace(output_parsed=_formalization_payload())]
    )
    with pytest.raises(ProviderError) as exc:
        provider.generate(Role.FORMALIZER, ActionType.FORMALIZE, "prompt", {}, FormalizationOutput)
    assert exc.value.trace.status == "transport_error"
    assert len(client.responses.calls) == 2

    retry_provider, retry_client = _provider([TimeoutError("slow"), SimpleNamespace(output_parsed=_formalization_payload())])
    result = retry_provider.generate(Role.FORMALIZER, ActionType.FORMALIZE, "prompt", {}, FormalizationOutput)
    assert result.trace.attempt_count == 2
    assert len(retry_client.responses.calls) == 2
