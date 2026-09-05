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
    "cross": TaskDefinition(
        id="cross",
        label="Cross",
        objective="Solve a cross on any face in as few moves as possible.",
        success_criteria=(
            "The task is colour-neutral: any whole-cube orientation may satisfy it.",
            "Some face must have a solved cross matched to its adjacent side centers.",
            "The rest of the cube may remain unsolved.",
        ),
        final_response_format=(
            "Return only the move sequence that reaches a cross solution with the fewest moves you found in WCA standard outer block turn metric."
        ),
    ),
    "one_face": TaskDefinition(
        id="one_face",
        label="One Face",
        objective="Solve any single 3x3 face in as few moves as possible.",
        success_criteria=(
            "The task is colour-neutral: any whole-cube orientation may satisfy it.",
            "Some face must show a solid 3x3 color, but adjacent side stickers do not need to line up with their centers.",
            "The rest of the cube may remain unsolved.",
        ),
        final_response_format=(
            "Return only the move sequence that reaches a one_face solution with the fewest moves you found in WCA standard outer block turn metric."
        ),
    ),
    "one_layer": TaskDefinition(
        id="one_layer",
        label="One Layer",
        objective="Solve any full 3x3x1 layer in as few moves as possible.",
        success_criteria=(
            "The task is colour-neutral: any whole-cube orientation may satisfy it.",
            "Some full layer must be solved, including the face and the matching side stickers around that layer.",
            "The remaining two layers may stay unsolved.",
        ),
        final_response_format=(
            "Return only the move sequence that reaches a one_layer solution with the fewest moves you found in WCA standard outer block turn metric."
        ),
    ),
    "f2l": TaskDefinition(
        id="f2l",
        label="F2L",
        objective="Solve any 3x3x2 block in as few moves as possible.",
        success_criteria=(
            "The task is colour-neutral: any whole-cube orientation may satisfy it.",
            "Some full 3x3x2 block must be solved.",
            "Equivalently, under some whole-cube orientation, a full layer and the adjacent middle layer are solved.",
            "The opposite outer layer may remain unsolved.",
        ),
        final_response_format=(
            "Return only the move sequence that reaches an f2l solution with the fewest moves you found in WCA standard outer block turn metric."
        ),
    ),
    "full_solve": TaskDefinition(
        id="full_solve",
        label="Full Solve",
        objective="Solve the entire cube in as few moves as possible.",
        success_criteria=(
            "All pieces must be solved; whole-cube orientation does not matter.",
            "Use the completion check to confirm the cube is fully solved before concluding.",
        ),
        final_response_format=(
            "Return only the move sequence that fully solves the cube with the fewest moves you found in WCA standard outer block turn metric."
        ),
    ),
}


def get_task_definition(task_id: str) -> TaskDefinition:
    try:
        return TASK_DEFINITIONS[task_id]
    except KeyError as exc:
        supported = ", ".join(sorted(TASK_DEFINITIONS))
        raise ValueError(f"Unsupported task '{task_id}'. Choose one of: {supported}.") from exc
