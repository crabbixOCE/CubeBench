#!/usr/bin/env python3
"""Run exactly one Astra full-solve diagnostic with session persistence.

Uses the current hardened batch settings and keeps the full session record.
No retries or parallel runs. The historical diagnostic predates the no-code
enforcement; new invocations use the same mandatory isolation probe as batches.
"""
from datetime import UTC, datetime
import argparse
import json
from pathlib import Path

import run_codex_batch as runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--timeout-seconds', type=float, default=900)
    args = parser.parse_args()
    batch, entries = runner.load_batch(runner.DEFAULT_CONFIG)
    entry, = [e for e in entries if e.task == 'full_solve' and e.model_name == 'gpt-6-astra']
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    run_dir = runner.REPO_ROOT / 'runs' / f'{stamp}_astra_persisted'
    base_home = runner.DEFAULT_CODEX_HOME / run_dir.name
    command = runner.build_command(entry=entry, workspace=Path('<private-workspace>'),
                                   prompt=runner._prompt(batch, entry), persist_session=True)
    metadata = {'model': entry.model_name, 'reasoning_effort': 'max',
                'persist_session': True, 'timeout_seconds': args.timeout_seconds,
                'run_dir': str(run_dir), 'base_codex_home': str(base_home),
                'command_template': command}
    if args.dry_run:
        print(json.dumps(metadata, indent=2))
        return 0
    run_dir.mkdir(parents=True)
    (run_dir / 'launch.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps({'run_dir': str(run_dir), 'base_codex_home': str(base_home)}), flush=True)
    status = runner._run_entry(batch=batch, entry=entry,
                              template_path=runner.DEFAULT_TEMPLATE,
                              base_codex_home=base_home, batch_dir=run_dir,
                              timeout_seconds=args.timeout_seconds, codex_bin='codex',
                              persist_session=True)
    status['persist_session'] = True
    (run_dir / 'status.json').write_text(json.dumps(status, indent=2))
    print(json.dumps(status, indent=2), flush=True)
    return 0 if status['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
