from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cubebench_harness.plot_results import build_plot_points, count_moves, load_status_records


class PlotResultsTests(unittest.TestCase):
    def test_count_moves_counts_outer_turn_tokens(self) -> None:
        self.assertEqual(count_moves("R U R' U'"), 4)
        self.assertEqual(count_moves(""), 0)

    def test_build_plot_points_filters_unsuccessful_and_missing_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            payload = [
                {
                    "error": None,
                    "events_path": str(run_dir / "artifacts" / "001" / "events.txt"),
                    "model": "gpt-5.4-high",
                    "provider": "openai",
                    "reasoning_path": str(run_dir / "artifacts" / "001" / "reasoning.txt"),
                    "run_id": "001",
                    "scramble": "R U",
                    "scramble_name": "cross_01",
                    "solution": "R U R'",
                    "success": True,
                    "task_name": "cross",
                    "task_run_index": 1,
                    "total_output_tokens_used": 1234,
                },
                {
                    "error": "failed",
                    "events_path": str(run_dir / "artifacts" / "002" / "events.txt"),
                    "model": "gpt-5.4-high",
                    "provider": "openai",
                    "reasoning_path": str(run_dir / "artifacts" / "002" / "reasoning.txt"),
                    "run_id": "002",
                    "scramble": "R U",
                    "scramble_name": "cross_02",
                    "solution": "U R",
                    "success": False,
                    "task_name": "cross",
                    "task_run_index": 2,
                    "total_output_tokens_used": 500,
                },
                {
                    "error": None,
                    "events_path": str(run_dir / "artifacts" / "003" / "events.txt"),
                    "model": "gemini-3.1-pro-preview-high",
                    "provider": "google",
                    "reasoning_path": str(run_dir / "artifacts" / "003" / "reasoning.txt"),
                    "run_id": "003",
                    "scramble": "R U",
                    "scramble_name": "cross_03",
                    "solution": "F2",
                    "success": True,
                    "task_name": "cross",
                    "task_run_index": 3,
                    "total_output_tokens_used": None,
                },
            ]
            (run_dir / "status.json").write_text(json.dumps(payload))

            records = load_status_records(run_dir)
            points = build_plot_points(records)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].run_id, "001")
        self.assertEqual(points[0].move_count, 3)
        self.assertEqual(points[0].reasoning_effort, 1234)


if __name__ == "__main__":
    unittest.main()
