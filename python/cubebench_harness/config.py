from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .tasks import get_task_definition

OPENAI_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
GOOGLE_THINKING_LEVELS = {"low", "medium", "high"}
KNOWN_PROVIDERS = {"anthropic", "google", "openai"}


def _normalize_model_name(provider: str, model_name: str) -> str:
    if provider == "openai" and model_name.startswith("gpt") and len(model_name) > 3:
        if model_name[3].isdigit():
            return f"gpt-{model_name[3:]}"

    return model_name


def _split_provider_prefix(model_name: str) -> tuple[str | None, str]:
    for separator in (":", "/"):
        if separator not in model_name:
            continue

        provider, remainder = model_name.split(separator, 1)
        provider = provider.strip().lower()
        if provider in KNOWN_PROVIDERS and remainder.strip():
            return provider, remainder.strip()

    return None, model_name


def _infer_provider(model_name: str, default_provider: str | None) -> str:
    lowered = model_name.lower()

    if lowered.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    if lowered.startswith("gemini"):
        return "google"
    if lowered.startswith("claude"):
        return "anthropic"
    if default_provider is not None:
        return default_provider

    raise ValueError(
        "Could not infer a provider from model "
        f"'{model_name}'. Prefix the model with 'openai:', 'google:', or 'anthropic:'."
    )


def _as_string_list(value: object, field_name: str) -> list[str]:
    if isinstance(value, str):
        result = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        result = value
    else:
        raise ValueError(f"Expected '{field_name}' to be a string or list of strings.")

    normalized = [item.strip() for item in result if item.strip()]
    if not normalized:
        raise ValueError(f"Expected '{field_name}' to contain at least one value.")

    return normalized


def _ensure_unique(values: list[str], field_name: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        duplicates_text = ", ".join(duplicates)
        raise ValueError(f"Duplicate values are not allowed in '{field_name}': {duplicates_text}.")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    raw_name: str
    provider: str
    model_name: str
    reasoning_level: str | None = None

    @classmethod
    def parse(cls, raw_name: str, default_provider: str | None = None) -> "ModelSpec":
        explicit_provider, remainder = _split_provider_prefix(raw_name.strip())
        provider = explicit_provider or _infer_provider(remainder, default_provider)
        model_name = remainder
        reasoning_level: str | None = None

        if provider == "openai":
            candidate, _, suffix = model_name.rpartition("-")
            if candidate and suffix in OPENAI_REASONING_EFFORTS:
                model_name = candidate
                reasoning_level = suffix
        elif provider == "google":
            candidate, _, suffix = model_name.rpartition("-")
            if candidate and suffix in GOOGLE_THINKING_LEVELS:
                model_name = candidate
                reasoning_level = suffix

        return cls(
            raw_name=raw_name.strip(),
            provider=provider,
            model_name=_normalize_model_name(provider, model_name.strip()),
            reasoning_level=reasoning_level,
        )


@dataclass(frozen=True, slots=True)
class PlannedRun:
    run_index: int
    run_id: str
    task: str
    task_run_index: int
    scramble_name: str
    scramble: str
    model: ModelSpec


@dataclass(slots=True)
class OpenAIConfig:
    reasoning_effort: str = "medium"
    reasoning_summary: str = "detailed"
    compact_threshold: int | None = None


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
    model_label: str | None = None
    run_id: str | None = None
    task_run_index: int | None = None
    max_turns: int = 12
    max_output_tokens: int = 1200
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    google: GoogleConfig = field(default_factory=GoogleConfig)


@dataclass(slots=True)
class HarnessBatchConfig:
    cube: str
    representation: str
    tasks: list[str]
    model_names: list[str]
    n_runs_per_task: int = 1
    provider: str | None = None
    scramble_name: str | None = None
    scramble: str | None = None
    max_turns: int = 12
    max_output_tokens: int = 1200
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    google: GoogleConfig = field(default_factory=GoogleConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "HarnessBatchConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}

        task_values = raw.get("tasks", raw.get("task"))
        model_values = raw.get("model_names", raw.get("model_name"))
        if task_values is None:
            raise ValueError("Config must define 'tasks' or legacy 'task'.")
        if model_values is None:
            raise ValueError("Config must define 'model_names' or legacy 'model_name'.")

        tasks = [get_task_definition(task).id for task in _as_string_list(task_values, "tasks")]
        model_names = _as_string_list(model_values, "model_names")
        _ensure_unique(tasks, "tasks")
        _ensure_unique(model_names, "model_names")

        n_runs_per_task = raw.get("n_runs_per_task", 1)
        if not isinstance(n_runs_per_task, int) or n_runs_per_task < 1:
            raise ValueError("'n_runs_per_task' must be an integer >= 1.")

        provider = raw.get("provider")
        if provider is not None:
            provider = str(provider).strip().lower()
            if provider not in KNOWN_PROVIDERS:
                supported = ", ".join(sorted(KNOWN_PROVIDERS))
                raise ValueError(f"Unsupported provider '{provider}'. Choose one of: {supported}.")

        scramble_name = raw.get("scramble_name")
        scramble = raw.get("scramble")
        if (scramble_name is None) != (scramble is None):
            raise ValueError("Legacy scramble overrides require both 'scramble_name' and 'scramble'.")
        if scramble is not None and n_runs_per_task != 1:
            raise ValueError(
                "Fixed scramble overrides require n_runs_per_task=1 for every task."
            )

        return cls(
            cube=raw["cube"],
            representation=raw["representation"],
            tasks=tasks,
            model_names=model_names,
            n_runs_per_task=n_runs_per_task,
            provider=provider,
            scramble_name=scramble_name,
            scramble=scramble,
            max_turns=raw.get("max_turns", 12),
            max_output_tokens=raw.get("max_output_tokens", 1200),
            openai=OpenAIConfig(**raw.get("openai", {})),
            anthropic=AnthropicConfig(**raw.get("anthropic", {})),
            google=GoogleConfig(**raw.get("google", {})),
        )

    def resolved_models(self) -> list[ModelSpec]:
        return [ModelSpec.parse(model_name, self.provider) for model_name in self.model_names]

    def expand_runs(self, scrambles_by_task: dict[str, list[str]]) -> list[PlannedRun]:
        planned_runs: list[PlannedRun] = []
        models = self.resolved_models()
        run_index = 1

        for task in self.tasks:
            task_scrambles = scrambles_by_task.get(task)
            if task_scrambles is None:
                raise ValueError(f"Missing generated scrambles for task '{task}'.")
            if len(task_scrambles) != self.n_runs_per_task:
                raise ValueError(
                    f"Task '{task}' expected {self.n_runs_per_task} scrambles, "
                    f"got {len(task_scrambles)}."
                )

            for task_run_index, scramble in enumerate(task_scrambles, start=1):
                scramble_name = f"{task}_{task_run_index:02d}"
                if (
                    self.scramble_name is not None
                    and self.scramble is not None
                    and task_run_index == 1
                ):
                    scramble_name = self.scramble_name
                for model in models:
                    run_id = (
                        f"{run_index:03d}_{task}_r{task_run_index:02d}_"
                        f"{_slug_fragment(model.raw_name)}"
                    )
                    planned_runs.append(
                        PlannedRun(
                            run_index=run_index,
                            run_id=run_id,
                            task=task,
                            task_run_index=task_run_index,
                            scramble_name=scramble_name,
                            scramble=scramble,
                            model=model,
                        )
                    )
                    run_index += 1

        return planned_runs

    def build_run_config(self, planned_run: PlannedRun) -> HarnessConfig:
        config = HarnessConfig(
            provider=planned_run.model.provider,
            model_name=planned_run.model.model_name,
            model_label=planned_run.model.raw_name,
            cube=self.cube,
            representation=self.representation,
            scramble_name=planned_run.scramble_name,
            scramble=planned_run.scramble,
            task=planned_run.task,
            run_id=planned_run.run_id,
            task_run_index=planned_run.task_run_index,
            max_turns=self.max_turns,
            max_output_tokens=self.max_output_tokens,
            openai=deepcopy(self.openai),
            anthropic=deepcopy(self.anthropic),
            google=deepcopy(self.google),
        )

        if planned_run.model.provider == "openai" and planned_run.model.reasoning_level is not None:
            config.openai.reasoning_effort = planned_run.model.reasoning_level

        if planned_run.model.provider == "google" and planned_run.model.reasoning_level is not None:
            config.google.thinking_level = planned_run.model.reasoning_level
            config.google.thinking_budget = None

        return config

    def generated_scrambles(self) -> dict[str, list[str]]:
        if self.scramble is None or self.scramble_name is None:
            raise ValueError("This config does not define legacy fixed scrambles.")

        return {task: [self.scramble] for task in self.tasks}


def _slug_fragment(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value.strip()]
    fragment = "".join(chars).strip("_")
    while "__" in fragment:
        fragment = fragment.replace("__", "_")
    return fragment or "model"
