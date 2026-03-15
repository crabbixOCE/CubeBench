from __future__ import annotations

import json

from anthropic import Anthropic

from ..config import HarnessConfig
from ..env import require_env
from ..logging import RunLogger
from ..models import ProviderResult, ToolDefinition
from ..prompting import build_anthropic_prompt
from ..tooling import ToolExecutor


def _to_anthropic_tools(tooldefs: list[ToolDefinition]) -> list[dict]:
    return [
        {
            "name": tooldef.name,
            "description": tooldef.description,
            "input_schema": tooldef.input_schema,
        }
        for tooldef in tooldefs
    ]


def _extract_reasoning(response) -> list[str]:
    traces: list[str] = []

    for block in response.content:
        if getattr(block, "type", None) == "thinking":
            traces.append(getattr(block, "thinking", ""))

    return traces


def run_anthropic(
    config: HarnessConfig,
    tooldefs: list[ToolDefinition],
    tool_executor: ToolExecutor,
    logger: RunLogger,
    representation_contract: str,
) -> ProviderResult:
    client = Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))
    prompt = build_anthropic_prompt(config, representation_contract)
    tools = _to_anthropic_tools(tooldefs)
    messages = list(prompt["messages"])

    turn = 1
    while turn <= config.max_turns:
        response = client.messages.create(
            model=config.model_name,
            system=prompt["system"],
            messages=messages,
            tools=tools,
            tool_choice={"type": "auto"},
            max_tokens=config.anthropic.max_tokens,
            thinking={
                "type": "enabled",
                "budget_tokens": config.anthropic.thinking_budget_tokens,
            },
        )

        logger.log_verbose_event(f"anthropic response turn {turn}", response.model_dump())
        for trace in _extract_reasoning(response):
            logger.log_reasoning("anthropic", turn, trace)

        tool_blocks = [block for block in response.content if block.type == "tool_use"]
        text_blocks = [block.text for block in response.content if block.type == "text"]
        final_text = "\n".join(text_blocks).strip()

        if not tool_blocks:
            if final_text:
                logger.log_compact_model_output(final_text)
            return ProviderResult(final_text=final_text)

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in tool_blocks:
            result = tool_executor.execute(block.name, dict(block.input))
            logger.log_compact_tool_call(block.name, dict(block.input))
            logger.log_verbose_event(
                f"tool call turn {turn}: {block.name}",
                {"arguments": dict(block.input), "result": result},
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})
        turn += 1

    raise RuntimeError(f"Anthropic run exceeded max_turns={config.max_turns}.")
