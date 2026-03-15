from __future__ import annotations

import unittest
from types import SimpleNamespace

from cubebench_harness.config import HarnessConfig
from cubebench_harness.providers.google_provider import _build_thinking_config
from cubebench_harness.providers.google_provider import _extract_reasoning
from cubebench_harness.providers.google_provider import _to_google_tools
from cubebench_harness.tooling import build_common_tooldefs


class GoogleProviderToolSchemaTests(unittest.TestCase):
    def test_google_tools_use_json_schema_parameters(self) -> None:
        tools = _to_google_tools(build_common_tooldefs())
        payload = tools[0].model_dump(by_alias=True, exclude_none=True)
        function_declarations = payload["functionDeclarations"]

        for declaration in function_declarations:
            self.assertIn("parametersJsonSchema", declaration)
            self.assertNotIn("parameters", declaration)

        apply_moves = next(
            declaration
            for declaration in function_declarations
            if declaration["name"] == "apply_moves"
        )
        self.assertEqual(
            apply_moves["parametersJsonSchema"]["additionalProperties"],
            False,
        )


class GoogleThinkingConfigTests(unittest.TestCase):
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

        thinking_config = _build_thinking_config(config)
        payload = thinking_config.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(str(payload["thinkingLevel"].value), "HIGH")
        self.assertNotIn("thinkingBudget", payload)

    def test_uses_thinking_budget_when_level_is_unset(self) -> None:
        config = HarnessConfig(
            provider="google",
            model_name="gemini-2.5-pro",
            cube="3x3",
            representation="cubie_json",
            scramble_name="test",
            scramble="R U",
            task="test",
        )
        config.google.thinking_budget = 2048

        thinking_config = _build_thinking_config(config)
        payload = thinking_config.model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(payload["thinkingBudget"], 2048)
        self.assertNotIn("thinkingLevel", payload)

    def test_rejects_level_and_budget_together(self) -> None:
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
        config.google.thinking_budget = 2048

        with self.assertRaisesRegex(
            ValueError,
            "cannot set both thinking_level and thinking_budget",
        ):
            _build_thinking_config(config)


class GoogleResponseParsingTests(unittest.TestCase):
    def test_extract_reasoning_ignores_text_parts(self) -> None:
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(text="intermediate text", thought=None),
                            SimpleNamespace(text=None, thought="private reasoning"),
                        ]
                    )
                )
            ]
        )

        self.assertEqual(_extract_reasoning(response), ["private reasoning"])


if __name__ == "__main__":
    unittest.main()
