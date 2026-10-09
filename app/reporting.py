from typing import Any

from app.llm import MockProvider


def build_report(report: dict[str, Any]) -> dict[str, Any]:
    report["markdown"] = MockProvider().synthesize_report(report)
    return report


def build_cancelled_report(
    run_id: str,
    goal: str,
    plan: dict[str, Any] | None,
    completed_tasks: list[dict[str, Any]],
    tools_invoked: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    duration_seconds: float,
) -> dict[str, Any]:
    return build_report({
        "run_id": run_id,
        "goal": goal,
        "status": "CANCELLED",
        "execution_summary": "Execution was cancelled before all planned tasks completed.",
        "plan": plan,
        "completed_tasks": completed_tasks,
        "failed_tasks": [],
        "tools_invoked": tools_invoked,
        "evidence": evidence,
        "verification": [{
            "check_name": "run_execution",
            "status": "SKIPPED",
            "evidence": ["The run was cancelled by an authorized administrator"],
            "failure_reason": "Remaining tasks were not executed",
        }],
        "errors": [],
        "limitations": ["In-flight synchronous tools cannot be forcibly interrupted."],
        "answer": "Execution was cancelled; findings may be incomplete.",
        "citations": [],
        "duration_seconds": duration_seconds,
    })
