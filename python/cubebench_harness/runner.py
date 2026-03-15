from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from .config import HarnessConfig
from .converters import get_converter
from .cube_bridge import CubeJsBridge
from .logging import RunLogger
from .providers import run_anthropic, run_google, run_openai
from .tooling import ToolExecutor, build_common_tooldefs


def run_harness(config_path: str | Path) -> tuple[object, RunLogger]:
    load_dotenv()

    repo_root = Path(__file__).resolve().parents[2]
    config = HarnessConfig.from_yaml(config_path)
    converter = get_converter(config.representation)
    bridge = CubeJsBridge(repo_root=repo_root, cube=config.cube)
    tooldefs = build_common_tooldefs()
    tool_executor = ToolExecutor(config=config, bridge=bridge, converter=converter)
    logger = RunLogger(repo_root=repo_root, provider=config.provider, model_name=config.model_name)
    logger.write_header(asdict(config))
    logger.log_verbose_event(
        "configured scramble",
        {"scramble_name": config.scramble_name, "scramble": config.scramble},
    )

    representation_contract = converter.prompt_contract()

    if config.provider == "openai":
        result = run_openai(config, tooldefs, tool_executor, logger, representation_contract)
    elif config.provider == "anthropic":
        result = run_anthropic(config, tooldefs, tool_executor, logger, representation_contract)
    elif config.provider == "google":
        result = run_google(config, tooldefs, tool_executor, logger, representation_contract)
    else:
        raise ValueError(f"Unsupported provider: {config.provider}")

    logger.log_verbose_event("final answer", result.final_text)
    task_completion = {"task": config.task, "task_completed": False, "scramble_loaded": False}
    if tool_executor.scramble_loaded:
        task_completion = {
            **tool_executor.execute("check_task_complete", {"task": config.task}),
            "scramble_loaded": True,
        }
    logger.log_verbose_event("task completion", task_completion)
    return result, logger
