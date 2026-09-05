"""Stop a Codex process at a reported reasoning budget or wall-clock deadline."""
import json
import signal
import os
import subprocess
import time


def reported_usage(home):
    latest = None
    for path in sorted((home / 'sessions').rglob('*.jsonl')):
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # The writer may be midway through the last record.
            payload = event.get('payload', {})
            if payload.get('type') == 'token_count' and payload.get('info'):
                usage = payload['info'].get('total_token_usage')
                if usage and (latest is None or usage.get('reasoning_output_tokens', 0) >= latest.get('reasoning_output_tokens', 0)):
                    latest = usage
    return latest


def run(command, *, home, budget, timeout, report_path, **kwargs):
    if budget <= 0 or timeout <= 0:
        raise ValueError('Budgets must be positive')
    started = time.monotonic()
    reason = None
    with subprocess.Popen(command, start_new_session=True, **kwargs) as process:
        while True:
            usage = reported_usage(home)
            elapsed = time.monotonic() - started
            if usage and usage.get('reasoning_output_tokens', 0) >= budget:
                reason = 'reasoning_token_budget'
            elif elapsed >= timeout:
                reason = 'wall_clock_timeout'
            report_path.write_text(json.dumps({
                'reasoning_token_budget': budget, 'timeout_seconds': timeout,
                'elapsed_seconds': elapsed, 'usage': usage, 'stop_reason': reason,
                'enforcement': 'reported totals only; an in-flight response can overshoot',
            }, indent=2))
            if reason:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                break
            try:
                stdout, stderr = process.communicate(timeout=min(2, max(.01, timeout - elapsed)))
                break
            except subprocess.TimeoutExpired:
                pass
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), reason
