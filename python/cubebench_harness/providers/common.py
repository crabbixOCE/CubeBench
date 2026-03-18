from __future__ import annotations

from ..models import ProviderResult, ProviderRunError
from ..tooling import ToolExecutor

FINAL_SUBMISSION_TOOL_NAME = "make_final_submission"


def maybe_build_submission_result(
    tool_name: str,
    tool_executor: ToolExecutor,
    total_output_tokens: int,
) -> ProviderResult | None:
    if tool_name != FINAL_SUBMISSION_TOOL_NAME:
        return None

    return ProviderResult(
        final_text=tool_executor.final_submission or "",
        total_output_tokens=total_output_tokens,
    )


def raise_missing_submission_error(
    provider_name: str,
    max_turns: int,
    total_output_tokens: int,
) -> None:
    raise ProviderRunError(
        (
            f"{provider_name} run exceeded max_turns={max_turns} "
            "and did not call make_final_submission."
        ),
        total_output_tokens=total_output_tokens,
    )
