from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from typing import Any


CanonicalState = dict[str, Any]


@dataclass(frozen=True, slots=True)
class RepresentationContract:
    summary: str
    color_scheme: dict[str, str]
    face_order: tuple[str, ...]
    array_orders: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def prompt_text(self, name: str) -> str:
        lines = [
            f"Representation name: {name}",
            f"Payload: {self.summary}",
            "Face/color mapping: "
            + ", ".join(f"{face}={color}" for face, color in self.color_scheme.items()),
            f"Face order: {', '.join(self.face_order)}",
        ]

        for field_name, entries in self.array_orders.items():
            lines.append(f"{field_name} order: {', '.join(entries)}")

        for note in self.notes:
            lines.append(f"Note: {note}")

        return "\n".join(lines)

    def payload(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "color_scheme": self.color_scheme,
            "face_order": list(self.face_order),
            "array_orders": {
                field_name: list(entries) for field_name, entries in self.array_orders.items()
            },
            "notes": list(self.notes),
        }


class StateConverter(ABC):
    name: str

    @abstractmethod
    def convert(self, canonical_state: CanonicalState) -> Any:
        raise NotImplementedError

    @abstractmethod
    def contract(self) -> RepresentationContract:
        raise NotImplementedError

    def prompt_contract(self) -> str:
        return self.contract().prompt_text(self.name)

    def contract_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            **self.contract().payload(),
        }


@dataclass(slots=True)
class FaceletStringConverter(StateConverter):
    name: str = "facelet_string"

    def convert(self, canonical_state: CanonicalState) -> str:
        return canonical_state["facelet_string"]

    def contract(self) -> RepresentationContract:
        return RepresentationContract(
            summary="A 54-character string of face labels, with 9 stickers per face.",
            color_scheme={
                "U": "white",
                "R": "red",
                "F": "green",
                "D": "yellow",
                "L": "orange",
                "B": "blue",
            },
            face_order=("U", "R", "F", "D", "L", "B"),
            notes=(
                "Characters are face labels, not free-form color initials.",
                "Read the string in chunks of 9 stickers per face using the listed face order.",
                "Solved state: UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB.",
            ),
        )


@dataclass(slots=True)
class CubieJsonConverter(StateConverter):
    name: str = "cubie_json"

    def convert(self, canonical_state: CanonicalState) -> dict[str, Any]:
        return canonical_state["cubie_json"]

    def contract(self) -> RepresentationContract:
        solved_state = {
            "center": [0, 1, 2, 3, 4, 5],
            "cp": [0, 1, 2, 3, 4, 5, 6, 7],
            "co": [0, 0, 0, 0, 0, 0, 0, 0],
            "ep": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
            "eo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        }
        return RepresentationContract(
            summary="A JSON object with integer arrays center[6], cp[8], co[8], ep[12], and eo[12].",
            color_scheme={
                "U": "white",
                "R": "red",
                "F": "green",
                "D": "yellow",
                "L": "orange",
                "B": "blue",
            },
            face_order=("U", "R", "F", "D", "L", "B"),
            array_orders={
                "center": ("U", "R", "F", "D", "L", "B"),
                "cp": ("URF", "UFL", "ULB", "UBR", "DFR", "DLF", "DBL", "DRB"),
                "ep": ("UR", "UF", "UL", "UB", "DR", "DF", "DL", "DB", "FR", "FL", "BL", "BR"),
            },
            notes=(
                "center values identify centers in the listed face order.",
                "Each cp value is the corner cubie id occupying that slot, using the listed cp order as the cubie-id legend.",
                "co stores corner orientation per slot: 0 is solved orientation, 1 and 2 are twists.",
                "Each ep value is the edge cubie id occupying that slot, using the listed ep order as the cubie-id legend.",
                "eo stores edge orientation per slot: 0 is solved orientation, 1 is flipped.",
                f"Solved state: {json.dumps(solved_state, separators=(',', ':'))}.",
            ),
        )


CONVERTERS: dict[str, StateConverter] = {
    "facelet_string": FaceletStringConverter(),
    "cubie_json": CubieJsonConverter(),
}


def get_converter(name: str) -> StateConverter:
    try:
        return CONVERTERS[name]
    except KeyError as exc:
        supported = ", ".join(sorted(CONVERTERS))
        raise ValueError(f"Unsupported representation '{name}'. Choose one of: {supported}.") from exc
