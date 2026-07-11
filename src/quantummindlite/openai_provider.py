from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, ValidationError

from .llm import ProviderError, ProviderResult, ProviderTrace
from .messages import ActionType, Role


class OpenAIStructuredProvider:
    provider_name = "openai"

    def __init__(
        self,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts not in {1, 2}:
            raise ValueError("OpenAI provider allows at most two attempts")
        if client is None and os.environ.get("QUANTUMMINDLITE_LIVE_OPENAI") != "1":
            raise RuntimeError("live OpenAI calls require QUANTUMMINDLITE_LIVE_OPENAI=1")
        self.model_name = model or os.environ.get("QUANTUMMINDLITE_OPENAI_MODEL", "")
        if not self.model_name:
            raise RuntimeError("OpenAI provider requires --model or QUANTUMMINDLITE_OPENAI_MODEL")
        self.reasoning_effort = reasoning_effort or os.environ.get("QUANTUMMINDLITE_REASONING_EFFORT")
        self.timeout = timeout
        self.client = client or self._new_client()
        self.max_attempts = max_attempts

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        last_error: ProviderError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._generate_once(role, action, prompt, inputs, output_model, attempt)
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.max_attempts:
                    raise
            except Exception as exc:
                retryable = _is_transient(exc)
                trace = ProviderTrace(
                    provider=self.provider_name,
                    model=self.model_name,
                    attempt_count=attempt,
                    status="transport_error",
                    parse_status="not_started",
                )
                last_error = ProviderError(f"OpenAI transport failure: {exc!r}", trace, retryable=retryable)
                if not retryable or attempt >= self.max_attempts:
                    raise last_error from exc
        if last_error is None:
            raise AssertionError("unreachable OpenAI retry state")
        raise last_error

    def _generate_once(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
        attempt: int,
    ) -> ProviderResult:
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "instructions": prompt,
            "input": json.dumps({"role": role.value, "action": action.value, "inputs": inputs}, sort_keys=True),
            "text_format": output_model,
            "store": False,
        }
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        response = self.client.responses.parse(**kwargs)
        model = str(getattr(response, "model", self.model_name))
        usage = _usage_dict(getattr(response, "usage", None))
        status = str(getattr(response, "status", "completed"))
        refusal = _extract_refusal(response)
        incomplete = _incomplete_reason(response, status)
        trace = ProviderTrace(
            provider=self.provider_name,
            model=model,
            usage=usage,
            attempt_count=attempt,
            status="ok",
            parse_status="ok",
            refusal=refusal,
            incomplete_reason=incomplete,
        )
        if refusal:
            raise ProviderError("OpenAI response refused the request", trace_with(trace, status="refusal"), retryable=False)
        if incomplete:
            raise ProviderError(
                "OpenAI response was incomplete",
                trace_with(trace, status="incomplete", parse_status="not_started"),
                retryable=True,
            )
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise ProviderError(
                "OpenAI response did not contain output_parsed",
                trace_with(trace, status="parse_error", parse_status="missing_output_parsed"),
                retryable=True,
            )
        try:
            model_output = parsed if isinstance(parsed, BaseModel) else output_model.model_validate(parsed)
            return ProviderResult(model_output.model_dump(mode="json"), trace)
        except ValidationError as exc:
            raise ProviderError(
                f"OpenAI structured output failed schema validation: {exc}",
                trace_with(trace, status="parse_error", parse_status="schema_error"),
                retryable=True,
            ) from exc

    def _new_client(self) -> Any:
        from openai import OpenAI

        return OpenAI()


def trace_with(trace: ProviderTrace, **updates: Any) -> ProviderTrace:
    return ProviderTrace(
        provider=str(updates.get("provider", trace.provider)),
        model=str(updates.get("model", trace.model)),
        usage=_dict_or_none(updates.get("usage", trace.usage)),
        attempt_count=int(updates.get("attempt_count", trace.attempt_count)),
        status=str(updates.get("status", trace.status)),
        refusal=_str_or_none(updates.get("refusal", trace.refusal)),
        incomplete_reason=_str_or_none(updates.get("incomplete_reason", trace.incomplete_reason)),
        parse_status=str(updates.get("parse_status", trace.parse_status)),
    )


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        result = dump(mode="json")
        return result if isinstance(result, dict) else None
    return None


def _extract_refusal(response: Any) -> str | None:
    direct = getattr(response, "refusal", None)
    if direct:
        return str(direct)
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            refusal = getattr(content, "refusal", None)
            if refusal:
                return str(refusal)
            if getattr(content, "type", None) == "refusal":
                text = getattr(content, "text", None)
                return str(text or "refusal")
    return None


def _incomplete_reason(response: Any, status: str) -> str | None:
    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None) if details is not None else None
    if reason:
        return str(reason)
    return "incomplete" if status == "incomplete" else None


def _is_transient(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    return isinstance(exc, TimeoutError) or "timeout" in name or "ratelimit" in name or "connection" in name
