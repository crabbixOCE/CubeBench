from __future__ import annotations

import json

from openai import OpenAI

from ..config import HarnessConfig
from ..env import require_env
from ..logging import RunLogger
from ..models import ProviderResult, ToolDefinition
from ..prompting import (
    build_final_submission_tool_prompt,
    build_openai_continuation_prompt,
    build_openai_prompt,
    build_openai_terse_continuation_prompt,
    build_tool_required_prompt,
)
from ..tooling import ToolExecutor
from .common import maybe_build_submission_result, raise_missing_submission_error


def _to_openai_tools(tooldefs: list[ToolDefinition]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": tooldef.name,
            "description": tooldef.description,
            "parameters": tooldef.input_schema,
        }
        for tooldef in tooldefs
    ]


def _extract_reasoning(response) -> list[str]:
    traces: list[str] = []

    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "reasoning":
            continue

        summaries = getattr(item, "summary", None) or []
        for summary in summaries:
            text = getattr(summary, "text", None)
            if text:
                traces.append(text)

    return traces


def _extract_text(response) -> str:
    if getattr(response, "output_text", ""):
        return response.output_text

    texts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue

        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) in {"output_text", "text"}:
                text = getattr(content, "text", None)
                if text:
                    texts.append(text)

    return "\n".join(texts).strip()


def _response_summary(response) -> dict:
    return {
        "id": getattr(response, "id", None),
        "status": getattr(response, "status", None),
        "output_types": [getattr(item, "type", None) for item in getattr(response, "output", []) or []],
        "output_text": _extract_text(response),
        "incomplete_details": getattr(response, "incomplete_details", None),
        "usage": getattr(response, "usage", None),
    }


def _output_tokens(response) -> int:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0

    return int(getattr(usage, "output_tokens", 0) or 0)


def _execute_tool_calls(
    function_calls: list[object],
    tool_executor: ToolExecutor,
    logger: RunLogger,
    turn: int,
    total_output_tokens: int,
) -> tuple[list[dict[str, str]], ProviderResult | None]:
    tool_outputs = []
    for call in function_calls:
        arguments = json.loads(call.arguments or "{}")
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
        tool_outputs.append(
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result),
            }
        )

    return tool_outputs, None


def _build_openai_input(
    tool_outputs: list[dict[str, str]],
    prompt: str | None = None,
) -> list[dict[str, object]]:
    input_items: list[dict[str, object]] = list(tool_outputs)
    if prompt is not None:
        input_items.append(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        )
    return input_items


def run_openai(
    config: HarnessConfig,
    tooldefs: list[ToolDefinition],
    tool_executor: ToolExecutor,
    logger: RunLogger,
    representation_contract: str,
) -> ProviderResult:
    client = OpenAI(api_key=require_env("OPENAI_API_KEY"))
    prompt = build_openai_prompt(config, representation_contract)
    tools = _to_openai_tools(tooldefs)
    continuation_prompt = build_openai_continuation_prompt()
    final_submission_prompt = build_final_submission_tool_prompt()
    terse_continuation_prompt = build_openai_terse_continuation_prompt()
    tool_required_prompt = build_tool_required_prompt()
    blank_response_streak = 0

    response = client.responses.create(
        model=config.model_name,
        instructions=prompt["instructions"],
        input=prompt["input"],
        tools=tools,
        reasoning={
            "effort": config.openai.reasoning_effort,
            "summary": config.openai.reasoning_summary,
        },
        max_output_tokens=config.max_output_tokens,
    )

    turn = 1
    total_output_tokens = _output_tokens(response)
    logger.log_verbose_event("openai initial response", _response_summary(response))
    for trace in _extract_reasoning(response):
        logger.log_reasoning("openai", turn, trace)

    while turn <= config.max_turns:
        function_calls = [
            item for item in getattr(response, "output", []) or []
            if getattr(item, "type", None) == "function_call"
        ]
        final_text = _extract_text(response)
        if not function_calls:
            if final_text:
                logger.log_compact_model_output(final_text)
                blank_response_streak = 0
                follow_up_prompt = tool_required_prompt
                follow_up_reasoning = {
                    "effort": "low",
                    "summary": config.openai.reasoning_summary,
                }
            else:
                blank_response_streak += 1
                incomplete_reason = None
                incomplete_details = getattr(response, "incomplete_details", None)
                if incomplete_details is not None:
                    incomplete_reason = getattr(incomplete_details, "reason", None)

                follow_up_prompt = continuation_prompt
                follow_up_reasoning = {
                    "effort": config.openai.reasoning_effort,
                    "summary": config.openai.reasoning_summary,
                }
                if incomplete_reason == "max_output_tokens" or blank_response_streak > 1:
                    follow_up_prompt = terse_continuation_prompt
                    follow_up_reasoning = {
                        "effort": "low",
                        "summary": config.openai.reasoning_summary,
                    }

            if turn == config.max_turns:
                break

            turn += 1
            response = client.responses.create(
                model=config.model_name,
                previous_response_id=response.id,
                input=follow_up_prompt,
                tools=tools,
                reasoning=follow_up_reasoning,
                max_output_tokens=config.max_output_tokens,
            )
            total_output_tokens += _output_tokens(response)
            logger.log_verbose_event(f"openai continuation turn {turn}", _response_summary(response))
            for trace in _extract_reasoning(response):
                logger.log_reasoning("openai", turn, trace)
            continue

        blank_response_streak = 0

        tool_outputs, submission_result = _execute_tool_calls(
            function_calls,
            tool_executor,
            logger,
            turn,
            total_output_tokens,
        )
        if submission_result is not None:
            return submission_result

        if turn == config.max_turns:
            response = client.responses.create(
                model=config.model_name,
                previous_response_id=response.id,
                input=_build_openai_input(tool_outputs, final_submission_prompt),
                tools=tools,
                reasoning={"effort": "low", "summary": config.openai.reasoning_summary},
                max_output_tokens=config.max_output_tokens,
            )
            total_output_tokens += _output_tokens(response)
            logger.log_verbose_event("openai final submission request", _response_summary(response))
            for trace in _extract_reasoning(response):
                logger.log_reasoning("openai", turn, trace)

            function_calls = [
                item for item in getattr(response, "output", []) or []
                if getattr(item, "type", None) == "function_call"
            ]
            if function_calls:
                _, submission_result = _execute_tool_calls(
                    function_calls,
                    tool_executor,
                    logger,
                    turn,
                    total_output_tokens,
                )
                if submission_result is not None:
                    return submission_result

            raise_missing_submission_error("OpenAI", config.max_turns, total_output_tokens)

        turn += 1
        response = client.responses.create(
            model=config.model_name,
            previous_response_id=response.id,
            input=_build_openai_input(tool_outputs),
            tools=tools,
            reasoning={
                "effort": config.openai.reasoning_effort,
                "summary": config.openai.reasoning_summary,
            },
            max_output_tokens=config.max_output_tokens,
        )
        total_output_tokens += _output_tokens(response)
        logger.log_verbose_event(f"openai response turn {turn}", _response_summary(response))
        for trace in _extract_reasoning(response):
            logger.log_reasoning("openai", turn, trace)

    response = client.responses.create(
        model=config.model_name,
        previous_response_id=response.id,
        input=final_submission_prompt,
        tools=tools,
        reasoning={"effort": "low", "summary": config.openai.reasoning_summary},
        max_output_tokens=config.max_output_tokens,
    )
    total_output_tokens += _output_tokens(response)
    logger.log_verbose_event("openai final submission request", _response_summary(response))
    for trace in _extract_reasoning(response):
        logger.log_reasoning("openai", turn, trace)

    function_calls = [
        item for item in getattr(response, "output", []) or []
        if getattr(item, "type", None) == "function_call"
    ]
    if function_calls:
        _, submission_result = _execute_tool_calls(
            function_calls,
            tool_executor,
            logger,
            turn,
            total_output_tokens,
        )
        if submission_result is not None:
            return submission_result

    raise_missing_submission_error("OpenAI", config.max_turns, total_output_tokens)
