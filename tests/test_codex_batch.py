from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import tomllib
import textwrap
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_codex_batch as runner  # noqa: E402
import run_codex_f2l as f2l_runner  # noqa: E402


class CodexBatchPlanTests(unittest.TestCase):
    def test_default_plan_is_two_tasks_by_two_models(self) -> None:
        batch, entries = runner.load_batch(runner.DEFAULT_CONFIG)

        self.assertEqual(batch.tasks, ["f2l", "full_solve"])
        self.assertEqual(batch.model_names, ["gpt-5.6-sol-max", "gpt-6-astra-max"])
        self.assertEqual(len(entries), 4)
        self.assertEqual(
            [(entry.task, entry.model_name) for entry in entries],
            [
                ("f2l", "gpt-5.6-sol"),
                ("f2l", "gpt-6-astra"),
                ("full_solve", "gpt-5.6-sol"),
                ("full_solve", "gpt-6-astra"),
            ],
        )
        self.assertTrue(all(entry.effective_reasoning_effort == "max" for entry in entries))

        planned = batch.expand_runs(batch.generated_scrambles())
        self.assertEqual(len(planned), 4)
        self.assertEqual({run.scramble for run in planned}, {runner.SCRAMBLE})
        self.assertEqual({run.scramble_name for run in planned}, {runner.SCRAMBLE_NAME})

    def test_fixed_scramble_can_be_shared_by_multiple_tasks(self) -> None:
        config_text = """
        cube: 3x3
        representation: cubie_json
        tasks: [f2l, full_solve]
        model_names: [gpt-5.6-sol-max]
        n_runs_per_task: 1
        scramble_name: shared
        scramble: R U
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(textwrap.dedent(config_text))
            config = runner.HarnessBatchConfig.from_yaml(path)

        self.assertEqual(config.generated_scrambles(), {"f2l": ["R U"], "full_solve": ["R U"]})

    def test_gpt55_f2l_plan_is_exactly_one_xhigh_run(self) -> None:
        batch, entry = f2l_runner.load_single_f2l(f2l_runner.DEFAULT_CONFIG)

        self.assertEqual(batch.tasks, ["f2l"])
        self.assertEqual(entry.model_name, "gpt-5.5")
        self.assertEqual(entry.effective_reasoning_effort, "xhigh")
        self.assertEqual(batch.scramble_name, f2l_runner.SCRAMBLE_NAME)
        self.assertEqual(batch.scramble, f2l_runner.SCRAMBLE)

    def test_gpt55_full_solve_plan_is_exactly_one_xhigh_run(self) -> None:
        batch, entry = f2l_runner.load_single_full_solve(
            REPO_ROOT / "config.codex-gpt55-full-solve.yaml"
        )

        self.assertEqual(batch.tasks, ["full_solve"])
        self.assertEqual(entry.model_name, "gpt-5.5")
        self.assertEqual(entry.requested_reasoning_effort, "max")
        self.assertEqual(entry.effective_reasoning_effort, "xhigh")
        self.assertEqual(batch.scramble_name, f2l_runner.SCRAMBLE_NAME)
        self.assertEqual(batch.scramble, f2l_runner.SCRAMBLE)


class CodexBatchRenderingTests(unittest.TestCase):
    def test_prompt_explicitly_forbids_execution_and_workarounds(self) -> None:
        batch, entries = runner.load_batch(runner.DEFAULT_CONFIG)
        for entry in entries:
            prompt = runner._prompt(batch, entry)
            self.assertIn("Code execution is disallowed and disabled", prompt)
            self.assertIn("Do not search for execution tools", prompt)
            self.assertIn("look for workarounds", prompt)
            self.assertIn("call them directly", prompt)

    def test_rendered_config_is_toml_and_scopes_mcp_tools(self) -> None:
        _, entries = runner.load_batch(runner.DEFAULT_CONFIG)
        rendered = runner.render_config_text(
            template_path=runner.DEFAULT_TEMPLATE,
            entry=entries[2],
            task=entries[2].task,
            scramble_name=runner.SCRAMBLE_NAME,
            scramble=runner.SCRAMBLE,
            compact_threshold=175000,
        )
        parsed = tomllib.loads(rendered)

        self.assertNotIn("__CUBEBENCH_", rendered)
        self.assertEqual(parsed["model"], "gpt-5.6-sol")
        self.assertEqual(parsed["model_reasoning_effort"], "max")
        self.assertEqual(parsed["approval_policy"], "never")
        self.assertEqual(parsed["sandbox_mode"], "read-only")
        self.assertEqual(parsed["web_search"], "disabled")
        self.assertFalse(parsed["features"]["shell_tool"])
        self.assertFalse(parsed["features"]["unified_exec"])
        self.assertFalse(parsed["features"]["code_mode_host"])
        self.assertFalse(parsed["features"]["apps"])
        self.assertFalse(parsed["features"]["plugins"])
        self.assertFalse(parsed["features"]["multi_agent"])
        self.assertEqual(
            parsed["mcp_servers"]["cubebench"]["enabled_tools"],
            ["load_scramble", "apply_moves", "check_task_complete", "make_final_submission"],
        )
        self.assertEqual(parsed["mcp_servers"]["cubebench"]["default_tools_approval_mode"], "approve")
        self.assertEqual(parsed["mcp_servers"]["cubebench"]["args"][3], "full_solve")

    def test_command_is_read_only_and_never_requests_approval(self) -> None:
        _, entries = runner.load_batch(runner.DEFAULT_CONFIG)
        command = runner.build_command(entry=entries[0], workspace=Path("/tmp/isolated"), prompt="prompt")

        self.assertEqual(command[:3], ["codex", "exec", "--json"])
        self.assertNotIn("--ephemeral", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--strict-config", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertIn("model_reasoning_effort=\"max\"", command)


class CodexBatchEventTests(unittest.TestCase):
    @staticmethod
    def _call(tool: str, arguments: dict[str, object], ident: str) -> dict[str, object]:
        return {
            "type": "item.completed",
            "item": {
                "id": ident,
                "type": "mcp_tool_call",
                "server": "cubebench",
                "tool": tool,
                "arguments": arguments,
                "status": "completed",
                "error": None,
            },
        }

    def test_submission_requires_completed_error_free_mcp_call(self) -> None:
        events = runner.parse_jsonl(
            "\n".join(
                [
                    json.dumps({
                        "type": "item.started",
                        "item": {
                            "type": "mcp_tool_call",
                            "tool": "make_final_submission",
                            "arguments": {"moves": "BAD"},
                            "status": "in_progress",
                        },
                    }),
                    json.dumps({
                        "type": "item.completed",
                        "item": {
                            "type": "mcp_tool_call",
                            "tool": "mcp__cubebench__make_final_submission",
                            "arguments": json.dumps({"moves": "R U"}),
                            "status": "completed",
                            "error": None,
                        },
                    }),
                    "not json",
                ]
            )
        )
        self.assertEqual(runner.extract_submission(events), "R U")

    def test_usage_preserves_codex_output_token_semantics(self) -> None:
        events = runner.parse_jsonl(
            json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 90,
                    "output_tokens": 12,
                    "reasoning_output_tokens": 8,
                },
            })
        )
        usage = runner.collect_usage(events)
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage["output_tokens"], 12)
        self.assertEqual(usage["total_output_tokens_used"], 12)

    def test_replay_recovers_shortest_completed_checkpoint_after_reset(self) -> None:
        solution = "R2 D F B2 U B R2 U L B2 R L2 U F"
        events = [
            self._call("load_scramble", {}, "load-1"),
            self._call("apply_moves", {"moves": "U U' " + solution}, "apply-long"),
            self._call("load_scramble", {}, "load-2"),
            self._call("apply_moves", {"moves": solution}, "apply-short"),
        ]

        report = runner.replay_checkpoints(
            events=events,
            task="f2l",
            cube="3x3",
            scramble=runner.SCRAMBLE,
            repo_root=REPO_ROOT,
        )

        self.assertEqual(report["checkpoint_count"], 2)
        self.assertEqual(report["completed_checkpoint_count"], 2)
        self.assertEqual(report["shortest_completed"]["moves"], solution)
        self.assertEqual(report["shortest_completed"]["reset_index"], 2)

        resolution = runner.resolve_trace_solution(
            events=events,
            task="f2l",
            cube="3x3",
            scramble=runner.SCRAMBLE,
            repo_root=REPO_ROOT,
        )
        self.assertEqual(resolution["solution"], solution)
        self.assertTrue(resolution["verified"])
        self.assertEqual(resolution["solution_source"], "recovered_checkpoint")

    def test_replay_keeps_final_unverified_candidate_without_marking_success(self) -> None:
        events = [
            self._call("load_scramble", {}, "load-1"),
            self._call("apply_moves", {"moves": "U"}, "apply-1"),
        ]

        resolution = runner.resolve_trace_solution(
            events=events,
            task="f2l",
            cube="3x3",
            scramble=runner.SCRAMBLE,
            repo_root=REPO_ROOT,
        )

        self.assertEqual(resolution["solution"], "U")
        self.assertFalse(resolution["verified"])
        self.assertEqual(resolution["solution_source"], "final_checkpoint_unverified")


if __name__ == "__main__":
    unittest.main()
