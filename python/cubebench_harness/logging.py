from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
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
        return json.dumps(value, indent=2, sort_keys=True, default=_json_default)

    return str(value)


def _compact_stringify(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=_json_default)

    return str(value)


def _slugify(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value.strip()]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "benchmark"


@dataclass(frozen=True, slots=True)
class RunStatusRecord:
    run_id: str
    task_name: str
    task_run_index: int
    scramble_name: str
    scramble: str
    solution: str
    model: str
    provider: str
    success: bool
    total_output_tokens_used: int | None
    events_path: str
    reasoning_path: str
    error: str | None = None


class RunLogger:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.txt"
        self.reasoning_path = self.run_dir / "reasoning.txt"

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


class BatchLogger:
    def __init__(self, repo_root: Path, batch_label: str) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        batch_slug = f"{timestamp}_{_slugify(batch_label)}"
        self.batch_dir = repo_root / "runs" / batch_slug
        self.artifacts_dir = self.batch_dir / "artifacts"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(exist_ok=True)
        self.manifest_path = self.batch_dir / "manifest.json"
        self.status_path = self.batch_dir / "status.json"
        self._status_records: list[RunStatusRecord] = []

    def write_manifest(self, payload: Any) -> None:
        self.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))

    def create_run_logger(self, run_id: str) -> RunLogger:
        return RunLogger(self.artifacts_dir / run_id)

    def append_status(self, record: RunStatusRecord) -> None:
        self._status_records.append(record)
        self.status_path.write_text(
            json.dumps(
                [asdict(status_record) for status_record in self._status_records],
                indent=2,
                sort_keys=True,
            )
        )

    @property
    def status_records(self) -> list[RunStatusRecord]:
        return list(self._status_records)
