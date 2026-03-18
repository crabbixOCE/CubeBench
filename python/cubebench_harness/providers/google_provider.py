from __future__ import annotations

from copy import deepcopy
from typing import Any

from google.genai import Client

from ..config import HarnessConfig
from ..env import require_google_api_key
from ..logging import RunLogger
from ..models import ProviderResult, ToolDefinition
from ..prompting import (
    build_final_submission_tool_prompt,
    build_google_prompt,
    build_tool_required_prompt,
)
from ..tooling import ToolExecutor
from .common import maybe_build_submission_result, raise_missing_submission_error


def _to_google_tools(tooldefs: list[ToolDefinition]) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "name": tooldef.name,
            "description": tooldef.description,
            "parameters": deepcopy(tooldef.input_schema),
        }
        for tooldef in tooldefs
    ]


def _extract_reasoning(interaction: Any) -> list[str]:
    traces: list[str] = []

    for output in getattr(interaction, "outputs", None) or []:
        if getattr(output, "type", None) != "thought":
            continue

        for summary_part in getattr(output, "summary", None) or []:
            text = getattr(summary_part, "text", None)
            if text:
                traces.append(str(text))

    return traces


def _extract_text(interaction: Any) -> str:
    texts: list[str] = []

    for output in getattr(interaction, "outputs", None) or []:
        if getattr(output, "type", None) != "text":
            continue

        text = getattr(output, "text", None)
        if text:
            texts.append(str(text))

    return "\n".join(texts).strip()


def _extract_function_calls(interaction: Any) -> list[Any]:
    return [
        output
        for output in getattr(interaction, "outputs", None) or []
        if getattr(output, "type", None) == "function_call"
    ]


def _build_generation_config(config: HarnessConfig) -> dict[str, object]:
    if config.google.thinking_budget is not None:
        raise ValueError("Google Interactions API does not support thinking_budget.")

    kwargs: dict[str, object] = {
        "max_output_tokens": config.google.max_output_tokens,
        "thinking_summaries": "auto" if config.google.include_thoughts else "none",
    }
    if config.google.thinking_level is not None:
        kwargs["thinking_level"] = config.google.thinking_level

    return kwargs


def _output_tokens(interaction: Any) -> int:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return 0

    visible_output_tokens = int(getattr(usage, "total_output_tokens", 0) or 0)
    reasoning_output_tokens = int(
        getattr(usage, "total_reasoning_tokens", getattr(usage, "total_thought_tokens", 0)) or 0
    )
    return visible_output_tokens + reasoning_output_tokens


def _create_interaction(
    client: Client,
    config: HarnessConfig,
    tools: list[dict[str, object]],
    system_instruction: str,
    input_payload: object,
    previous_interaction_id: str | None = None,
    include_tools: bool = True,
):
    kwargs: dict[str, object] = {
        "model": config.model_name,
        "input": input_payload,
        "system_instruction": system_instruction,
        "generation_config": _build_generation_config(config),
    }
    if previous_interaction_id is not None:
        kwargs["previous_interaction_id"] = previous_interaction_id
    if include_tools:
        kwargs["tools"] = tools

    return client.interactions.create(**kwargs)


def _execute_function_calls(
    function_calls: list[Any],
    tool_executor: ToolExecutor,
    logger: RunLogger,
    turn: int,
    total_output_tokens: int,
) -> tuple[list[dict[str, object]], ProviderResult | None]:
    function_results: list[dict[str, object]] = []
    for call in function_calls:
        arguments = dict(getattr(call, "arguments", {}) or {})
        result = tool_executor.execute(call.name, arguments)
        logger.log_compact_tool_call(call.name, arguments)
        logger.log_verbose_event(
            f"tool call turn {turn}: {call.name}",
            {"arguments": arguments, "result": result},
        )
        submission_result = maybe_build_submission_result(
            call.name,
            tool_executor,
            total_output_tokens,
        )
        if submission_result is not None:
            return [], submission_result
        function_results.append(
            {
                "type": "function_result",
                "call_id": call.id,
                "name": call.name,
                "result": result,
            }
        )

    return function_results, None


def run_google(
    config: HarnessConfig,
    tooldefs: list[ToolDefinition],
    tool_executor: ToolExecutor,
    logger: RunLogger,
    representation_contract: str,
) -> ProviderResult:
    client = Client(api_key=require_google_api_key())
    prompt = build_google_prompt(config, representation_contract)
    tools = _to_google_tools(tooldefs)
    system_instruction = prompt["system_instruction"]
    user_input = prompt["contents"][0]
    final_submission_prompt = build_final_submission_tool_prompt()
    tool_required_prompt = build_tool_required_prompt()

    turn = 1
    total_output_tokens = 0
    previous_interaction_id: str | None = None
    interaction = _create_interaction(
        client=client,
        config=config,
        tools=tools,
        system_instruction=system_instruction,
        input_payload=user_input,
    )

    while turn <= config.max_turns:
        previous_interaction_id = interaction.id
        total_output_tokens += _output_tokens(interaction)
        logger.log_verbose_event(f"google response turn {turn}", interaction.model_dump())
        for trace in _extract_reasoning(interaction):
            logger.log_reasoning("google", turn, trace)

        function_calls = _extract_function_calls(interaction)
        final_text = _extract_text(interaction)

        if not function_calls:
            if final_text:
                logger.log_compact_model_output(final_text)

            if turn == config.max_turns:
                break

            turn += 1
            interaction = _create_interaction(
                client=client,
                config=config,
                tools=tools,
                system_instruction=system_instruction,
                input_payload=tool_required_prompt,
                previous_interaction_id=previous_interaction_id,
            )
            continue

        function_results, submission_result = _execute_function_calls(
            function_calls,
            tool_executor,
            logger,
            turn,
            total_output_tokens,
        )
        if submission_result is not None:
            return submission_result

        interaction = _create_interaction(
            client=client,
            config=config,
            tools=tools,
            system_instruction=system_instruction,
            input_payload=function_results,
            previous_interaction_id=previous_interaction_id,
        )
        turn += 1
        if turn > config.max_turns:
            previous_interaction_id = interaction.id
            total_output_tokens += _output_tokens(interaction)
            logger.log_verbose_event(f"google response turn {turn}", interaction.model_dump())
            for trace in _extract_reasoning(interaction):
                logger.log_reasoning("google", turn, trace)

            function_calls = _extract_function_calls(interaction)
            if function_calls:
                _, submission_result = _execute_function_calls(
                    function_calls,
                    tool_executor,
                    logger,
                    turn,
                    total_output_tokens,
                )
                if submission_result is not None:
                    return submission_result

            final_text = _extract_text(interaction)
            if final_text:
                logger.log_compact_model_output(final_text)
            break

    interaction = _create_interaction(
        client=client,
        config=config,
        tools=tools,
        system_instruction=system_instruction,
        input_payload=final_submission_prompt,
        previous_interaction_id=previous_interaction_id,
    )
    total_output_tokens += _output_tokens(interaction)
    logger.log_verbose_event("google final submission request", interaction.model_dump())
    for trace in _extract_reasoning(interaction):
        logger.log_reasoning("google", turn, trace)

    function_calls = _extract_function_calls(interaction)
    if function_calls:
        _, submission_result = _execute_function_calls(
            function_calls,
            tool_executor,
            logger,
            turn,
            total_output_tokens,
        )
        if submission_result is not None:
            return submission_result

    raise_missing_submission_error("Google", config.max_turns, total_output_tokens)
