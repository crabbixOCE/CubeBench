from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .config import HarnessConfig
from .converters import StateConverter
from .cube_bridge import CubeJsBridge
from .models import ToolDefinition


def build_common_tooldefs() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="load_scramble",
            description=(
                "Reset the cube to solved, apply the configured scramble, and return the "
                "updated state together with the representation contract."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        ToolDefinition(
            name="apply_moves",
            description=(
                "Apply a space-separated sequence of cube moves to the current state, then "
                "return the updated state together with the representation contract."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "moves": {
                        "type": "string",
                        "description": "A cube algorithm such as R U R' U'.",
                    }
                },
                "required": ["moves"],
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="check_task_complete",
            description=(
                "Check whether the current cube satisfies a benchmark task. "
                "Use this to verify correctness of a candidate sequence before deciding whether to keep searching for a shorter one. "
                "Tasks are colour-neutral, so any whole-cube orientation may satisfy them. "
                "cross requires some face to have a solved cross matched to its side centers. "
                "one_face requires some face to be a solid 3x3 face. "
                "one_layer requires some 3x3x1 layer to be fully solved. "
                "f2l requires some 3x3x2 block to be fully solved. "
                "full_solve requires the entire cube to be solved."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "enum": ["cross", "one_face", "one_layer", "f2l", "full_solve"],
                        "description": "The benchmark task id to validate.",
                    }
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="make_final_submission",
            description=(
                "Submit the exact move sequence to score for this benchmark run and end the run. "
                "Call this only when you are ready to stop searching. "
                "You may use check_task_complete to verify correctness first, but you can continue searching after a correct check if you want a shorter solution."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "moves": {
                        "type": "string",
                        "description": "The exact move sequence to submit for scoring.",
                    }
                },
                "required": ["moves"],
                "additionalProperties": False,
            },
        ),
    ]


class ToolExecutor:
    def __init__(
        self,
        config: HarnessConfig,
        bridge: CubeJsBridge,
        converter: StateConverter,
    ) -> None:
        self.config = config
        self.bridge = bridge
        self.converter = converter
        self.scramble_loaded = False
        self.final_submission: str | None = None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "load_scramble":
            result = self.bridge.load_scramble(self.config.scramble)
            self.scramble_loaded = True
            return {
                "representation": self.converter.name,
                "representation_contract": self.converter.contract_payload(),
                "state": self.converter.convert(asdict(result)),
            }

        if name == "apply_moves":
            moves = arguments.get("moves", "").strip()
            if not moves:
                raise ValueError("apply_moves requires a non-empty 'moves' string.")
            result = self.bridge.apply_moves(moves)
            return {
                "applied_moves": moves,
                "representation": self.converter.name,
                "representation_contract": self.converter.contract_payload(),
                "state": self.converter.convert(asdict(result)),
            }

        if name == "check_task_complete":
            task = arguments.get("task", "").strip()
            if not task:
                raise ValueError("check_task_complete requires a non-empty 'task' string.")
            result = self.bridge.check_task_complete(task)
            return asdict(result)

        if name == "make_final_submission":
            moves = arguments.get("moves", "").strip()
            if not moves:
                raise ValueError("make_final_submission requires a non-empty 'moves' string.")
            self.final_submission = moves
            return {
                "submission_accepted": True,
                "submitted_moves": moves,
            }

        raise ValueError(f"Unknown tool: {name}")
