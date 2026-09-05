#!/usr/bin/env python3
"""Run a bounded, parallel CubeBench batch through Codex CLI.

The launcher deliberately keeps the Codex process in an empty read-only
workspace.  CubeBench is the only enabled MCP server, and the server's four
tools are the only tools allow-listed in the rendered Codex home.  A dry run
only validates the plan and prints commands; it never writes a Codex home,
copies credentials, or starts inference.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable

import codex_tool_isolation
import codex_token_budget


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from cubebench_harness.config import HarnessBatchConfig, ModelSpec  # noqa: E402
from cubebench_harness.converters import get_converter  # noqa: E402
from cubebench_harness.cube_bridge import CubeJsBridge  # noqa: E402
from cubebench_harness.prompting import build_system_prompt, build_user_prompt  # noqa: E402


DEFAULT_CONFIG = REPO_ROOT / "config.codex-f2l-full-cube.yaml"
DEFAULT_TEMPLATE = REPO_ROOT / "codex_home" / "config.toml.template"
DEFAULT_CODEX_HOME = Path.home() / ".codex-cubebench"
SOURCE_AUTH = Path.home() / ".codex" / "auth.json"
TASKS = ("f2l", "full_solve")
TASK_LABELS = {"f2l": "f2l", "full_solve": "full_cube"}
SCRAMBLE_NAME = "one_layer_01"
SCRAMBLE = "B U F B D F R L' F D2 F2 L' D2 F2 B2 R U2 L2 D2 L2 F"

EXPECTED_RAW_MODELS = (
    "gpt-5.6-sol-max",
    "gpt-6-astra-max",
)


@dataclass(frozen=True, slots=True)
class BatchEntry:
    index: int
    task: str
    task_index: int
    model_index: int
    raw_name: str
    model_name: str
    requested_reasoning_effort: str
    effective_reasoning_effort: str


def load_batch(config_path: Path) -> tuple[HarnessBatchConfig, list[BatchEntry]]:
    """Load and strictly validate the four-entry f2l/full-cube plan."""

    batch = HarnessBatchConfig.from_yaml(config_path)
    if tuple(batch.tasks) != TASKS or batch.n_runs_per_task != 1:
        raise ValueError("The Codex comparison must contain exactly one f2l and one full_solve run.")
    if batch.scramble_name != SCRAMBLE_NAME or batch.scramble != SCRAMBLE:
        raise ValueError("The Codex comparison must use the fixed one_layer_01 scramble.")
    if tuple(batch.model_names) != EXPECTED_RAW_MODELS:
        expected = ", ".join(EXPECTED_RAW_MODELS)
        raise ValueError(f"Expected model_names in this order: {expected}.")

    specs = batch.resolved_models()
    entries: list[BatchEntry] = []
    index = 0
    for task_index, task in enumerate(batch.tasks):
        for model_index, spec in enumerate(specs):
            if spec.provider != "openai":
                raise ValueError(f"Codex comparison only supports OpenAI models: {spec.raw_name}.")
            if spec.reasoning_level != "max":
                raise ValueError(f"Missing explicit max reasoning effort: {spec.raw_name}.")
            entries.append(
                BatchEntry(
                    index=index,
                    task=task,
                    task_index=task_index,
                    model_index=model_index,
                    raw_name=spec.raw_name,
                    model_name=spec.model_name,
                    requested_reasoning_effort="max",
                    effective_reasoning_effort="max",
                )
            )
            index += 1
    return batch, entries


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_config_text(
    *,
    template_path: Path,
    entry: BatchEntry,
    task: str | None = None,
    scramble_name: str = SCRAMBLE_NAME,
    scramble: str = SCRAMBLE,
    cube: str = "3x3",
    representation: str = "cubie_json",
    compact_threshold: int = 175000,
) -> str:
    """Render a template without touching the filesystem."""

    python_executable = REPO_ROOT / ".venv" / "bin" / "python"
    replacements = {
        "__CUBEBENCH_PYTHON__": str(python_executable),
        "__CUBEBENCH_PYTHONPATH__": str(PYTHON_ROOT),
        "__CUBEBENCH_REPO_ROOT__": str(REPO_ROOT),
        "__CUBEBENCH_MODEL__": entry.model_name,
        "__CUBEBENCH_REASONING_EFFORT__": entry.effective_reasoning_effort,
        "__CUBEBENCH_COMPACT_THRESHOLD__": str(compact_threshold),
        "__CUBEBENCH_TASK__": task or entry.task,
        "__CUBEBENCH_SCRAMBLE_NAME__": scramble_name,
        "__CUBEBENCH_SCRAMBLE__": scramble,
        "__CUBEBENCH_CUBE__": cube,
        "__CUBEBENCH_REPRESENTATION__": representation,
    }
    rendered = template_path.read_text()
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, _toml_escape(value))
    unresolved = re.findall(r"__CUBEBENCH_[A-Z0-9_]+__", rendered)
    if unresolved:
        raise ValueError(f"Unresolved Codex template markers: {', '.join(sorted(set(unresolved)))}")
    return rendered


def install_config(codex_home: Path, rendered: str) -> Path:
    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    codex_home.chmod(0o700)
    config_path = codex_home / "config.toml"
    config_path.write_text(rendered)
    config_path.chmod(0o600)
    return config_path


def ensure_chatgpt_auth(
    codex_home: Path,
    *,
    source_auth: Path = SOURCE_AUTH,
) -> Path:
    """Reuse a dedicated home auth file, or securely link the existing login.

    The launcher never copies credentials into the repository.  A symlink is
    used for a fresh home so token refreshes continue to use the user's normal
    Codex login without duplicating the secret.  Existing dedicated-home auth
    files are preserved and tightened to mode 0600.
    """

    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    codex_home.chmod(0o700)
    target = codex_home / "auth.json"
    if target.exists() or target.is_symlink():
        if not target.is_symlink():
            target.chmod(0o600)
        return target
    if not source_auth.is_file():
        raise FileNotFoundError(
            f"No ChatGPT Codex auth found at {source_auth}; run "
            f"CODEX_HOME={codex_home} codex login first."
        )
    target.symlink_to(source_auth.resolve())
    return target


def build_command(
    *,
    entry: BatchEntry,
    workspace: Path,
    prompt: str,
    codex_bin: str = "codex",
    persist_session: bool = True,
) -> list[str]:
    return [
        codex_bin,
        "exec",
        "--json",
        *([] if persist_session else ["--ephemeral"]),
        "--skip-git-repo-check",
        "--ignore-rules",
        "--strict-config",
        "--sandbox",
        "read-only",
        "--model",
        entry.model_name,
        "-c",
        f'model_reasoning_effort="{entry.effective_reasoning_effort}"',
        "-C",
        str(workspace),
        prompt,
    ]


def _prompt(batch: HarnessBatchConfig, entry: BatchEntry) -> str:
    scrambles = {task: [batch.scramble or SCRAMBLE] for task in batch.tasks}
    runs = batch.expand_runs(scrambles)
    planned = next(
        run for run in runs if run.task == entry.task and run.model.raw_name == entry.raw_name
    )
    config = batch.build_run_config(planned)
    contract = get_converter(config.representation).prompt_contract()
    return (
        codex_tool_isolation.NO_CODE_INSTRUCTIONS
        + "\n\n"
        + build_system_prompt(config, contract)
        + "\n\n"
        + build_user_prompt(config)
        + "\n\nThis is exactly one bounded benchmark attempt. Use only the four CubeBench MCP "
        "tools. Search for the fewest legal moves you can find, verify the current "
        "candidate with check_task_complete, and call make_final_submission exactly "
        "once. The instant any candidate passes check_task_complete, submit that "
        "verified sequence before spending another turn optimizing. Do not use shell, "
        "files, web, browser, image, app, plugin, or agent tools."
    )


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _is_submission_name(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return re.split(r"__|[.:/]", value.strip().lower())[-1] == "make_final_submission"


def extract_submission(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        # A started call contains its arguments before the MCP server has
        # accepted them.  Only a completed, error-free call is a submission.
        if event.get("type") != "item.completed":
            continue
        for node in reversed(list(_walk(event))):
            if (
                not isinstance(node, dict)
                or node.get("type") != "mcp_tool_call"
                or node.get("status") != "completed"
                or node.get("error")
            ):
                continue
            name = node.get("tool") or node.get("name")
            if not _is_submission_name(name):
                continue
            arguments = node.get("arguments") or node.get("input")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            if isinstance(arguments, dict) and isinstance(arguments.get("moves"), str):
                return arguments["moves"].strip()
    return ""


def _tool_name(node: dict[str, Any]) -> str:
    """Return the unqualified MCP tool name from a Codex event item."""

    value = node.get("tool") or node.get("name")
    if not isinstance(value, str):
        return ""
    return re.split(r"__|[.:/]", value.strip().lower())[-1]


def _tool_arguments(node: dict[str, Any]) -> dict[str, Any]:
    """Decode an MCP event's arguments/input payload when it is an object."""

    arguments = node.get("arguments")
    if arguments is None:
        arguments = node.get("input")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


def _completed_mcp_calls(events: list[dict[str, Any]]) -> Iterable[tuple[int, dict[str, Any]]]:
    """Yield completed, error-free MCP call items in trace order.

    Codex currently emits calls as ``item.completed`` items, but keeping the
    recursive walk makes this tolerant of equivalent nested/response event
    shapes. IDs are de-duplicated so a call mirrored in a result payload is
    replayed only once.
    """

    seen_ids: set[str] = set()
    for event_index, event in enumerate(events):
        # A resumed/new trace starts its item-id sequence at item_0 again.
        # Clear the per-thread dedupe set so continuation calls are not
        # mistaken for duplicates of the original ephemeral trace.
        if event.get("type") == "thread.started":
            seen_ids.clear()
        for node in _walk(event):
            if not isinstance(node, dict) or node.get("type") != "mcp_tool_call":
                continue
            if node.get("status") != "completed" or node.get("error"):
                continue
            node_id = node.get("id")
            if isinstance(node_id, str):
                if node_id in seen_ids:
                    continue
                seen_ids.add(node_id)
            yield event_index, node


def replay_checkpoints(
    *,
    events: list[dict[str, Any]],
    task: str,
    cube: str,
    scramble: str,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Replay legal cumulative ``apply_moves`` checkpoints from a Codex trace.

    Every completed ``load_scramble`` starts a fresh trajectory.  Each
    subsequent completed ``apply_moves`` chunk is applied to a host cube and
    checked immediately with the configured task.  The resulting report keeps
    the final candidate plus the shortest verified completion, allowing a
    timed-out Codex process to be scored when it never reached
    ``make_final_submission``.
    """

    bridge: CubeJsBridge | None = None
    reset_index = 0
    cumulative_parts: list[str] = []
    checkpoints: list[dict[str, Any]] = []

    for event_index, node in _completed_mcp_calls(events):
        tool = _tool_name(node)
        if tool == "load_scramble":
            reset_index += 1
            cumulative_parts = []
            try:
                bridge = CubeJsBridge(repo_root=repo_root, cube=cube)
                bridge.load_scramble(scramble)
            except Exception:
                bridge = None
            continue

        if tool != "apply_moves" or bridge is None:
            continue

        arguments = _tool_arguments(node)
        chunk = arguments.get("moves")
        if not isinstance(chunk, str) or not chunk.strip():
            continue
        chunk = chunk.strip()

        try:
            bridge.apply_moves(chunk)
            cumulative_parts.append(chunk)
            cumulative_moves = " ".join(cumulative_parts)
            completed = bool(bridge.check_task_complete(task).task_completed)
            checkpoints.append(
                {
                    "event_index": event_index + 1,
                    "reset_index": reset_index,
                    "chunk_moves": chunk,
                    "moves": cumulative_moves,
                    "move_count": len(cumulative_moves.split()),
                    "legal": True,
                    "task_completed": completed,
                }
            )
        except Exception as exc:
            # A malformed/illegal chunk must not poison later checkpoints in
            # the same trajectory.  Keep an explicit record for diagnosis,
            # but only legal calls contribute to recovery candidates.
            checkpoints.append(
                {
                    "event_index": event_index + 1,
                    "reset_index": reset_index,
                    "chunk_moves": chunk,
                    "moves": " ".join(cumulative_parts),
                    "move_count": len(" ".join(cumulative_parts).split()),
                    "legal": False,
                    "task_completed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    legal = [record for record in checkpoints if record.get("legal")]
    completed = [record for record in legal if record.get("task_completed")]
    shortest = (
        min(completed, key=lambda record: (record["move_count"], record["event_index"]))
        if completed
        else None
    )
    final = legal[-1] if legal else None
    return {
        "checkpoints": checkpoints,
        "checkpoint_count": len(checkpoints),
        "legal_checkpoint_count": len(legal),
        "completed_checkpoint_count": len(completed),
        "shortest_completed": shortest,
        "final_checkpoint": final,
    }


def collect_usage(events: list[dict[str, Any]]) -> dict[str, int] | None:
    totals: dict[str, int] = {}
    for event in events:
        if event.get("type") != "turn.completed" or not isinstance(event.get("usage"), dict):
            continue
        for key, value in event["usage"].items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    if not totals:
        return None
    # Codex's output_tokens already includes reasoning_output_tokens.  Keep
    # this field compatible with CubeBench's existing status/plot schema.
    totals["total_output_tokens_used"] = totals.get("output_tokens", 0)
    return totals


def verify_submission(*, task: str, cube: str, scramble: str, moves: str) -> tuple[bool, str | None]:
    if not moves:
        return False, "No make_final_submission call was found."
    try:
        bridge = CubeJsBridge(repo_root=REPO_ROOT, cube=cube)
        bridge.load_scramble(scramble)
        bridge.apply_moves(moves)
        result = bridge.check_task_complete(task)
    except Exception as exc:  # host-side status should survive malformed model output
        return False, f"{type(exc).__name__}: {exc}"
    return bool(result.task_completed), None if result.task_completed else "CubeBench check_task_complete returned false."


def resolve_trace_solution(
    *,
    events: list[dict[str, Any]],
    task: str,
    cube: str,
    scramble: str,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Choose an official submission or recover a verified checkpoint.

    A Codex process can time out after proving a candidate with
    ``apply_moves`` but before emitting ``make_final_submission``.  In that
    case the shortest host-verified checkpoint is a valid benchmark result.
    When no checkpoint completes, the latest legal cumulative candidate is
    retained for diagnosis while ``verified`` and ``success`` remain false.
    """

    report = replay_checkpoints(
        events=events,
        task=task,
        cube=cube,
        scramble=scramble,
        repo_root=repo_root,
    )
    official = extract_submission(events)
    official_verified, official_error = verify_submission(
        task=task,
        cube=cube,
        scramble=scramble,
        moves=official,
    )

    if official_verified:
        return {
            "solution": official,
            "verified": True,
            "solution_source": "official_submission",
            "verification_error": None,
            "checkpoint_report": report,
        }

    shortest = report.get("shortest_completed")
    if isinstance(shortest, dict):
        return {
            "solution": str(shortest.get("moves", "")),
            "verified": True,
            "solution_source": "recovered_checkpoint",
            "verification_error": None,
            "checkpoint_report": report,
        }

    final = report.get("final_checkpoint")
    final_moves = str(final.get("moves", "")) if isinstance(final, dict) else ""
    if official:
        solution = official
        source = "official_submission_unverified"
    elif final_moves:
        solution = final_moves
        source = "final_checkpoint_unverified"
    else:
        solution = ""
        source = "none"
    return {
        "solution": solution,
        "verified": False,
        "solution_source": source,
        "verification_error": official_error or "No host-verified checkpoint completed the task.",
        "checkpoint_report": report,
    }


def _slug(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return result or "model"


def _new_batch_dir() -> Path:
    base = REPO_ROOT / "runs" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_codex_f2l_full_cube"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_{suffix}")
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _run_entry(
    *,
    batch: HarnessBatchConfig,
    entry: BatchEntry,
    template_path: Path,
    base_codex_home: Path,
    batch_dir: Path,
    timeout_seconds: float,
    codex_bin: str,
    persist_session: bool = True,
    reasoning_token_budget: int | None = None,
) -> dict[str, Any]:
    """Execute one attempt with a private home and workspace."""

    run_dir = batch_dir / f"{entry.index + 1:03d}_{_slug(entry.task)}_{_slug(entry.raw_name)}"
    run_dir.mkdir()
    attempt_home = base_codex_home / run_dir.name
    auth_path = ensure_chatgpt_auth(attempt_home)
    rendered = render_config_text(
        template_path=template_path,
        entry=entry,
        task=entry.task,
        scramble_name=batch.scramble_name or SCRAMBLE_NAME,
        scramble=batch.scramble or SCRAMBLE,
        cube=batch.cube,
        representation=batch.representation,
        compact_threshold=batch.openai.compact_threshold or 175000,
    )
    config_path = install_config(attempt_home, rendered)
    trace_path = run_dir / "codex-events.jsonl"
    stderr_path = run_dir / "codex-stderr.txt"
    timed_out = False
    budget_stop_reason = None
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(attempt_home)
    environment.pop("CODEX_API_KEY", None)
    environment.pop("OPENAI_API_KEY", None)
    # Feature flags alone do not override a model's code_mode_only metadata.
    # Refuse inference unless the installed dispatcher passes a local probe.
    isolation_args = codex_tool_isolation.prepare(
        attempt_home, entry.model_name, codex_bin, run_dir / "tool-isolation"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="cubebench-codex-") as workspace:
            command = build_command(
                entry=entry,
                workspace=Path(workspace),
                prompt=_prompt(batch, entry),
                codex_bin=codex_bin,
                persist_session=persist_session,
            )
            command[2:2] = isolation_args
            (run_dir / "launch-command.json").write_text(json.dumps(command, indent=2))
            process_kwargs = dict(
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if reasoning_token_budget is not None:
                if not persist_session:
                    raise ValueError('Reasoning token budgets require persistent sessions')
                completed, budget_stop_reason = codex_token_budget.run(
                    command, home=attempt_home, budget=reasoning_token_budget,
                    timeout=timeout_seconds, report_path=run_dir / 'budget-status.json',
                    **process_kwargs,
                )
                timed_out = budget_stop_reason == 'wall_clock_timeout'
            else:
                completed = subprocess.run(command, check=False, timeout=timeout_seconds, **process_kwargs)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        exit_code = None

    trace_path.write_text(stdout)
    stderr_path.write_text(stderr)
    events = parse_jsonl(stdout)
    resolution = resolve_trace_solution(
        events=events,
        task=entry.task,
        cube=batch.cube,
        scramble=batch.scramble or SCRAMBLE,
        repo_root=REPO_ROOT,
    )
    submission = str(resolution["solution"])
    verified = bool(resolution["verified"])
    verification_error = resolution["verification_error"]
    checkpoint_report = resolution["checkpoint_report"]
    error = verification_error
    if not error and exit_code not in {0, None}:
        error = stderr.strip()[-4000:] or f"codex exited with status {exit_code}"
    status = {
        "run_id": run_dir.name,
        "task": entry.task,
        "task_label": TASK_LABELS[entry.task],
        "scramble_name": batch.scramble_name,
        "scramble": batch.scramble,
        "model": entry.model_name,
        "model_label": entry.raw_name,
        "provider": "openai",
        "requested_reasoning_effort": entry.requested_reasoning_effort,
        "reasoning_effort": entry.effective_reasoning_effort,
        "solution": submission,
        "solution_source": resolution["solution_source"],
        # Host verification is authoritative.  A timeout or non-zero Codex
        # exit remains visible below but must not discard a valid recovered
        # checkpoint (or an official submission emitted just before exit).
        "success": verified,
        "verified": verified,
        "timed_out": timed_out,
        "budget_stop_reason": budget_stop_reason,
        "reasoning_token_budget": reasoning_token_budget,
        "checkpoint_count": checkpoint_report["checkpoint_count"],
        "legal_checkpoint_count": checkpoint_report["legal_checkpoint_count"],
        "completed_checkpoint_count": checkpoint_report["completed_checkpoint_count"],
        "shortest_completed_checkpoint": checkpoint_report["shortest_completed"],
        "final_checkpoint": checkpoint_report["final_checkpoint"],
        "usage": collect_usage(events),
        "tool_isolation_report": str(run_dir / "tool-isolation" / "report.json"),
        "persist_session": persist_session,
        "codex_exit_code": exit_code,
        "error": error,
        "config_path": str(config_path),
        "codex_home": str(attempt_home),
        "auth_path": str(auth_path),
        "trace_path": str(trace_path),
        "stderr_path": str(stderr_path),
    }
    (run_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True))
    return status


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    batch, entries = load_batch(args.config.expanduser().resolve())
    codex_home = args.codex_home.expanduser().resolve()
    template_path = args.template.expanduser().resolve()

    if args.dry_run:
        preview = []
        for entry in entries:
            command = build_command(
                entry=entry,
                workspace=Path("<private-workspace>"),
                prompt="<prompt>",
                codex_bin=args.codex_bin,
            )
            preview.append(
                {
                    "index": entry.index,
                    "task": entry.task,
                    "task_label": TASK_LABELS[entry.task],
                    "raw_model": entry.raw_name,
                    "model": entry.model_name,
                    "reasoning_effort": entry.effective_reasoning_effort,
                    "command": command,
                    "tool_isolation": "Required before inference; runtime adds pinned catalog and disabled-host overrides. The final command is saved as launch-command.json.",
                    "rendered_config_preview": render_config_text(
                        template_path=template_path, entry=entry
                    ),
                }
            )
        print(json.dumps({"codex_home": str(codex_home), "runs": preview}, indent=2))
        return 0

    # Four independent homes prevent config/auth races while sharing the same
    # parent directory and existing ChatGPT account authentication.
    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    codex_home.chmod(0o700)
    batch_dir = _new_batch_dir()
    statuses: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(entries)) as executor:
        futures = {
            executor.submit(
                _run_entry,
                batch=batch,
                entry=entry,
                template_path=template_path,
                base_codex_home=codex_home,
                batch_dir=batch_dir,
                timeout_seconds=args.timeout_seconds,
                codex_bin=args.codex_bin,
            ): entry
            for entry in entries
        }
        for future in as_completed(futures):
            statuses.append(future.result())
    statuses.sort(key=lambda item: item["run_id"])
    (batch_dir / "status.json").write_text(json.dumps(statuses, indent=2, sort_keys=True))
    print(json.dumps({"run_dir": str(batch_dir), "status": statuses}, indent=2, sort_keys=True))
    return 0 if all(item["success"] for item in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
