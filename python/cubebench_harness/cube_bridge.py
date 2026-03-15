from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CubeBridgeResult:
    cube: str
    facelet_string: str
    cubie_json: dict[str, Any]
    is_solved: bool


@dataclass(slots=True)
class TaskCheckResult:
    task: str
    task_completed: bool


class CubeJsBridge:
    def __init__(self, repo_root: Path, cube: str) -> None:
        self.repo_root = repo_root
        self.cube = cube
        self.script_path = repo_root / "scripts" / "cubejs_bridge.mjs"
        self._state: str | None = None

    def load_scramble(self, scramble: str) -> CubeBridgeResult:
        result = self._invoke(state=None, moves=scramble)
        self._state = result.facelet_string
        return result

    def apply_moves(self, moves: str) -> CubeBridgeResult:
        result = self._invoke(state=self._state, moves=moves)
        self._state = result.facelet_string
        return result

    def get_state(self) -> CubeBridgeResult:
        result = self._invoke(state=self._state, moves=None)
        self._state = result.facelet_string
        return result

    def is_solved(self) -> bool:
        return self.get_state().is_solved

    def check_task_complete(self, task: str) -> TaskCheckResult:
        data = self._run(
            {
                "cube": self.cube,
                "state": self._state,
                "moves": None,
                "check_task": task,
            }
        )
        self._state = data["facelet_string"]
        return TaskCheckResult(task=data["task"], task_completed=data["task_completed"])

    def _invoke(self, state: str | None, moves: str | None) -> CubeBridgeResult:
        data = self._run({"cube": self.cube, "state": state, "moves": moves})
        return CubeBridgeResult(
            cube=data["cube"],
            facelet_string=data["facelet_string"],
            cubie_json=data["cubie_json"],
            is_solved=data["is_solved"],
        )

    def _run(self, payload: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            ["node", str(self.script_path), json.dumps(payload)],
            cwd=self.repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
        return json.loads(completed.stdout)
