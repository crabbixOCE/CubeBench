from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap
import unittest

from cubebench_harness.config import HarnessBatchConfig
from cubebench_harness.config import ModelSpec


class ModelSpecParsingTests(unittest.TestCase):
    def test_parses_openai_reasoning_suffix_and_normalizes_name(self) -> None:
        spec = ModelSpec.parse("gpt5.4-high")

        self.assertEqual(spec.provider, "openai")
        self.assertEqual(spec.model_name, "gpt-5.4")
        self.assertEqual(spec.reasoning_level, "high")

    def test_parses_openai_xhigh_reasoning_suffix(self) -> None:
        spec = ModelSpec.parse("gpt-5.4-xhigh")

        self.assertEqual(spec.provider, "openai")
        self.assertEqual(spec.model_name, "gpt-5.4")
        self.assertEqual(spec.reasoning_level, "xhigh")

    def test_parses_google_reasoning_suffix(self) -> None:
        spec = ModelSpec.parse("gemini-3.1-pro-preview-high")

        self.assertEqual(spec.provider, "google")
        self.assertEqual(spec.model_name, "gemini-3.1-pro-preview")
        self.assertEqual(spec.reasoning_level, "high")


class BatchConfigExpansionTests(unittest.TestCase):
    def test_expand_runs_shares_scrambles_within_task_run(self) -> None:
        config = HarnessBatchConfig(
            cube="3x3",
            representation="cubie_json",
            tasks=["cross", "f2l"],
            model_names=["gpt5.4-high", "gemini-3.1-pro-preview-high"],
            n_runs_per_task=2,
        )

        planned_runs = config.expand_runs(
            {
                "cross": ["cross-scramble-1", "cross-scramble-2"],
                "f2l": ["f2l-scramble-1", "f2l-scramble-2"],
            }
        )

        self.assertEqual(len(planned_runs), 8)

        cross_run_one = [
            planned_run
            for planned_run in planned_runs
            if planned_run.task == "cross" and planned_run.task_run_index == 1
        ]
        self.assertEqual([planned_run.scramble for planned_run in cross_run_one], ["cross-scramble-1"] * 2)
        self.assertEqual([planned_run.model.raw_name for planned_run in cross_run_one], config.model_names)

        f2l_run_two = [
            planned_run
            for planned_run in planned_runs
            if planned_run.task == "f2l" and planned_run.task_run_index == 2
        ]
        self.assertEqual([planned_run.scramble for planned_run in f2l_run_two], ["f2l-scramble-2"] * 2)

        openai_run = config.build_run_config(cross_run_one[0])
        google_run = config.build_run_config(cross_run_one[1])

        self.assertEqual(openai_run.provider, "openai")
        self.assertEqual(openai_run.model_name, "gpt-5.4")
        self.assertEqual(openai_run.openai.reasoning_effort, "high")

        self.assertEqual(google_run.provider, "google")
        self.assertEqual(google_run.model_name, "gemini-3.1-pro-preview")
        self.assertEqual(google_run.google.thinking_level, "high")
        self.assertIsNone(google_run.google.thinking_budget)

    def test_from_yaml_accepts_legacy_single_run_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                textwrap.dedent(
                    """
                    provider: openai
                    model_name: gpt-5.4
                    cube: 3x3
                    representation: cubie_json
                    scramble_name: demo
                    scramble: "R U"
                    task: cross
                    """
                ).strip()
            )

            config = HarnessBatchConfig.from_yaml(config_path)

        self.assertEqual(config.tasks, ["cross"])
        self.assertEqual(config.model_names, ["gpt-5.4"])
        self.assertEqual(config.generated_scrambles(), {"cross": ["R U"]})

    def test_build_run_config_applies_openai_xhigh_reasoning_effort(self) -> None:
        config = HarnessBatchConfig(
            cube="3x3",
            representation="cubie_json",
            tasks=["cross"],
            model_names=["gpt-5.4-xhigh"],
        )

        planned_run = config.expand_runs({"cross": ["cross-scramble-1"]})[0]
        run_config = config.build_run_config(planned_run)

        self.assertEqual(run_config.provider, "openai")
        self.assertEqual(run_config.model_name, "gpt-5.4")
        self.assertEqual(run_config.openai.reasoning_effort, "xhigh")


if __name__ == "__main__":
    unittest.main()
