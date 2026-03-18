from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    provider_call_id: str


@dataclass(slots=True)
class ProviderResult:
    final_text: str
    total_output_tokens: int | None = None


class ProviderRunError(RuntimeError):
    def __init__(self, message: str, *, total_output_tokens: int | None = None) -> None:
        super().__init__(message)
        self.total_output_tokens = total_output_tokens
