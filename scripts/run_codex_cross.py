#!/usr/bin/env python3
"""Run the deterministic one-task CubeBench smoke test through Codex CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from cubebench_harness.config import HarnessBatchConfig
from cubebench_harness.converters import get_converter
from cubebench_harness.cube_bridge import CubeJsBridge
from cubebench_harness.prompting import build_system_prompt, build_user_prompt


DEFAULT_CONFIG = REPO_ROOT / "config.codex-luna-cross.yaml"
DEFAULT_TEMPLATE = REPO_ROOT / "codex_home" / "config.toml.template"
DEFAULT_CODEX_HOME = Path.home() / ".codex-cubebench"
SOURCE_AUTH = Path.home() / ".codex" / "auth.json"


def _load_single_run(config_path: Path) -> tuple[HarnessBatchConfig, Any, str]:
    batch = HarnessBatchConfig.from_yaml(config_path)
    if len(batch.tasks) != 1 or len(batch.model_names) != 1 or batch.n_runs_per_task != 1:
        raise ValueError("Codex smoke config must describe exactly one model and one task run.")
    if batch.scramble is None or batch.scramble_name is None:
        raise ValueError("Codex smoke config requires a fixed scramble and scramble_name.")
    model = batch.resolved_models()[0]
    if batch.tasks != ["cross"]:
        raise ValueError("This smoke launcher only accepts the cross task.")
    if model.model_name != "gpt-5.6-luna" or model.reasoning_level != "max":
        raise ValueError("This smoke launcher requires gpt-5.6-luna-max.")
    return batch, model, batch.scramble


def _render_codex_home(
    *, codex_home: Path, template_path: Path, scramble: str
) -> Path:
    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    codex_home.chmod(0o700)
    rendered = template_path.read_text()
    replacements = {
        "__CUBEBENCH_PYTHON__": str(REPO_ROOT / ".venv" / "bin" / "python"),
        "__CUBEBENCH_PYTHONPATH__": str(REPO_ROOT / "python"),
        "__CUBEBENCH_REPO_ROOT__": str(REPO_ROOT),
        "__CUBEBENCH_COMPACT_THRESHOLD__": "175000",
        "__CUBEBENCH_MODEL__": "gpt-5.6-luna",
        "__CUBEBENCH_REASONING_EFFORT__": "max",
        "__CUBEBENCH_COMPACT_THRESHOLD__": "120000",
        "__CUBEBENCH_TASK__": "cross",
        "__CUBEBENCH_SCRAMBLE_NAME__": "cross_01",
        "__CUBEBENCH_CUBE__": "3x3",
        "__CUBEBENCH_REPRESENTATION__": "cubie_json",
        "__CUBEBENCH_SCRAMBLE__": scramble,
    }
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    config_path = codex_home / "config.toml"
    config_path.write_text(rendered)
    config_path.chmod(0o600)
    return config_path


def _seed_chatgpt_auth(codex_home: Path) -> Path:
    target = codex_home / "auth.json"
    if target.exists():
        target.chmod(0o600)
        return target
    if not SOURCE_AUTH.is_file():
        raise FileNotFoundError(
            f"No ChatGPT Codex auth found at {SOURCE_AUTH}; run "
            f"CODEX_HOME={codex_home} codex login first."
        )
    shutil.copyfile(SOURCE_AUTH, target)
    target.chmod(0o600)
    return target


def _prompt(batch: HarnessBatchConfig, model: Any) -> str:
    from codex_tool_isolation import NO_CODE_INSTRUCTIONS
    planned = batch.expand_runs({batch.tasks[0]: [batch.scramble]})[0]
    config = batch.build_run_config(planned)
    contract = get_converter(config.representation).prompt_contract()
    return (
        NO_CODE_INSTRUCTIONS
        + "\n\n"
        + build_system_prompt(config, contract)
        + "\n\n"
        + build_user_prompt(config)
        + "\n\nThis is one benchmark attempt. Keep searching when it is useful because "
        "the score rewards the fewest legal moves, then submit your best verified sequence."
    )


def _event_item(event: dict[str, Any]) -> dict[str, Any]:
    item = event.get("item")
    return item if isinstance(item, dict) else {}


def _extract_submission(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        item = _event_item(event)
        if item.get("type") != "mcp_tool_call":
            continue
        tool_name = item.get("tool") or item.get("name")
        if not isinstance(tool_name, str) or not tool_name.endswith("make_final_submission"):
            continue
        arguments = item.get("arguments") or item.get("input")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        if isinstance(arguments, dict) and isinstance(arguments.get("moves"), str):
            return arguments["moves"].strip()
    return ""


def _usage(events: list[dict[str, Any]]) -> dict[str, int] | None:
    for event in reversed(events):
        usage = event.get("usage")
        if event.get("type") == "turn.completed" and isinstance(usage, dict):
            return {key: int(value) for key, value in usage.items() if isinstance(value, int)}
    return None


def _verify(task: str, scramble: str, moves: str) -> bool:
    if not moves:
        return False
    bridge = CubeJsBridge(repo_root=REPO_ROOT, cube="3x3")
    bridge.load_scramble(scramble)
    bridge.apply_moves(moves)
    return bridge.check_task_complete(task).task_completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch, model, scramble = _load_single_run(args.config.resolve())
    codex_home = args.codex_home.expanduser().resolve()
    rendered_config = _render_codex_home(
        codex_home=codex_home,
        template_path=args.template.resolve(),
        scramble=scramble,
    )
    auth_path = _seed_chatgpt_auth(codex_home)

    effort = model.reasoning_level or "max"
    command_prefix = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ignore-rules",
        "--strict-config",
        "--sandbox",
        "read-only",
        "--model",
        model.model_name,
        "-c",
        f'model_reasoning_effort="{effort}"',
    ]
    if args.dry_run:
        print(json.dumps({
            "codex_home": str(codex_home),
            "config": str(rendered_config),
            "auth": str(auth_path),
            "command": command_prefix + ["-C", "<empty temporary directory>", "<prompt>"],
            "task": batch.tasks[0],
            "scramble": scramble,
        }, indent=2))
        return 0

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = REPO_ROOT / "runs" / f"{timestamp}_codex_luna_cross"
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "codex-events.jsonl"
    stderr_path = run_dir / "codex-stderr.txt"

    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment.pop("CODEX_API_KEY", None)
    environment.pop("OPENAI_API_KEY", None)
    from codex_tool_isolation import prepare
    command_prefix[2:2] = prepare(codex_home, model.model_name, "codex", run_dir / "tool-isolation")

    with tempfile.TemporaryDirectory(prefix="cubebench-codex-") as workspace:
        command = command_prefix + ["-C", workspace, _prompt(batch, model)]
        (run_dir / "launch-command.json").write_text(json.dumps(command, indent=2))
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    trace_path.write_text(completed.stdout)
    stderr_path.write_text(completed.stderr)
    events: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)

    submission = _extract_submission(events)
    success = _verify(batch.tasks[0], scramble, submission)
    status = {
        "task": batch.tasks[0],
        "scramble_name": batch.scramble_name,
        "scramble": scramble,
        "model": model.model_name,
        "reasoning_effort": effort,
        "solution": submission,
        "success": success,
        "usage": _usage(events),
        "codex_exit_code": completed.returncode,
        "trace_path": str(trace_path),
        "stderr_path": str(stderr_path),
    }
    status_path = run_dir / "status.json"
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True))
    print(json.dumps({"run_dir": str(run_dir), **status}, indent=2, sort_keys=True))
    return 0 if completed.returncode == 0 and success else 1


if __name__ == "__main__":
    raise SystemExit(main())
