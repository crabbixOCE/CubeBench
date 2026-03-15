from __future__ import annotations

import json
from copy import deepcopy

from google.genai import Client, types

from ..config import HarnessConfig
from ..env import require_google_api_key
from ..logging import RunLogger
from ..models import ProviderResult, ToolDefinition
from ..prompting import build_google_prompt
from ..tooling import ToolExecutor


def _to_google_tools(tooldefs: list[ToolDefinition]) -> list[types.Tool]:
    declarations = [
        types.FunctionDeclaration(
            name=tooldef.name,
            description=tooldef.description,
            parameters_json_schema=deepcopy(tooldef.input_schema),
        )
        for tooldef in tooldefs
    ]
    return [types.Tool(function_declarations=declarations)]


def _extract_reasoning(response) -> list[str]:
    traces: list[str] = []

    for candidate in response.candidates or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in content.parts or []:
            thought = getattr(part, "thought", None)
            if thought:
                traces.append(str(thought))

    return traces


def _build_thinking_config(config: HarnessConfig) -> types.ThinkingConfig:
    if (
        config.google.thinking_level is not None
        and config.google.thinking_budget is not None
    ):
        raise ValueError(
            "Google config cannot set both thinking_level and thinking_budget."
        )

    kwargs: dict[str, object] = {
        "include_thoughts": config.google.include_thoughts,
    }
    if config.google.thinking_level is not None:
        kwargs["thinking_level"] = config.google.thinking_level
    elif config.google.thinking_budget is not None:
        kwargs["thinking_budget"] = config.google.thinking_budget

    return types.ThinkingConfig(**kwargs)


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
    contents: list[types.Content | str] = list(prompt["contents"])
    system_instruction = prompt["system_instruction"]

    turn = 1
    while turn <= config.max_turns:
        response = client.models.generate_content(
            model=config.model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=tools,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
                thinking_config=_build_thinking_config(config),
                max_output_tokens=config.google.max_output_tokens,
            ),
        )

        logger.log_verbose_event(f"google response turn {turn}", response.model_dump())
        for trace in _extract_reasoning(response):
            logger.log_reasoning("google", turn, trace)

        candidate = response.candidates[0]
        content = candidate.content
        function_calls = [
            part.function_call for part in content.parts or [] if getattr(part, "function_call", None)
        ]
        text_parts = [part.text for part in content.parts or [] if getattr(part, "text", None)]
        final_text = "\n".join(text_parts).strip()

        if not function_calls:
            if final_text:
                logger.log_compact_model_output(final_text)
            return ProviderResult(final_text=final_text)

        contents.append(content)

        function_responses = []
        for call in function_calls:
            arguments = dict(call.args or {})
            result = tool_executor.execute(call.name, arguments)
            logger.log_compact_tool_call(call.name, arguments)
            logger.log_verbose_event(
                f"tool call turn {turn}: {call.name}",
                {"arguments": arguments, "result": result},
            )
            function_responses.append(
                types.Part.from_function_response(
                    name=call.name,
                    response=result,
                )
            )

        contents.append(types.Content(role="user", parts=function_responses))
        turn += 1

    raise RuntimeError(f"Google run exceeded max_turns={config.max_turns}.")
