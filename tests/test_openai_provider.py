from __future__ import annotations

import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cubebench_harness.config import HarnessConfig
from cubebench_harness.models import ToolDefinition
from cubebench_harness.providers.openai_provider import _build_openai_input
from cubebench_harness.providers.openai_provider import _output_tokens
from cubebench_harness.providers.openai_provider import run_openai


class _FakeLogger:
    def log_verbose_event(self, *_args, **_kwargs) -> None:
        pass

    def log_reasoning(self, *_args, **_kwargs) -> None:
        pass

    def log_compact_tool_call(self, *_args, **_kwargs) -> None:
        pass

    def log_compact_model_output(self, *_args, **_kwargs) -> None:
        pass


class _FakeToolExecutor:
    def __init__(self) -> None:
        self.final_submission: str | None = None

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "load_scramble":
            return {"ok": True}
        if name == "make_final_submission":
            moves = str(arguments["moves"])
            self.final_submission = moves
            return {"submission_accepted": True, "submitted_moves": moves}
        raise AssertionError(f"unexpected tool call {name}")


class OpenAIUsageTests(unittest.TestCase):
    def test_output_tokens_reads_usage(self) -> None:
        response = SimpleNamespace(
            usage=SimpleNamespace(output_tokens=144)
        )

        self.assertEqual(_output_tokens(response), 144)

    def test_build_openai_input_can_mix_tool_outputs_and_prompt(self) -> None:
        input_items = _build_openai_input(
            [{"type": "function_call_output", "call_id": "call-1", "output": "{}"}],
            "Submit now.",
        )

        self.assertEqual(input_items[0]["type"], "function_call_output")
        self.assertEqual(input_items[1]["type"], "message")
        self.assertEqual(input_items[1]["role"], "user")
        self.assertEqual(input_items[1]["content"][0]["text"], "Submit now.")

    def test_run_openai_answers_pending_tool_call_before_forced_submission(self) -> None:
        config = HarnessConfig(
            provider="openai",
            model_name="gpt-test",
            cube="3x3",
            representation="cubie_json",
            scramble_name="demo",
            scramble="R",
            task="cross",
        )
        config.max_turns = 1

        first_response = SimpleNamespace(
            id="resp-1",
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="load_scramble",
                    arguments="{}",
                    call_id="call-1",
                )
            ],
            usage=SimpleNamespace(output_tokens=10),
            incomplete_details=None,
            output_text="",
            status="completed",
        )
        final_response = SimpleNamespace(
            id="resp-2",
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="make_final_submission",
                    arguments=json.dumps({"moves": "R'"}),
                    call_id="call-2",
                )
            ],
            usage=SimpleNamespace(output_tokens=5),
            incomplete_details=None,
            output_text="",
            status="completed",
        )

        calls: list[dict[str, object]] = []

        class _FakeResponses:
            def create(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    return first_response
                if len(calls) == 2:
                    return final_response
                raise AssertionError("unexpected extra response call")

        class _FakeClient:
            def __init__(self) -> None:
                self.responses = _FakeResponses()

        tooldefs = [
            ToolDefinition(
                name="load_scramble",
                description="load",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            ToolDefinition(
                name="make_final_submission",
                description="submit",
                input_schema={
                    "type": "object",
                    "properties": {"moves": {"type": "string"}},
                    "required": ["moves"],
                    "additionalProperties": False,
                },
            ),
        ]

        with patch("cubebench_harness.providers.openai_provider.OpenAI", return_value=_FakeClient()):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                result = run_openai(
                    config,
                    tooldefs,
                    _FakeToolExecutor(),
                    _FakeLogger(),
                    "contract",
                )

        self.assertEqual(result.final_text, "R'")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["previous_response_id"], "resp-1")
        self.assertEqual(calls[1]["input"][0]["type"], "function_call_output")
        self.assertEqual(calls[1]["input"][0]["call_id"], "call-1")
        self.assertEqual(calls[1]["input"][1]["type"], "message")
        self.assertIn("make_final_submission", calls[1]["input"][1]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
