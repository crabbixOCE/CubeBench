from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging import RunStatusRecord


@dataclass(frozen=True, slots=True)
class PlotPoint:
    run_id: str
    task_name: str
    scramble_name: str
    model: str
    provider: str
    move_count: int
    reasoning_effort: int


def count_moves(solution: str) -> int:
    return len(solution.split())


def _resolve_status_path(run_path: str | Path) -> Path:
    candidate = Path(run_path)
    if candidate.is_dir():
        return candidate / "status.json"
    return candidate


def load_status_records(run_path: str | Path) -> list[RunStatusRecord]:
    status_path = _resolve_status_path(run_path)
    payload = json.loads(status_path.read_text())
    return [RunStatusRecord(**item) for item in payload]


def build_plot_points(records: list[RunStatusRecord]) -> list[PlotPoint]:
    points: list[PlotPoint] = []
    for record in records:
        if not record.success or record.total_output_tokens_used is None:
            continue

        points.append(
            PlotPoint(
                run_id=record.run_id,
                task_name=record.task_name,
                scramble_name=record.scramble_name,
                model=record.model,
                provider=record.provider,
                move_count=count_moves(record.solution),
                reasoning_effort=record.total_output_tokens_used,
            )
        )

    return points


def save_reasoning_effort_plot(
    points: list[PlotPoint],
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    if not points:
        raise ValueError("No successful runs with token usage were found to plot.")

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    models = sorted({point.model for point in points})
    cmap = plt.get_cmap("tab10")

    for index, model in enumerate(models):
        model_points = [point for point in points if point.model == model]
        ax.scatter(
            [point.reasoning_effort for point in model_points],
            [point.move_count for point in model_points],
            label=model,
            s=70,
            alpha=0.85,
            color=cmap(index % cmap.N),
            edgecolors="black",
            linewidths=0.4,
        )

    ax.set_title(title or "Reasoning effort vs move count")
    ax.set_xlabel("Reasoning effort (total output tokens)")
    ax.set_ylabel("Move count (lower is better)")
    ax.grid(True, alpha=0.3)
    ax.legend(title="Model")

    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return output


def summarize_points(points: list[PlotPoint]) -> dict[str, Any]:
    return {
        "plotted_runs": len(points),
        "models": sorted({point.model for point in points}),
        "tasks": sorted({point.task_name for point in points}),
    }


def default_title_for_points(points: list[PlotPoint], fallback: str) -> str:
    tasks = sorted({point.task_name for point in points})
    if len(tasks) == 1:
        return tasks[0]
    return fallback


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Plot reasoning effort against move count for successful CubeBench runs "
            "using status.json output."
        )
    )
    parser.add_argument(
        "run_path",
        help="Path to a run directory containing status.json, or a status.json file.",
    )
    parser.add_argument(
        "--output",
        help="Output image path. Defaults to <run_dir>/reasoning_effort_vs_move_count.png.",
    )
    parser.add_argument(
        "--title",
        help="Optional custom plot title.",
    )
    args = parser.parse_args()

    status_path = _resolve_status_path(args.run_path)
    run_dir = status_path.parent
    output_path = Path(args.output) if args.output else run_dir / "reasoning_effort_vs_move_count.png"

    records = load_status_records(status_path)
    points = build_plot_points(records)
    plot_title = args.title or default_title_for_points(points, run_dir.name)
    saved_path = save_reasoning_effort_plot(points, output_path, title=plot_title)
    summary = summarize_points(points)

    print(f"Read {len(records)} status records from {status_path}")
    print(f"Plotted {summary['plotted_runs']} successful runs across models: {', '.join(summary['models'])}")
    print(f"Tasks included: {', '.join(summary['tasks'])}")
    print(f"Wrote plot to {saved_path}")
