#!/usr/bin/env python3
"""Run exactly one GPT-5.5/xhigh full-solve attempt through isolated Codex."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_codex_f2l import main as _run_single  # noqa: E402


DEFAULT_CONFIG = REPO_ROOT / "config.codex-gpt55-full-solve.yaml"


def main(argv: list[str] | None = None) -> int:
    return _run_single(
        argv,
        default_config=DEFAULT_CONFIG,
        expected_task="full_solve",
        run_label="full_solve",
    )


if __name__ == "__main__":
    raise SystemExit(main())
