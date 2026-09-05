#!/usr/bin/env python3
"""Run one fresh, isolated Astra/max attempt each for F2L and full solve."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path

import run_codex_batch as runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--timeout-seconds', type=float, default=900)
    parser.add_argument('--task', choices=['f2l', 'full_solve'])
    parser.add_argument('--reasoning-token-budget', type=int)
    parser.add_argument('--scramble')
    parser.add_argument('--scramble-name', default='fresh_full_solve')
    args = parser.parse_args()
    batch, entries = runner.load_batch(runner.DEFAULT_CONFIG)
    if args.scramble:
        batch.scramble = args.scramble
        batch.scramble_name = args.scramble_name
    entries = [e for e in entries if e.model_name == 'gpt-6-astra']
    if [e.task for e in entries] != ['f2l', 'full_solve']:
        raise RuntimeError('Expected exactly one Astra run per task')
    if args.task:
        entries = [e for e in entries if e.task == args.task]
    if args.timeout_seconds <= 0 or (args.reasoning_token_budget is not None and args.reasoning_token_budget <= 0):
        parser.error('Budgets must be positive')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    root = runner.REPO_ROOT / 'runs' / (stamp + '_astra_no_code')
    home = runner.DEFAULT_CODEX_HOME / root.name
    meta = {'run_dir': str(root), 'base_codex_home': str(home),
            'model': 'gpt-6-astra', 'reasoning_effort': 'max', 'tasks': [e.task for e in entries],
            'scramble': batch.scramble, 'scramble_name': batch.scramble_name,
            'representation': batch.representation, 'timeout_seconds': args.timeout_seconds,
            'reasoning_token_budget': args.reasoning_token_budget,
            'persist_session': True, 'tool_isolation_preflight': 'required', 'attempts_per_task': 1}
    if args.dry_run:
        print(json.dumps(meta, indent=2))
        return 0
    root.mkdir(parents=True)
    (root / 'launch.json').write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta), flush=True)
    statuses = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(runner._run_entry, batch=batch, entry=entry,
                                  template_path=runner.DEFAULT_TEMPLATE, base_codex_home=home,
                                  batch_dir=root, timeout_seconds=args.timeout_seconds,
                                  codex_bin='codex', persist_session=True,
                                  reasoning_token_budget=args.reasoning_token_budget): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {'task': entry.task, 'model': entry.model_name,
                          'success': False, 'error': str(exc), 'launcher_failed': True}
            statuses.append(result)
            statuses.sort(key=lambda s: s['task'])
            (root / 'status.json').write_text(json.dumps(statuses, indent=2))
            print(json.dumps({'task': entry.task, 'success': result['success'],
                              'timed_out': result.get('timed_out'),
                              'moves': len(result.get('solution', '').split()),
                              'source': result.get('solution_source'), 'error': result.get('error')}), flush=True)
    print('Completed: ' + str(root), flush=True)
    return 0 if all(s['success'] for s in statuses) else 1


if __name__ == '__main__':
    raise SystemExit(main())
