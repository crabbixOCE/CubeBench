from __future__ import annotations

from .config import HarnessConfig
from .tasks import get_task_definition


def build_tool_required_prompt() -> str:
    return (
        "Do not answer in plain text. "
        "If you are ready to stop, call make_final_submission with the exact move sequence to score. "
        "Otherwise call another tool."
    )


def build_final_submission_tool_prompt() -> str:
    return (
        "Search budget is exhausted. Call make_final_submission with your single best move sequence now. "
        "Do not call any other tool."
    )


def build_openai_continuation_prompt() -> str:
    return (
        "Continue the task. "
        "If you are ready to stop, call make_final_submission. "
        "Otherwise call another tool. "
        "Do not stop with an empty response."
    )


def build_openai_terse_continuation_prompt() -> str:
    return (
        "Respond briefly. Call exactly one tool now. "
        "If you are ready to stop, call make_final_submission. "
        "Do not spend tokens on extra reasoning."
    )


def build_system_prompt(config: HarnessConfig, representation_contract: str) -> str:
    task_definition = get_task_definition(config.task)
    task_lines = "\n".join(f"- {line}" for line in task_definition.success_criteria)
    return (
        "You are solving a Rubik's Cube through tools.\n"
        "Use tools instead of guessing the cube state.\n"
        "Interpret all cube states strictly according to the representation contract below.\n"
        "Do not invent a different color scheme, face mapping, or index ordering.\n"
        "Benchmark tasks are colour-neutral: any whole-cube orientation that satisfies the task counts.\n"
        "Always call load_scramble() before attempting to solve.\n"
        "Use the state returned by load_scramble() and apply_moves(); there is no separate state-inspection tool.\n"
        "Minimize the move count using WCA standard outer block turn metric: each outer face turn such as U, R2, or F' counts as 1 move.\n"
        "After applying a candidate algorithm, verify the result with tools before concluding.\n"
        f"Before ending the run, call check_task_complete({{'task': '{task_definition.id}'}}) on your current candidate.\n"
        "If check_task_complete returns task_completed false, do not submit yet; continue searching.\n"
        "A correct check does not force you to stop; you may keep searching for a shorter sequence.\n"
        "When you are ready to stop, call make_final_submission with the exact move sequence to score.\n"
        "Do not end with plain text instead of make_final_submission.\n"
        "Do not use check_task_complete for a different task id than the configured benchmark task.\n"
        "If a response would otherwise be empty, continue by calling another tool.\n"
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
        f"Load it with the tool, use the returned states to plan, and solve the "
        f"configured benchmark task `{task_definition.id}` in as few moves as possible. "
        "Use make_final_submission to submit the exact sequence you want scored."
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
