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

    def test_parses_openai_max_reasoning_suffix(self) -> None:
        spec = ModelSpec.parse("gpt-6-astra-max")

        self.assertEqual(spec.provider, "openai")
        self.assertEqual(spec.model_name, "gpt-6-astra")
        self.assertEqual(spec.reasoning_level, "max")

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

    def test_astra_config_is_single_white_cross_run(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = HarnessBatchConfig.from_yaml(repo_root / "config.astra.yaml")

        self.assertEqual(config.tasks, ["white_cross"])
        self.assertEqual(config.model_names, ["gpt-6-astra-max"])
        self.assertEqual(config.n_runs_per_task, 1)
        self.assertEqual(config.max_turns, 50)
        self.assertEqual(config.max_output_tokens, 100000)
        self.assertEqual(config.openai.reasoning_summary, "detailed")
        self.assertEqual(config.openai.compact_threshold, 175000)

        planned_run = config.expand_runs({"white_cross": ["probe-scramble"]})[0]
        run_config = config.build_run_config(planned_run)

        self.assertEqual(run_config.model_name, "gpt-6-astra")
        self.assertEqual(run_config.openai.reasoning_effort, "max")
        self.assertEqual(run_config.openai.compact_threshold, 175000)

    def test_astra_full_config_has_one_run_per_task(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = HarnessBatchConfig.from_yaml(repo_root / "config.astra-full.yaml")

        self.assertEqual(
            config.tasks,
            ["white_cross", "cross", "one_face", "one_layer", "f2l", "full_solve"],
        )
        self.assertEqual(config.model_names, ["gpt-6-astra-max"])
        self.assertEqual(config.n_runs_per_task, 1)
        self.assertEqual(config.max_turns, 50)
        self.assertEqual(config.max_output_tokens, 100000)
        self.assertEqual(config.openai.reasoning_summary, "detailed")
        self.assertEqual(config.openai.compact_threshold, 175000)

        scrambles = {task: [f"{task}-scramble"] for task in config.tasks}
        planned_runs = config.expand_runs(scrambles)

        self.assertEqual(len(planned_runs), 6)
        self.assertEqual([run.task for run in planned_runs], config.tasks)


if __name__ == "__main__":
    unittest.main()
