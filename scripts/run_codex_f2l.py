#!/usr/bin/env python3
"""Run exactly one GPT-5.5/xhigh F2L attempt through isolated Codex.

The launcher is intentionally dry-run friendly.  It never starts inference
when ``--dry-run`` is supplied, and it delegates trace replay/status handling
to :mod:`run_codex_batch`, including recovery of a host-verified checkpoint
when Codex timed out before making its final-submission call.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import run_codex_batch as batch_runner  # noqa: E402
from cubebench_harness.config import HarnessBatchConfig  # noqa: E402


DEFAULT_CONFIG = REPO_ROOT / "config.codex-gpt55-f2l.yaml"
DEFAULT_TEMPLATE = REPO_ROOT / "codex_home" / "config.toml.template"
DEFAULT_CODEX_HOME = Path.home() / ".codex-cubebench"
SCRAMBLE_NAME = "one_layer_01"
SCRAMBLE = "B U F B D F R L' F D2 F2 L' D2 F2 B2 R U2 L2 D2 L2 F"


def load_single(
    config_path: Path,
    *,
    expected_task: str,
) -> tuple[HarnessBatchConfig, batch_runner.BatchEntry]:
    """Load and strictly validate one GPT-5.5/xhigh task run."""

    batch = HarnessBatchConfig.from_yaml(config_path)
    if batch.tasks != [expected_task] or batch.n_runs_per_task != 1:
        raise ValueError(
            f"The GPT-5.5 smoke config must contain exactly one {expected_task} run."
        )
    if batch.scramble_name != SCRAMBLE_NAME or batch.scramble != SCRAMBLE:
        raise ValueError("The GPT-5.5 smoke config must use the fixed one_layer_01 scramble.")
    specs = batch.resolved_models()
    if len(specs) != 1 or specs[0].raw_name != "gpt-5.5-xhigh":
        raise ValueError("The GPT-5.5 smoke config must request gpt-5.5-xhigh.")
    spec = specs[0]
    if spec.provider != "openai" or spec.model_name != "gpt-5.5" or spec.reasoning_level != "xhigh":
        raise ValueError("The GPT-5.5 smoke config must resolve to gpt-5.5/xhigh.")
    return batch, batch_runner.BatchEntry(
        index=0,
        task=expected_task,
        task_index=0,
        model_index=0,
        raw_name=spec.raw_name,
        model_name=spec.model_name,
        requested_reasoning_effort="max",
        effective_reasoning_effort="xhigh",
    )


def load_single_f2l(config_path: Path) -> tuple[HarnessBatchConfig, batch_runner.BatchEntry]:
    """Load and strictly validate the one-run GPT-5.5 F2L plan."""

    return load_single(config_path, expected_task="f2l")


def load_single_full_solve(config_path: Path) -> tuple[HarnessBatchConfig, batch_runner.BatchEntry]:
    """Load and strictly validate the one-run GPT-5.5 full-solve plan."""

    return load_single(config_path, expected_task="full_solve")


def _new_run_dir(run_label: str) -> Path:
    base = REPO_ROOT / "runs" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_codex_gpt55_{run_label}"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_{suffix}")
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def parse_args(
    argv: list[str] | None = None,
    *,
    default_config: Path = DEFAULT_CONFIG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config)
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    default_config: Path = DEFAULT_CONFIG,
    expected_task: str = "f2l",
    run_label: str = "f2l",
) -> int:
    args = parse_args(argv, default_config=default_config)
    batch, entry = load_single(args.config.expanduser().resolve(), expected_task=expected_task)
    codex_home = args.codex_home.expanduser().resolve()
    template_path = args.template.expanduser().resolve()

    if args.dry_run:
        command = batch_runner.build_command(
            entry=entry,
            workspace=Path("<private-workspace>"),
            prompt="<prompt>",
            codex_bin=args.codex_bin,
        )
        print(
            json.dumps(
                {
                    "codex_home": str(codex_home),
                    "task": expected_task,
                    "model": entry.model_name,
                    "requested_reasoning_effort": entry.requested_reasoning_effort,
                    "reasoning_effort": entry.effective_reasoning_effort,
                    "scramble_name": SCRAMBLE_NAME,
                    "scramble": SCRAMBLE,
                    "timeout_seconds": args.timeout_seconds,
                    "command": command,
                    "tool_isolation": "Required before inference; runtime adds pinned catalog and disabled-host overrides. The final command is saved as launch-command.json.",
                    "rendered_config_preview": batch_runner.render_config_text(
                        template_path=template_path,
                        entry=entry,
                        task=expected_task,
                        scramble_name=SCRAMBLE_NAME,
                        scramble=SCRAMBLE,
                    ),
                },
                indent=2,
            )
        )
        return 0

    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    codex_home.chmod(0o700)
    run_dir = _new_run_dir(run_label)
    status = batch_runner._run_entry(
        batch=batch,
        entry=entry,
        template_path=template_path,
        base_codex_home=codex_home,
        batch_dir=run_dir,
        timeout_seconds=args.timeout_seconds,
        codex_bin=args.codex_bin,
    )
    (run_dir / "status.json").write_text(json.dumps([status], indent=2, sort_keys=True))
    print(json.dumps({"run_dir": str(run_dir), "status": status}, indent=2, sort_keys=True))
    return 0 if status["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
