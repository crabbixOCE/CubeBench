import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_token_budget as budget


class BudgetTests(unittest.TestCase):
    def test_partial_record_and_reasoning_only(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / 'sessions').mkdir()
            usage = {'reasoning_output_tokens': 100, 'output_tokens': 200}
            (home / 'sessions' / 'a.jsonl').write_text(json.dumps({'payload': {
                'type': 'token_count', 'info': {'total_token_usage': usage}}}) + '\n{"partial":')
            self.assertEqual(budget.reported_usage(home), usage)
            result, reason = budget.run([sys.executable, '-c', 'import time; time.sleep(60)'],
                home=home, budget=100, timeout=10, report_path=home / 'budget.json')
            self.assertEqual(reason, 'reasoning_token_budget')
            self.assertNotEqual(result.returncode, 0)

    def test_wall_clock_without_usage(self):
        with tempfile.TemporaryDirectory() as d:
            result, reason = budget.run([sys.executable, '-c', 'import time; time.sleep(60)'],
                home=Path(d), budget=100, timeout=.1, report_path=Path(d) / 'budget.json')
            self.assertEqual(reason, 'wall_clock_timeout')

    def test_normal_completion(self):
        with tempfile.TemporaryDirectory() as d:
            result, reason = budget.run([sys.executable, '-c', 'pass'],
                home=Path(d), budget=100, timeout=10, report_path=Path(d) / 'budget.json')
            self.assertIsNone(reason)
            self.assertEqual(result.returncode, 0)
