from __future__ import annotations

from pathlib import Path
from typing import Any

from .llm import LLMProvider, ProviderTrace
from .messages import ActionSpec, Message, Role


class Agent:
    def __init__(self, spec: ActionSpec, provider: LLMProvider, prompt_path: Path) -> None:
        self.spec = spec
        self.role: Role = spec.role
        self.provider = provider
        self.prompt_path = prompt_path
        self.last_provider_trace: ProviderTrace | None = None

    def run(self, inputs: dict[str, Any]) -> Message:
        prompt = self.prompt_path.read_text(encoding="utf-8")
        result = self.provider.generate(self.role, self.spec.action, prompt, inputs, self.spec.output_model)
        payload = self.spec.output_model.model_validate(result.payload).model_dump(mode="json")
        self.last_provider_trace = result.trace
        return Message(sender=self.role, action=self.spec.action, payload=payload)
