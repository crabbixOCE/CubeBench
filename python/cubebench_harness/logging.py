from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)

    if hasattr(value, "model_dump"):
        return value.model_dump()

    if hasattr(value, "__dict__"):
        return value.__dict__

    return str(value)


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        import json

        return json.dumps(value, indent=2, sort_keys=True, default=_json_default)

    return str(value)


def _compact_stringify(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        import json

        return json.dumps(value, sort_keys=True, default=_json_default)

    return str(value)


class RunLogger:
    def __init__(self, repo_root: Path, provider: str, model_name: str) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        slug = f"{timestamp}_{provider}_{model_name.replace('/', '_')}"
        runs_dir = repo_root / "runs"
        runs_dir.mkdir(exist_ok=True)
        self.events_path = runs_dir / f"{slug}_events.txt"
        self.reasoning_path = runs_dir / f"{slug}_reasoning.txt"

    def write_header(self, config: Any) -> None:
        self.events_path.write_text("")
        self.reasoning_path.write_text(
            "CubeBench Trace\n"
            "===============\n\n"
            "config\n"
            "------\n"
            f"{_stringify(config)}\n\n",
        )

    def log_compact_tool_call(self, name: str, arguments: Any) -> None:
        with self.events_path.open("a") as handle:
            handle.write(f"{name} {_compact_stringify(arguments)}\n")

    def log_compact_model_output(self, content: str) -> None:
        text = content.strip()
        if not text:
            return

        with self.events_path.open("a") as handle:
            handle.write(f"{text}\n")

    def log_verbose_event(self, title: str, content: Any) -> None:
        with self.reasoning_path.open("a") as handle:
            handle.write(f"{title}\n")
            handle.write(f"{'-' * len(title)}\n")
            handle.write(f"{_stringify(content)}\n\n")

    def log_reasoning(self, provider: str, turn: int, content: Any) -> None:
        self.log_verbose_event(f"{provider} turn {turn}", content)
