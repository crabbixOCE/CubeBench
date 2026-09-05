from __future__ import annotations

from pathlib import Path
import unittest

from cubebench_harness.config import HarnessConfig
from cubebench_harness.runner import _verify_submitted_solution


class RunnerSubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_verify_submitted_solution_checks_explicit_submission(self) -> None:
        config = HarnessConfig(
            provider="openai",
            model_name="gpt-test",
            cube="3x3",
            representation="cubie_json",
            scramble_name="demo",
            scramble="R",
            task="full_solve",
        )

        verification = _verify_submitted_solution(
            self.repo_root,
            config,
            "R'",
        )

        self.assertEqual(verification.extracted_solution, "R'")
        self.assertTrue(verification.task_completion["task_completed"])

    def test_verify_submitted_solution_accepts_wide_notation(self) -> None:
        config = HarnessConfig(
            provider="openai",
            model_name="gpt-test",
            cube="3x3",
            representation="cubie_json",
            scramble_name="wide-demo",
            scramble="r",
            task="full_solve",
        )

        verification = _verify_submitted_solution(
            self.repo_root,
            config,
            "Rw'",
        )

        self.assertEqual(verification.extracted_solution, "Rw'")
        self.assertTrue(verification.task_completion["task_completed"])

    def test_verify_submitted_solution_rejects_missing_submission(self) -> None:
        config = HarnessConfig(
            provider="google",
            model_name="gemini-test",
            cube="3x3",
            representation="cubie_json",
            scramble_name="demo",
            scramble="R",
            task="full_solve",
        )

        verification = _verify_submitted_solution(
            self.repo_root,
            config,
            None,
        )

        self.assertEqual(verification.extracted_solution, "")
        self.assertFalse(verification.task_completion["task_completed"])

    def test_verify_submitted_solution_rejects_invalid_submission(self) -> None:
        config = HarnessConfig(
            provider="google",
            model_name="gemini-test",
            cube="3x3",
            representation="cubie_json",
            scramble_name="demo",
            scramble="R",
            task="full_solve",
        )

        verification = _verify_submitted_solution(
            self.repo_root,
            config,
            "R",
        )

        self.assertEqual(verification.extracted_solution, "R")
        self.assertFalse(verification.task_completion["task_completed"])


if __name__ == "__main__":
    unittest.main()
