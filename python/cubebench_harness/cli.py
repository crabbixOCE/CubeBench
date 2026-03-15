from __future__ import annotations

import argparse

from .runner import run_harness


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CubeBench LLM harness.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file.")
    args = parser.parse_args()

    result, logger = run_harness(args.config)
    print(result.final_text)
    print(f"\nEvents log: {logger.events_path}")
    print(f"Reasoning log: {logger.reasoning_path}")
