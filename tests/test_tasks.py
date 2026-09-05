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

        self.assertTrue(bridge.check_task_complete("white_cross").task_completed)
        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertTrue(bridge.check_task_complete("one_face").task_completed)
        self.assertTrue(bridge.check_task_complete("one_layer").task_completed)
        self.assertTrue(bridge.check_task_complete("f2l").task_completed)
        self.assertTrue(bridge.check_task_complete("full_solve").task_completed)

    def test_whole_cube_rotation_is_still_a_full_solve(self) -> None:
        bridge = self.make_bridge()
        bridge.apply_moves("x")

        self.assertFalse(bridge.check_task_complete("white_cross").task_completed)
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

        self.assertTrue(bridge.check_task_complete("white_cross").task_completed)
        self.assertTrue(bridge.check_task_complete("cross").task_completed)
        self.assertFalse(bridge.check_task_complete("one_face").task_completed)
        self.assertFalse(bridge.check_task_complete("one_layer").task_completed)
        self.assertFalse(bridge.check_task_complete("f2l").task_completed)
        self.assertFalse(bridge.check_task_complete("full_solve").task_completed)

    def test_white_cross_requires_the_literal_u_face(self) -> None:
        bridge = self.make_bridge()
        bridge.apply_moves("R")

        self.assertFalse(bridge.check_task_complete("white_cross").task_completed)
        self.assertTrue(bridge.check_task_complete("cross").task_completed)


class MoveNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]

    def make_bridge(self) -> CubeJsBridge:
        return CubeJsBridge(repo_root=self.repo_root, cube="3x3")

    def test_failed_wide_turn_sequence_matches_lowercase_primitive_expansion(self) -> None:
        wide_bridge = self.make_bridge()
        primitive_bridge = self.make_bridge()

        wide_result = wide_bridge.apply_moves("U Rw' E D2 F' B2 U2 M'")
        primitive_result = primitive_bridge.apply_moves("U r' E D2 F' B2 U2 M'")

        self.assertEqual(wide_result.facelet_string, primitive_result.facelet_string)
        self.assertEqual(wide_result.cubie_json, primitive_result.cubie_json)

    def test_all_wide_faces_and_aliases_are_equivalent(self) -> None:
        wide_bridge = self.make_bridge()
        primitive_bridge = self.make_bridge()

        wide_result = wide_bridge.apply_moves("Rw Lw Uw Dw Fw Bw Rw2 Lw' Uw2 Dw' Fw Bw2")
        primitive_result = primitive_bridge.apply_moves("r l u d f b r2 l' u2 d' f b2")

        self.assertEqual(wide_result.facelet_string, primitive_result.facelet_string)
        self.assertEqual(wide_result.cubie_json, primitive_result.cubie_json)

    def test_grouping_commutator_and_conjugate_expand_correctly(self) -> None:
        structured_bridge = self.make_bridge()
        primitive_bridge = self.make_bridge()

        structured_result = structured_bridge.apply_moves("(R U R' U')2 [F,R] [R: U]")
        primitive_result = primitive_bridge.apply_moves(
            "R U R' U' R U R' U' F R F' R' R U R'"
        )

        self.assertEqual(structured_result.facelet_string, primitive_result.facelet_string)
        self.assertEqual(structured_result.cubie_json, primitive_result.cubie_json)

    def test_slices_rotations_and_arbitrary_powers_are_normalized(self) -> None:
        structured_bridge = self.make_bridge()
        primitive_bridge = self.make_bridge()

        structured_result = structured_bridge.apply_moves("M2 E' S x3 y2 z")
        primitive_result = primitive_bridge.apply_moves("M2 E' S x' y2 z")

        self.assertEqual(structured_result.facelet_string, primitive_result.facelet_string)
        self.assertEqual(structured_result.cubie_json, primitive_result.cubie_json)

    def test_common_whitespace_is_accepted(self) -> None:
        whitespace_bridge = self.make_bridge()
        ordinary_bridge = self.make_bridge()

        whitespace_result = whitespace_bridge.apply_moves("U\tRw'\rE\nD2")
        ordinary_result = ordinary_bridge.apply_moves("U Rw' E D2")

        self.assertEqual(whitespace_result.facelet_string, ordinary_result.facelet_string)
        self.assertEqual(whitespace_result.cubie_json, ordinary_result.cubie_json)

    def test_invalid_move_family_is_rejected_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported move family 'Q'"):
            self.make_bridge().apply_moves("Q")


class TaskPromptAndToolingTests(unittest.TestCase):
    def test_system_prompt_uses_literal_white_cross_definition(self) -> None:
        config = HarnessConfig(
            provider="openai",
            model_name="gpt-test",
            cube="3x3",
            representation="cubie_json",
            scramble_name="demo",
            scramble="R U",
            task="white_cross",
        )

        prompt = build_system_prompt(config, "contract text")

        self.assertIn("Benchmark task id: white_cross", prompt)
        self.assertIn("Benchmark task: White Cross", prompt)
        self.assertIn("The UR, UF, UL, and UB edge slots", prompt)
        self.assertIn("white is the U face", prompt)

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
            ["white_cross", "cross", "one_face", "one_layer", "f2l", "full_solve"],
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
