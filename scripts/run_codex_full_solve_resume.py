#!/usr/bin/env python3
"""Continue the halted GPT-5.5 full-solve attempt without losing evidence.

The original invocation used ``codex exec --ephemeral``, so its thread is
normally not persisted. ``--mode auto`` checks that condition without touching
the database: it uses ``codex exec resume`` only when the thread is present,
otherwise it starts a clearly labelled fresh continuation with a concise
summary of the previous checkpoint. In both cases the MCP server is fresh and
the prompt requires ``load_scramble`` before any moves.

Use ``--dry-run`` to inspect the selected command. No credentials, config, or
Codex process are written/launched by a dry run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import run_codex_batch as batch_runner  # noqa: E402
import run_codex_f2l as single_runner  # noqa: E402


DEFAULT_ORIGINAL_RUN = (
    REPO_ROOT
    / "runs"
    / "20260905T055253Z_codex_gpt55_full_solve"
    / "001_full_solve_gpt_5_5_xhigh"
)
DEFAULT_CONFIG = REPO_ROOT / "config.codex-gpt55-full-solve.yaml"
DEFAULT_TEMPLATE = REPO_ROOT / "codex_home" / "config.toml.template"
DEFAULT_CODEX_HOME = Path.home() / ".codex-cubebench"
DEFAULT_TIMEOUT_SECONDS = 480.0


def _status_payload(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "status.json"
    if not path.is_file():
        raise FileNotFoundError(f"Original status file not found: {path}")
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        raise ValueError(f"Original status file is not an object: {path}")
    return payload


def _thread_id(trace_path: Path) -> str:
    if not trace_path.is_file():
        return ""
    for line in trace_path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            return event["thread_id"]
    return ""


def thread_is_persisted(codex_home: Path, thread_id: str) -> bool:
    """Check for a saved thread through a read-only SQLite connection."""

    if not thread_id:
        return False
    db_path = codex_home / "state_5.sqlite"
    if not db_path.is_file():
        return False
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM threads WHERE id = ? LIMIT 1", (thread_id,)
            ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _last_state(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Extract the compact cubie state from the last completed apply call."""

    for event in reversed(events):
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            continue
        if item.get("tool") != "apply_moves" or item.get("status") != "completed":
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        structured = result.get("structured_content")
        if isinstance(structured, dict) and isinstance(structured.get("state"), dict):
            state = structured["state"]
            return {
                key: state[key]
                for key in ("center", "cp", "co", "ep", "eo")
                if key in state
            }
    return None


def prior_summary(status: dict[str, Any], events: list[dict[str, Any]]) -> str:
    final = status.get("final_checkpoint")
    if not isinstance(final, dict):
        final = {}
    state = _last_state(events)
    state_text = json.dumps(state, separators=(",", ":")) if state else "unavailable"
    final_moves = str(final.get("moves", ""))
    restore_path = collapse_same_face_turns(final_moves) if final_moves else "unavailable"
    return (
        "Previous attempt summary (diagnostic only; do not assume this cube state): "
        f"{status.get('checkpoint_count', 0)} legal checkpoints, "
        f"{status.get('completed_checkpoint_count', 0)} full-solve completions, "
        f"last candidate {final.get('move_count', 0)} move tokens and unsolved. "
        f"Last returned cubie state: {state_text}. "
        f"If useful, restore that exact final candidate after load_scramble with "
        f"this collapsed path ({len(restore_path.split()) if restore_path != 'unavailable' else 0} moves): "
        f"{restore_path}."
    )


def collapse_same_face_turns(moves: str) -> str:
    """Collapse adjacent basic turns of one face while preserving the state.

    The halted run's final candidate contains many adjacent setup/undo turns.
    Combining those runs gives the continuation a compact, replayable restore
    path without attempting a solver rewrite. Unknown notation is left as a
    hard boundary rather than being guessed at.
    """

    amounts = {"": 1, "2": 2, "'": 3}
    suffixes = {0: "", 1: "", 2: "2", 3: "'"}
    collapsed: list[tuple[str, int]] = []
    for token in moves.split():
        if len(token) not in (1, 2) or token[0] not in "URFDLB" or token[1:] not in amounts:
            collapsed.append((token, -1))
            continue
        face = token[0]
        amount = amounts[token[1:]]
        if collapsed and collapsed[-1][0] == face and collapsed[-1][1] >= 0:
            total = (collapsed[-1][1] + amount) % 4
            collapsed.pop()
            if total:
                collapsed.append((face, total))
        else:
            collapsed.append((face, amount))
    return " ".join(face + suffixes[amount] if amount >= 0 else face for face, amount in collapsed)


def _fresh_reset_event() -> dict[str, Any]:
    """Mark the fresh MCP process boundary for host replay only."""

    return {
        "type": "item.completed",
        "item": {
            "id": "host-continuation-reset",
            "type": "mcp_tool_call",
            "server": "cubebench",
            "tool": "load_scramble",
            "arguments": {},
            "status": "completed",
            "error": None,
        },
    }


def build_resume_command(
    *,
    entry: batch_runner.BatchEntry,
    workspace: Path,
    thread_id: str,
    prompt: str,
    codex_bin: str = "codex",
) -> list[str]:
    """Build the exact ``codex exec resume`` invocation."""

    return [
        codex_bin,
        "exec",
        "--json",
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
        "resume",
        thread_id,
        prompt,
    ]


def build_continuation_prompt(
    *,
    batch: Any,
    entry: batch_runner.BatchEntry,
    summary: str,
    continuation_mode: str = "new_thread",
) -> str:
    base = batch_runner._prompt(batch, entry)
    conversation_warning = (
        "Codex is resuming the previous conversation, but the CubeBench MCP "
        "process and read-only workspace are fresh."
        if continuation_mode == "resume"
        else "This is a fresh Codex thread/workspace and a fresh CubeBench MCP process."
    )
    return (
        base
        + "\n\nCONTINUATION WARNING: "
        + conversation_warning
        + " The cube has been reset; call load_scramble() before "
        "any apply_moves() and do not rely on prior tool state.\n"
        + summary
        + "\nSubmit immediately on the first candidate for which check_task_complete "
        "returns true; do not spend another turn optimizing before making that "
        "submission."
    )


def _new_resume_dir() -> Path:
    base = REPO_ROOT / "runs" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_codex_gpt55_full_solve_resume"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_{suffix}")
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-run", type=Path, default=DEFAULT_ORIGINAL_RUN)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--codex-home", type=Path, default=None)
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--thread-id", default=None)
    parser.add_argument("--mode", choices=("auto", "resume", "new"), default="auto")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    original_run = args.original_run.expanduser().resolve()
    status = _status_payload(original_run)
    original_trace = Path(status.get("trace_path", original_run / "codex-events.jsonl"))
    original_trace = original_trace.expanduser().resolve()
    original_events = batch_runner.parse_jsonl(original_trace.read_text())
    thread_id = args.thread_id or _thread_id(original_trace)
    codex_home = (
        args.codex_home.expanduser().resolve()
        if args.codex_home is not None
        else Path(status.get("codex_home", DEFAULT_CODEX_HOME)).expanduser().resolve()
    )
    resume_available = thread_is_persisted(codex_home, thread_id)
    if args.mode == "resume":
        selected_mode = "resume"
    elif args.mode == "new":
        selected_mode = "new_thread"
    else:
        selected_mode = "resume" if resume_available else "new_thread"

    batch, entry = single_runner.load_single_full_solve(args.config.expanduser().resolve())
    summary = prior_summary(status, original_events)
    prompt = build_continuation_prompt(
        batch=batch,
        entry=entry,
        summary=summary,
        continuation_mode=selected_mode,
    )
    workspace_preview = Path("<fresh-read-only-workspace>")
    if selected_mode == "resume":
        command = build_resume_command(
            entry=entry,
            workspace=workspace_preview,
            thread_id=thread_id,
            prompt=prompt,
            codex_bin=args.codex_bin,
        )
    else:
        command = batch_runner.build_command(
            entry=entry,
            workspace=workspace_preview,
            prompt=prompt,
            codex_bin=args.codex_bin,
        )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "original_run": str(original_run),
                    "original_trace": str(original_trace),
                    "codex_home": str(codex_home),
                    "thread_id": thread_id,
                    "resume_available": resume_available,
                    "requested_mode": args.mode,
                    "selected_mode": selected_mode,
                    "fresh_mcp_reset_warning": True,
                    "timeout_seconds": args.timeout_seconds,
                    "command": command,
                    "prior_summary": summary,
                },
                indent=2,
            )
        )
        return 0

    if not codex_home.is_dir():
        raise FileNotFoundError(f"Original isolated CODEX_HOME is missing: {codex_home}")
    resume_dir = _new_resume_dir()
    resume_trace = resume_dir / "resume-codex-events.jsonl"
    resume_stderr = resume_dir / "resume-codex-stderr.txt"
    combined_trace = resume_dir / "combined-codex-events.jsonl"
    timed_out = False
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment.pop("CODEX_API_KEY", None)
    environment.pop("OPENAI_API_KEY", None)
    from codex_tool_isolation import prepare
    isolation_args = prepare(codex_home, entry.model_name, args.codex_bin, resume_dir / "tool-isolation")
    try:
        with tempfile.TemporaryDirectory(prefix="cubebench-codex-resume-") as workspace:
            command = (  # replace preview workspace with a real fresh directory
                build_resume_command(
                    entry=entry,
                    workspace=Path(workspace),
                    thread_id=thread_id,
                    prompt=prompt,
                    codex_bin=args.codex_bin,
                )
                if selected_mode == "resume"
                else batch_runner.build_command(
                    entry=entry,
                    workspace=Path(workspace),
                    prompt=prompt,
                    codex_bin=args.codex_bin,
                )
            )
            command[2:2] = isolation_args
            (resume_dir / "launch-command.json").write_text(json.dumps(command, indent=2))
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=args.timeout_seconds,
            )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        exit_code = None

    resume_trace.write_text(stdout)
    resume_stderr.write_text(stderr)
    continuation_events = batch_runner.parse_jsonl(stdout)
    combined_events = original_events + continuation_events
    combined_trace.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in combined_events) + "\n"
    )
    # A resumed Codex process still starts a fresh MCP server. Inject a reset
    # boundary into the in-memory replay stream so continuation moves cannot
    # accidentally be appended to the old cube trajectory.
    replay_events = original_events + [_fresh_reset_event()] + continuation_events
    resolution = batch_runner.resolve_trace_solution(
        events=replay_events,
        task="full_solve",
        cube=batch.cube,
        scramble=batch.scramble or single_runner.SCRAMBLE,
        repo_root=REPO_ROOT,
    )
    error = resolution["verification_error"]
    if not error and exit_code not in {0, None}:
        error = stderr.strip()[-4000:] or f"codex exited with status {exit_code}"
    result = {
        "run_id": resume_dir.name,
        "task": "full_solve",
        "task_label": "full_cube",
        "scramble_name": batch.scramble_name,
        "scramble": batch.scramble,
        "model": entry.model_name,
        "model_label": entry.raw_name,
        "provider": "openai",
        "requested_reasoning_effort": entry.requested_reasoning_effort,
        "reasoning_effort": entry.effective_reasoning_effort,
        "solution": resolution["solution"],
        "solution_source": resolution["solution_source"],
        "success": bool(resolution["verified"]),
        "verified": bool(resolution["verified"]),
        "timed_out": timed_out,
        "codex_exit_code": exit_code,
        "error": error,
        "usage": batch_runner.collect_usage(continuation_events),
        "continuation_mode": selected_mode,
        "requested_mode": args.mode,
        "resume_available": resume_available,
        "same_thread_resume_attempted": selected_mode == "resume",
        "thread_id": thread_id,
        "codex_home": str(codex_home),
        "original_run": str(original_run),
        "original_trace_path": str(original_trace),
        "resume_trace_path": str(resume_trace),
        "combined_trace_path": str(combined_trace),
        "fresh_mcp_reset_injected": True,
        "checkpoint_report": resolution["checkpoint_report"],
    }
    (resume_dir / "resume-status.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({"run_dir": str(resume_dir), "status": result}, indent=2, sort_keys=True))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
