from datetime import UTC, datetime
from typing import Any

from app.schemas import ExecutionPlan, VerificationResult


def verify_execution(
    plan: ExecutionPlan,
    results: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
    answer: dict[str, Any],
    failed_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    checks = [
        VerificationResult(
            check_name="plan_tasks_completed",
            status="PASS" if all(task.task_id in results for task in plan.tasks) else "FAIL",
            evidence=[f"{len(results)} of {len(plan.tasks)} task results persisted"],
            failure_reason=None if all(task.task_id in results for task in plan.tasks)
            else "One or more planned tasks have no result",
            timestamp=now,
        ),
        VerificationResult(
            check_name="dependencies_satisfied",
            status="PASS" if all(
                dependency in results for task in plan.tasks for dependency in task.dependencies
            ) else "FAIL",
            evidence=["Every dependency has a persisted task result"],
            failure_reason=None if all(
                dependency in results for task in plan.tasks for dependency in task.dependencies
            ) else "A dependency result is missing",
            timestamp=now,
        ),
        VerificationResult(
            check_name="tool_execution",
            status="FAIL" if failed_tasks else "PASS",
            evidence=[f"{len(failed_tasks)} failed task(s)"],
            failure_reason="At least one tool call failed" if failed_tasks else None,
            timestamp=now,
        ),
    ]
    evidence_ids = {item["chunk_id"] for item in evidence}
    cited_ids = set(answer.get("citations", []))
    invalid_ids = cited_ids - evidence_ids
    checks.append(VerificationResult(
        check_name="citation_references",
        status="FAIL" if invalid_ids else "PASS",
        evidence=[f"{len(cited_ids & evidence_ids)} citation(s) match retrieved chunks"],
        failure_reason=f"Unknown citation IDs: {sorted(invalid_ids)}" if invalid_ids else None,
        timestamp=now,
    ))
    return [check.model_dump(mode="json") for check in checks]
