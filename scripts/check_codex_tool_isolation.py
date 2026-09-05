#!/usr/bin/env python3
"""Test the installed Codex tool dispatcher locally, without model inference."""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

import codex_tool_isolation as isolation
import run_codex_batch as runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='gpt-6-astra')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.output or runner.REPO_ROOT / 'runs' / (datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '_tool_isolation')
    home = root / 'home'
    entry = runner.BatchEntry(0, 'full_solve', 0, 0, args.model, args.model, 'max', 'max')
    runner.install_config(home, runner.render_config_text(template_path=runner.DEFAULT_TEMPLATE, entry=entry, task='full_solve'))
    isolation.prepare(home, args.model, 'codex', root / 'probe')
    print((root / 'probe/report.json').read_text())


if __name__ == '__main__':
    main()
