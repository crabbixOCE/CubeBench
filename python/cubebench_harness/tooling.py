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
                "current state together with the representation contract."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        ToolDefinition(
            name="get_state",
            description=(
                "Return the current cube state in the configured representation together "
                "with the representation contract."
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
                "white_cross requires UR, UF, UL, and UB edges to be in their solved slots "
                "with orientation 0. "
                "f2l requires white_cross plus URF, UFL, ULB, and UBR corners and FR, FL, "
                "BL, and BR edges to be in their solved slots with orientation 0. "
                "full_solve requires the entire cube to be solved."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "enum": ["white_cross", "f2l", "full_solve"],
                        "description": "The benchmark task id to validate.",
                    }
                },
                "required": ["task"],
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

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "load_scramble":
            result = self.bridge.load_scramble(self.config.scramble)
            self.scramble_loaded = True
            return {
                "representation": self.converter.name,
                "representation_contract": self.converter.contract_payload(),
                "state": self.converter.convert(asdict(result)),
            }

        if name == "get_state":
            result = self.bridge.get_state()
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

        raise ValueError(f"Unknown tool: {name}")
