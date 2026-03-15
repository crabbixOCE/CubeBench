from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    id: str
    label: str
    objective: str
    success_criteria: tuple[str, ...]
    final_response_format: str


TASK_DEFINITIONS: dict[str, TaskDefinition] = {
    "white_cross": TaskDefinition(
        id="white_cross",
        label="White Cross",
        objective="Solve the white cross only.",
        success_criteria=(
            "Interpret white literally from the representation contract, so white is the U face.",
            "The UR, UF, UL, and UB edge slots must each contain their matching edge cubie in solved orientation.",
            "The rest of the cube may remain unsolved.",
        ),
        final_response_format=(
            "Return only the move sequence that reaches a state satisfying the white_cross task."
        ),
    ),
    "f2l": TaskDefinition(
        id="f2l",
        label="F2L",
        objective="Solve the first two layers relative to the literal white face.",
        success_criteria=(
            "Interpret white literally from the representation contract, so white is the U face.",
            "The white cross must be solved: UR, UF, UL, and UB edges solved and oriented.",
            "The URF, UFL, ULB, and UBR corner slots must each contain their matching corner cubie in solved orientation.",
            "The FR, FL, BL, and BR edge slots must each contain their matching edge cubie in solved orientation.",
            "The D layer may remain unsolved.",
        ),
        final_response_format=(
            "Return only the move sequence that reaches a state satisfying the f2l task."
        ),
    ),
    "full_solve": TaskDefinition(
        id="full_solve",
        label="Full Solve",
        objective="Solve the entire cube.",
        success_criteria=(
            "All pieces must be in their solved positions and orientations.",
            "Use the completion check to confirm the cube is fully solved before concluding.",
        ),
        final_response_format=(
            "Return only the move sequence that reaches a fully solved cube."
        ),
    ),
}


def get_task_definition(task_id: str) -> TaskDefinition:
    try:
        return TASK_DEFINITIONS[task_id]
    except KeyError as exc:
        supported = ", ".join(sorted(TASK_DEFINITIONS))
        raise ValueError(f"Unsupported task '{task_id}'. Choose one of: {supported}.") from exc
