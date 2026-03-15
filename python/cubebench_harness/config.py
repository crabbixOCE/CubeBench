from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .tasks import get_task_definition


@dataclass(slots=True)
class OpenAIConfig:
    reasoning_effort: str = "medium"
    reasoning_summary: str = "detailed"


@dataclass(slots=True)
class AnthropicConfig:
    max_tokens: int = 1600
    thinking_budget_tokens: int = 2048


@dataclass(slots=True)
class GoogleConfig:
    max_output_tokens: int = 1600
    thinking_budget: int | None = None
    thinking_level: str | None = None
    include_thoughts: bool = True


@dataclass(slots=True)
class HarnessConfig:
    provider: str
    model_name: str
    cube: str
    representation: str
    scramble_name: str
    scramble: str
    task: str
    max_turns: int = 12
    max_output_tokens: int = 1200
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    google: GoogleConfig = field(default_factory=GoogleConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "HarnessConfig":
        raw = yaml.safe_load(Path(path).read_text())
        task = get_task_definition(raw["task"]).id

        return cls(
            provider=raw["provider"],
            model_name=raw["model_name"],
            cube=raw["cube"],
            representation=raw["representation"],
            scramble_name=raw["scramble_name"],
            scramble=raw["scramble"],
            task=task,
            max_turns=raw.get("max_turns", 12),
            max_output_tokens=raw.get("max_output_tokens", 1200),
            openai=OpenAIConfig(**raw.get("openai", {})),
            anthropic=AnthropicConfig(**raw.get("anthropic", {})),
            google=GoogleConfig(**raw.get("google", {})),
        )
