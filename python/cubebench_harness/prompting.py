from __future__ import annotations

from .config import HarnessConfig
from .tasks import get_task_definition


def build_system_prompt(config: HarnessConfig, representation_contract: str) -> str:
    task_definition = get_task_definition(config.task)
    task_lines = "\n".join(f"- {line}" for line in task_definition.success_criteria)
    return (
        "You are solving a Rubik's Cube through tools.\n"
        "Use tools instead of guessing the cube state.\n"
        "Interpret all cube states strictly according to the representation contract below.\n"
        "Do not invent a different color scheme, face mapping, or index ordering.\n"
        "When the task mentions colors such as white, use the stated face/color mapping literally.\n"
        "Always call load_scramble() before attempting to solve.\n"
        "After applying a candidate algorithm, verify the result with tools before concluding.\n"
        f"Before giving the final answer, call check_task_complete({{'task': '{task_definition.id}'}}).\n"
        "Do not use check_task_complete for a different task id than the configured benchmark task.\n"
        "If a response would otherwise be empty, continue by calling another tool or giving the final answer.\n"
        "Be concise and action-oriented.\n"
        f"Cube: {config.cube}\n"
        f"Benchmark task id: {task_definition.id}\n"
        f"Benchmark task: {task_definition.label}\n"
        f"Objective: {task_definition.objective}\n"
        "Success criteria:\n"
        f"{task_lines}\n"
        f"Final response format: {task_definition.final_response_format}\n"
        "Representation contract:\n"
        f"{representation_contract}\n"
    )


def build_user_prompt(config: HarnessConfig) -> str:
    task_definition = get_task_definition(config.task)
    return (
        "A hidden scramble has been configured in the harness.\n"
        f"Load it with the tool, inspect the resulting state if needed, and solve the "
        f"configured benchmark task: {task_definition.id}."
    )


def build_openai_prompt(config: HarnessConfig, representation_contract: str) -> dict[str, str]:
    return {
        "instructions": build_system_prompt(config, representation_contract),
        "input": build_user_prompt(config),
    }


def build_anthropic_prompt(config: HarnessConfig, representation_contract: str) -> dict[str, object]:
    return {
        "system": build_system_prompt(config, representation_contract),
        "messages": [{"role": "user", "content": build_user_prompt(config)}],
    }


def build_google_prompt(config: HarnessConfig, representation_contract: str) -> dict[str, object]:
    return {
        "system_instruction": build_system_prompt(config, representation_contract),
        "contents": [build_user_prompt(config)],
    }
