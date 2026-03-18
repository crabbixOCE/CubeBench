from __future__ import annotations

import argparse

from .runner import run_harness


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CubeBench LLM harness.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file.")
    args = parser.parse_args()

    report = run_harness(args.config)
    total_runs = len(report.results)
    successes = sum(1 for result in report.results if result.success)
    print(f"Completed {total_runs} runs with {successes} successes.")
    print(f"Batch directory: {report.batch_dir}")
    print(f"Manifest: {report.manifest_path}")
    print(f"Status: {report.status_path}")
