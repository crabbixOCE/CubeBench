from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

from .config import HarnessBatchConfig, HarnessConfig, PlannedRun
from .converters import get_converter
from .cube_bridge import CubeJsBridge
from .logging import BatchLogger, RunLogger, RunStatusRecord
from .models import ProviderRunError
from .providers import run_anthropic, run_google, run_openai
from .tooling import ToolExecutor, build_common_tooldefs


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    batch_dir: Path
    manifest_path: Path
    status_path: Path
    results: list[RunStatusRecord]


@dataclass(frozen=True, slots=True)
class SubmissionVerification:
    raw_submission: str
    extracted_solution: str
    task_completion: dict[str, object]


def _generate_scrambles(
    batch_config: HarnessBatchConfig,
    bridge: CubeJsBridge,
) -> dict[str, list[str]]:
    if batch_config.scramble is not None and batch_config.scramble_name is not None:
        return batch_config.generated_scrambles()

    scrambles_by_task: dict[str, list[str]] = {}
    for task in batch_config.tasks:
        scrambles_by_task[task] = [
            bridge.generate_scramble() for _ in range(batch_config.n_runs_per_task)
        ]

    return scrambles_by_task


def _run_single_harness(
    repo_root: Path,
    config: HarnessConfig,
    logger: RunLogger,
) -> tuple[object, SubmissionVerification]:
    converter = get_converter(config.representation)
    bridge = CubeJsBridge(repo_root=repo_root, cube=config.cube)
    tooldefs = build_common_tooldefs()
    tool_executor = ToolExecutor(config=config, bridge=bridge, converter=converter)
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
    current_state_completion = {
        "task": config.task,
        "task_completed": False,
        "scramble_loaded": False,
    }
    if tool_executor.scramble_loaded:
        current_state_completion = {
            **tool_executor.execute("check_task_complete", {"task": config.task}),
            "scramble_loaded": True,
        }

    logger.log_verbose_event("live state completion", current_state_completion)
    submission_verification = _verify_submitted_solution(
        repo_root,
        config,
        tool_executor.final_submission,
    )
    logger.log_verbose_event("submitted solution verification", asdict(submission_verification))
    logger.log_verbose_event(
        "usage summary",
        {"total_output_tokens_used": result.total_output_tokens},
    )
    return result, submission_verification


def _verify_submitted_solution(
    repo_root: Path,
    config: HarnessConfig,
    submitted_solution: str | None,
) -> SubmissionVerification:
    raw_submission = (submitted_solution or "").strip()
    failure = {
        "task": config.task,
        "task_completed": False,
        "scramble_loaded": False,
    }
    if not raw_submission:
        return SubmissionVerification(
            raw_submission="",
            extracted_solution="",
            task_completion=failure,
        )

    bridge = CubeJsBridge(repo_root=repo_root, cube=config.cube)
    try:
        bridge.load_scramble(config.scramble)
        bridge.apply_moves(raw_submission)
        task_completion = {
            **asdict(bridge.check_task_complete(config.task)),
            "scramble_loaded": True,
        }
    except Exception:
        return SubmissionVerification(
            raw_submission=raw_submission,
            extracted_solution="",
            task_completion=failure,
        )

    return SubmissionVerification(
        raw_submission=raw_submission,
        extracted_solution=raw_submission,
        task_completion=task_completion,
    )


def _build_manifest_payload(
    batch_config: HarnessBatchConfig,
    planned_runs: list[PlannedRun],
    scrambles_by_task: dict[str, list[str]],
    config_path: str | Path,
) -> dict[str, object]:
    return {
        "config_path": str(Path(config_path).resolve()),
        "batch_config": asdict(batch_config),
        "generated_scrambles": scrambles_by_task,
        "planned_runs": [asdict(planned_run) for planned_run in planned_runs],
    }


def run_harness(config_path: str | Path) -> BenchmarkReport:
    load_dotenv()

    repo_root = Path(__file__).resolve().parents[2]
    batch_config = HarnessBatchConfig.from_yaml(config_path)
    scramble_bridge = CubeJsBridge(repo_root=repo_root, cube=batch_config.cube)
    scrambles_by_task = _generate_scrambles(batch_config, scramble_bridge)
    planned_runs = batch_config.expand_runs(scrambles_by_task)

    batch_logger = BatchLogger(repo_root=repo_root, batch_label=Path(config_path).stem)
    batch_logger.write_manifest(
        _build_manifest_payload(batch_config, planned_runs, scrambles_by_task, config_path)
    )

    for planned_run in planned_runs:
        run_config = batch_config.build_run_config(planned_run)
        logger = batch_logger.create_run_logger(planned_run.run_id)

        try:
            result, submission_verification = _run_single_harness(repo_root, run_config, logger)
            status_record = RunStatusRecord(
                run_id=planned_run.run_id,
                task_name=planned_run.task,
                task_run_index=planned_run.task_run_index,
                scramble_name=planned_run.scramble_name,
                scramble=planned_run.scramble,
                solution=submission_verification.extracted_solution,
                model=planned_run.model.raw_name,
                provider=planned_run.model.provider,
                success=bool(submission_verification.task_completion.get("task_completed")),
                total_output_tokens_used=result.total_output_tokens,
                events_path=str(logger.events_path),
                reasoning_path=str(logger.reasoning_path),
            )
        except ProviderRunError as exc:
            logger.log_verbose_event(
                "run error",
                {"type": type(exc).__name__, "message": str(exc)},
            )
            status_record = RunStatusRecord(
                run_id=planned_run.run_id,
                task_name=planned_run.task,
                task_run_index=planned_run.task_run_index,
                scramble_name=planned_run.scramble_name,
                scramble=planned_run.scramble,
                solution="",
                model=planned_run.model.raw_name,
                provider=planned_run.model.provider,
                success=False,
                total_output_tokens_used=exc.total_output_tokens,
                events_path=str(logger.events_path),
                reasoning_path=str(logger.reasoning_path),
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception as exc:
            logger.log_verbose_event(
                "run error",
                {"type": type(exc).__name__, "message": str(exc)},
            )
            status_record = RunStatusRecord(
                run_id=planned_run.run_id,
                task_name=planned_run.task,
                task_run_index=planned_run.task_run_index,
                scramble_name=planned_run.scramble_name,
                scramble=planned_run.scramble,
                solution="",
                model=planned_run.model.raw_name,
                provider=planned_run.model.provider,
                success=False,
                total_output_tokens_used=None,
                events_path=str(logger.events_path),
                reasoning_path=str(logger.reasoning_path),
                error=f"{type(exc).__name__}: {exc}",
            )

        batch_logger.append_status(status_record)

    return BenchmarkReport(
        batch_dir=batch_logger.batch_dir,
        manifest_path=batch_logger.manifest_path,
        status_path=batch_logger.status_path,
        results=batch_logger.status_records,
    )
