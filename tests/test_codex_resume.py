from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_codex_batch as batch_runner  # noqa: E402
import run_codex_f2l as single_runner  # noqa: E402
import run_codex_full_solve_resume as resume_runner  # noqa: E402


class CodexResumeTests(unittest.TestCase):
    def test_missing_ephemeral_thread_is_detected_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertFalse(resume_runner.thread_is_persisted(home, "thread-missing"))

            db = home / "state_5.sqlite"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
                connection.commit()
            self.assertFalse(resume_runner.thread_is_persisted(home, "thread-ephemeral"))

    def test_persisted_thread_detection_and_resume_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = home / "state_5.sqlite"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO threads VALUES (?)", ("thread-saved",))
                connection.commit()
            self.assertTrue(resume_runner.thread_is_persisted(home, "thread-saved"))

        _, entry = single_runner.load_single_full_solve(
            REPO_ROOT / "config.codex-gpt55-full-solve.yaml"
        )
        command = resume_runner.build_resume_command(
            entry=entry,
            workspace=Path("/tmp/fresh"),
            thread_id="thread-saved",
            prompt="continue",
        )
        self.assertEqual(command[:3], ["codex", "exec", "--json"])
        self.assertNotIn("--ephemeral", command)
        self.assertLess(command.index("-C"), command.index("resume"))
        self.assertIn("thread-saved", command)
        self.assertIn("read-only", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertIn('model_reasoning_effort="xhigh"', command)

    def test_prior_summary_is_compact_and_includes_last_state(self) -> None:
        events = [
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "tool": "apply_moves",
                    "status": "completed",
                    "result": {
                        "structured_content": {
                            "state": {
                                "center": [0, 1, 2, 3, 4, 5],
                                "cp": [0] * 8,
                                "co": [0] * 8,
                                "ep": [0] * 12,
                                "eo": [0] * 12,
                            }
                        }
                    },
                },
            }
        ]
        summary = resume_runner.prior_summary(
            {
                "checkpoint_count": 52,
                "completed_checkpoint_count": 0,
                "final_checkpoint": {"move_count": 168},
            },
            events,
        )
        self.assertIn("52 legal checkpoints", summary)
        self.assertIn("last candidate 168 move tokens", summary)
        self.assertIn('"center":[0,1,2,3,4,5]', summary)

    def test_collapsed_restore_path_preserves_halted_final_state(self) -> None:
        run_dir = (
            REPO_ROOT
            / "runs"
            / "20260905T055253Z_codex_gpt55_full_solve"
            / "001_full_solve_gpt_5_5_xhigh"
        )
        status = resume_runner._status_payload(run_dir)
        final = status["final_checkpoint"]["moves"]
        collapsed = resume_runner.collapse_same_face_turns(final)

        self.assertEqual(len(collapsed.split()), 57)
        original = batch_runner.CubeJsBridge(repo_root=REPO_ROOT, cube="3x3")
        original.load_scramble(single_runner.SCRAMBLE)
        original.apply_moves(final)
        restored = batch_runner.CubeJsBridge(repo_root=REPO_ROOT, cube="3x3")
        restored.load_scramble(single_runner.SCRAMBLE)
        restored.apply_moves(collapsed)
        self.assertEqual(
            original.apply_moves("").cubie_json,
            restored.apply_moves("").cubie_json,
        )

    def test_fresh_reset_prevents_cross_trace_cumulative_moves(self) -> None:
        solution = (
            "R F R2 U2 L B' U F' D2 F2 B' R U2 R U' R2 U L2 U"
        )
        def call(tool: str, moves: str | None, ident: str) -> dict[str, object]:
            args = {} if moves is None else {"moves": moves}
            return {
                "type": "item.completed",
                "item": {
                    "id": ident,
                    "type": "mcp_tool_call",
                    "tool": tool,
                    "arguments": args,
                    "status": "completed",
                    "error": None,
                },
            }

        # Codex starts item numbering from item_0 in each process/thread.
        original = [
            {"type": "thread.started", "thread_id": "original"},
            call("load_scramble", None, "item_0"),
            call("apply_moves", "U", "item_1"),
        ]
        continuation = [
            {"type": "thread.started", "thread_id": "continuation"},
            call("load_scramble", None, "item_0"),
            call("apply_moves", solution, "item_1"),
        ]
        report = batch_runner.replay_checkpoints(
            events=original + [resume_runner._fresh_reset_event()] + continuation,
            task="full_solve",
            cube="3x3",
            scramble=single_runner.SCRAMBLE,
            repo_root=REPO_ROOT,
        )
        self.assertTrue(report["shortest_completed"])
        self.assertEqual(report["shortest_completed"]["moves"], solution)


if __name__ == "__main__":
    unittest.main()
