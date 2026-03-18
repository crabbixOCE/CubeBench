from __future__ import annotations

import json

from anthropic import Anthropic

from ..config import HarnessConfig
from ..env import require_env
from ..logging import RunLogger
from ..models import ProviderResult, ToolDefinition
from ..prompting import (
    build_anthropic_prompt,
    build_final_submission_tool_prompt,
    build_tool_required_prompt,
)
from ..tooling import ToolExecutor
from .common import maybe_build_submission_result, raise_missing_submission_error


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


def _output_tokens(response) -> int:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0

    return int(getattr(usage, "output_tokens", 0) or 0)


def _execute_tool_blocks(
    tool_blocks: list[object],
    tool_executor: ToolExecutor,
    logger: RunLogger,
    turn: int,
    total_output_tokens: int,
) -> tuple[list[dict[str, str]], ProviderResult | None]:
    tool_results = []
    for block in tool_blocks:
        arguments = dict(block.input)
        result = tool_executor.execute(block.name, arguments)
        logger.log_compact_tool_call(block.name, arguments)
        logger.log_verbose_event(
            f"tool call turn {turn}: {block.name}",
            {"arguments": arguments, "result": result},
        )
        submission_result = maybe_build_submission_result(
            block.name,
            tool_executor,
            total_output_tokens,
        )
        if submission_result is not None:
            return [], submission_result
        tool_results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            }
        )

    return tool_results, None


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
    final_submission_prompt = build_final_submission_tool_prompt()
    tool_required_prompt = build_tool_required_prompt()

    turn = 1
    total_output_tokens = 0
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

        total_output_tokens += _output_tokens(response)
        logger.log_verbose_event(f"anthropic response turn {turn}", response.model_dump())
        for trace in _extract_reasoning(response):
            logger.log_reasoning("anthropic", turn, trace)

        tool_blocks = [block for block in response.content if block.type == "tool_use"]
        text_blocks = [block.text for block in response.content if block.type == "text"]
        final_text = "\n".join(text_blocks).strip()

        if not tool_blocks:
            if final_text:
                logger.log_compact_model_output(final_text)
            messages.append({"role": "assistant", "content": response.content})
            if turn == config.max_turns:
                break
            messages.append({"role": "user", "content": tool_required_prompt})
            turn += 1
            continue

        messages.append({"role": "assistant", "content": response.content})

        tool_results, submission_result = _execute_tool_blocks(
            tool_blocks,
            tool_executor,
            logger,
            turn,
            total_output_tokens,
        )
        if submission_result is not None:
            return submission_result

        messages.append({"role": "user", "content": tool_results})
        turn += 1

    final_messages = list(messages)
    final_messages.append({"role": "user", "content": final_submission_prompt})
    response = client.messages.create(
        model=config.model_name,
        system=prompt["system"],
        messages=final_messages,
        tools=tools,
        tool_choice={"type": "auto"},
        max_tokens=config.anthropic.max_tokens,
        thinking={
            "type": "enabled",
            "budget_tokens": config.anthropic.thinking_budget_tokens,
        },
    )
    total_output_tokens += _output_tokens(response)
    logger.log_verbose_event("anthropic final submission request", response.model_dump())
    for trace in _extract_reasoning(response):
        logger.log_reasoning("anthropic", turn, trace)

    tool_blocks = [block for block in response.content if block.type == "tool_use"]
    if tool_blocks:
        _, submission_result = _execute_tool_blocks(
            tool_blocks,
            tool_executor,
            logger,
            turn,
            total_output_tokens,
        )
        if submission_result is not None:
            return submission_result

    raise_missing_submission_error("Anthropic", config.max_turns, total_output_tokens)
