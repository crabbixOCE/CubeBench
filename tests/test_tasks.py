from __future__ import annotations

from pathlib import Path
import unittest

from cubebench_harness.config import HarnessConfig
from cubebench_harness.cube_bridge import CubeJsBridge
from cubebench_harness.prompting import build_system_prompt
from cubebench_harness.tooling import build_common_tooldefs


class TaskCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]

    def make_bridge(self) -> CubeJsBridge:
        return CubeJsBridge(repo_root=self.repo_root, cube="3x3")

    def test_solved_cube_satisfies_all_tasks(self) -> None:
        bridge = self.make_bridge()

        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertTrue(bridge.check_task_complete("one_face").task_completed)
        self.assertTrue(bridge.check_task_complete("one_layer").task_completed)
        self.assertTrue(bridge.check_task_complete("f2l").task_completed)
        self.assertTrue(bridge.check_task_complete("full_solve").task_completed)

    def test_whole_cube_rotation_is_still_a_full_solve(self) -> None:
        bridge = self.make_bridge()
        bridge.apply_moves("x")

        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertTrue(bridge.check_task_complete("one_face").task_completed)
        self.assertTrue(bridge.check_task_complete("one_layer").task_completed)
        self.assertTrue(bridge.check_task_complete("f2l").task_completed)
        self.assertTrue(bridge.check_task_complete("full_solve").task_completed)

    def test_d_turn_keeps_f2l_but_not_full_solve(self) -> None:
        bridge = self.make_bridge()
        bridge.apply_moves("D")

        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertTrue(bridge.check_task_complete("one_face").task_completed)
        self.assertTrue(bridge.check_task_complete("one_layer").task_completed)
        self.assertTrue(bridge.check_task_complete("f2l").task_completed)
        self.assertFalse(bridge.check_task_complete("full_solve").task_completed)

    def test_sequence_can_keep_one_layer_but_break_f2l(self) -> None:
        bridge = self.make_bridge()
        bridge.apply_moves("U R2 E' R2")

        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertTrue(bridge.check_task_complete("one_face").task_completed)
        self.assertTrue(bridge.check_task_complete("one_layer").task_completed)
        self.assertFalse(bridge.check_task_complete("f2l").task_completed)
        self.assertFalse(bridge.check_task_complete("full_solve").task_completed)

    def test_sequence_can_keep_one_face_but_break_one_layer(self) -> None:
        bridge = self.make_bridge()
        bridge.apply_moves("U2 M2 D2 M2")

        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertTrue(bridge.check_task_complete("one_face").task_completed)
        self.assertFalse(bridge.check_task_complete("one_layer").task_completed)
        self.assertFalse(bridge.check_task_complete("f2l").task_completed)
        self.assertFalse(bridge.check_task_complete("full_solve").task_completed)

    def test_rdr_prime_keeps_cross_but_breaks_one_face(self) -> None:
        bridge = self.make_bridge()
        bridge.apply_moves("R D R'")

        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertFalse(bridge.check_task_complete("one_face").task_completed)
        self.assertFalse(bridge.check_task_complete("one_layer").task_completed)
        self.assertFalse(bridge.check_task_complete("f2l").task_completed)
        self.assertFalse(bridge.check_task_complete("full_solve").task_completed)


class TaskPromptAndToolingTests(unittest.TestCase):
    def test_system_prompt_uses_explicit_task_definition(self) -> None:
        config = HarnessConfig(
            provider="openai",
            model_name="gpt-test",
            cube="3x3",
            representation="cubie_json",
            scramble_name="demo",
            scramble="R U",
            task="cross",
        )

        prompt = build_system_prompt(config, "contract text")

        self.assertIn("Benchmark task id: cross", prompt)
        self.assertIn("Benchmark task: Cross", prompt)
        self.assertIn("check_task_complete({'task': 'cross'})", prompt)
        self.assertIn("make_final_submission", prompt)
        self.assertIn("WCA standard outer block turn metric", prompt)
        self.assertIn("colour-neutral", prompt)

    def test_tooldefs_use_check_task_complete(self) -> None:
        tooldefs = build_common_tooldefs()
        names = [tooldef.name for tooldef in tooldefs]

        self.assertIn("check_task_complete", names)
        self.assertIn("make_final_submission", names)
        self.assertNotIn("get_state", names)
        self.assertNotIn("is_solved", names)

        check_task_complete = next(
            tooldef for tooldef in tooldefs if tooldef.name == "check_task_complete"
        )
        self.assertEqual(
            check_task_complete.input_schema["properties"]["task"]["enum"],
            ["cross", "one_face", "one_layer", "f2l", "full_solve"],
        )

        make_final_submission = next(
            tooldef for tooldef in tooldefs if tooldef.name == "make_final_submission"
        )
        self.assertEqual(
            make_final_submission.input_schema["required"],
            ["moves"],
        )


if __name__ == "__main__":
    unittest.main()
