from __future__ import annotations

import json

from openai import OpenAI

from ..config import HarnessConfig
from ..env import require_env
from ..logging import RunLogger
from ..models import ProviderResult, ToolDefinition
from ..prompting import build_openai_prompt
from ..tooling import ToolExecutor


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
    }


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
    continuation_prompt = (
        "Continue the task. If you are not finished, call another tool. "
        "Do not stop with an empty response."
    )
    terse_continuation_prompt = (
        "Respond briefly. Either call exactly one tool now or provide the final answer now. "
        "Do not spend tokens on extra reasoning."
    )
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
                return ProviderResult(final_text=final_text)

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

            turn += 1
            response = client.responses.create(
                model=config.model_name,
                previous_response_id=response.id,
                input=follow_up_prompt,
                tools=tools,
                reasoning=follow_up_reasoning,
                max_output_tokens=config.max_output_tokens,
            )
            logger.log_verbose_event(f"openai continuation turn {turn}", _response_summary(response))
            for trace in _extract_reasoning(response):
                logger.log_reasoning("openai", turn, trace)
            continue

        blank_response_streak = 0

        tool_outputs = []
        for call in function_calls:
            arguments = json.loads(call.arguments or "{}")
            result = tool_executor.execute(call.name, arguments)
            logger.log_compact_tool_call(call.name, arguments)
            logger.log_verbose_event(
                f"tool call turn {turn}: {call.name}",
                {"arguments": arguments, "result": result},
            )
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }
            )

        turn += 1
        response = client.responses.create(
            model=config.model_name,
            previous_response_id=response.id,
            input=tool_outputs,
            tools=tools,
            reasoning={
                "effort": config.openai.reasoning_effort,
                "summary": config.openai.reasoning_summary,
            },
            max_output_tokens=config.max_output_tokens,
        )
        logger.log_verbose_event(f"openai response turn {turn}", _response_summary(response))
        for trace in _extract_reasoning(response):
            logger.log_reasoning("openai", turn, trace)

    raise RuntimeError(f"OpenAI run exceeded max_turns={config.max_turns}.")
