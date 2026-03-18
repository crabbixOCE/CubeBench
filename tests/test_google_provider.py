from __future__ import annotations

import unittest
from types import SimpleNamespace

from cubebench_harness.config import HarnessConfig
from cubebench_harness.providers.google_provider import _build_generation_config
from cubebench_harness.providers.google_provider import _extract_function_calls
from cubebench_harness.providers.google_provider import _extract_reasoning
from cubebench_harness.providers.google_provider import _extract_text
from cubebench_harness.providers.google_provider import _output_tokens
from cubebench_harness.providers.google_provider import _to_google_tools
from cubebench_harness.tooling import build_common_tooldefs


class GoogleProviderToolSchemaTests(unittest.TestCase):
    def test_google_tools_use_interactions_function_schema(self) -> None:
        tools = _to_google_tools(build_common_tooldefs())
        payload = tools

        for declaration in payload:
            self.assertEqual(declaration["type"], "function")
            self.assertIn("parameters", declaration)

        apply_moves = next(
            declaration
            for declaration in payload
            if declaration["name"] == "apply_moves"
        )
        self.assertEqual(
            apply_moves["parameters"]["additionalProperties"],
            False,
        )


class GoogleGenerationConfigTests(unittest.TestCase):
    def test_prefers_thinking_level_when_set(self) -> None:
        config = HarnessConfig(
            provider="google",
            model_name="gemini-3.1-pro-preview",
            cube="3x3",
            representation="cubie_json",
            scramble_name="test",
            scramble="R U",
            task="test",
        )
        config.google.thinking_level = "high"

        generation_config = _build_generation_config(config)
        payload = generation_config

        self.assertEqual(payload["thinking_level"], "high")
        self.assertEqual(payload["thinking_summaries"], "auto")

    def test_rejects_thinking_budget(self) -> None:
        config = HarnessConfig(
            provider="google",
            model_name="gemini-3.1-pro-preview",
            cube="3x3",
            representation="cubie_json",
            scramble_name="test",
            scramble="R U",
            task="test",
        )
        config.google.thinking_budget = 2048

        with self.assertRaisesRegex(
            ValueError,
            "does not support thinking_budget",
        ):
            _build_generation_config(config)


class GoogleResponseParsingTests(unittest.TestCase):
    def test_extract_reasoning_reads_thought_summaries(self) -> None:
        interaction = SimpleNamespace(
            outputs=[
                SimpleNamespace(type="text", text="visible answer"),
                SimpleNamespace(
                    type="thought",
                    summary=[
                        SimpleNamespace(text="private reasoning"),
                    ],
                ),
            ]
        )

        self.assertEqual(_extract_reasoning(interaction), ["private reasoning"])

    def test_extract_text_reads_text_outputs_only(self) -> None:
        interaction = SimpleNamespace(
            outputs=[
                SimpleNamespace(type="thought", summary=[SimpleNamespace(text="hidden")]),
                SimpleNamespace(type="text", text="R U R'"),
            ]
        )

        self.assertEqual(_extract_text(interaction), "R U R'")

    def test_extract_function_calls_reads_outputs(self) -> None:
        function_call = SimpleNamespace(type="function_call", name="apply_moves", id="call-1")
        interaction = SimpleNamespace(
            outputs=[
                SimpleNamespace(type="text", text="ignored"),
                function_call,
            ]
        )

        self.assertEqual(_extract_function_calls(interaction), [function_call])

    def test_output_tokens_reads_interactions_usage(self) -> None:
        interaction = SimpleNamespace(
            usage=SimpleNamespace(total_output_tokens=321, total_thought_tokens=99)
        )

        self.assertEqual(_output_tokens(interaction), 420)


if __name__ == "__main__":
    unittest.main()
