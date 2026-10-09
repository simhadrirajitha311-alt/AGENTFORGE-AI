import logging
import re
import time
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.llm import LLMProvider, MockProvider
from app.policies import PolicyError, validate_plan
from app.reporting import build_cancelled_report, build_report
from app.schemas import ExecutionPlan, RunStatus
from app.state_machine import validate_transition
from app.storage import Store
from app.tools import ToolRegistry
from app.verification import verify_execution

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(self, store: Store, settings: Settings, provider: LLMProvider | None = None):
        self.store = store
        self.settings = settings
        self.provider = provider or MockProvider()
        self.tools = ToolRegistry(store, settings.tool_timeout_seconds)

    def execute(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError("Run not found")
        started = time.monotonic()
        task_results = self.store.get_task_results(run_id)
        failed_tasks: list[dict[str, Any]] = []
        try:
            if run["status"] == RunStatus.PENDING:
                self._transition(run_id, RunStatus.PLANNING)
                plan = self.provider.generate_plan(run["goal"])
                ordered_tasks = validate_plan(plan, self.tools.names(), self.settings.max_tasks)
                self.store.update_run(run_id, plan_json=plan.model_dump(mode="json"))
                self.store.add_event(run_id, "plan_created", {"plan_id": plan.plan_id,
                                     "task_count": len(plan.tasks)})
                self._transition(run_id, RunStatus.PLANNED)
            else:
                if not run.get("plan_json"):
                    raise PolicyError("Run has no validated plan")
                plan = ExecutionPlan.model_validate_json(run["plan_json"])
                ordered_tasks = validate_plan(plan, self.tools.names(), self.settings.max_tasks)

            run = self.store.get_run(run_id)
            if run and run["status"] in {RunStatus.WAITING_FOR_APPROVAL, RunStatus.PLANNED}:
                self._transition(run_id, RunStatus.RUNNING)

            approved_task_ids = {
                event["payload"].get("task_id") for event in self.store.list_events(run_id)
                if event["kind"] == "approval_granted"
            }
            call_count = sum(event["kind"] == "tool_call" for event in self.store.list_events(run_id))
            for task in ordered_tasks:
                current = self.store.get_run(run_id)
                if current and current["status"] == RunStatus.CANCELLED:
                    return self._finish_cancelled(run_id, run["goal"], plan, task_results, started)
                if time.monotonic() - started > self.settings.run_timeout_seconds:
                    raise TimeoutError("Per-run execution time limit exceeded")
                if task.task_id in task_results:
                    continue
                if not set(task.dependencies) <= set(task_results):
                    raise PolicyError(f"Dependencies are incomplete for task {task.task_id}")
                tool = self.tools._tools[task.tool_name]
                if (task.approval_required or tool.approval_required) and task.task_id not in approved_task_ids:
                    request_id = next((
                        event["payload"]["request_id"] for event in reversed(self.store.list_events(run_id))
                        if event["kind"] == "approval_requested"
                        and event["payload"].get("task_id") == task.task_id
                    ), str(uuid4()))
                    if not any(event["kind"] == "approval_requested"
                               and event["payload"].get("request_id") == request_id
                               for event in self.store.list_events(run_id)):
                        self.store.add_event(run_id, "approval_requested", {
                            "request_id": request_id, "task_id": task.task_id,
                            "tool_name": task.tool_name,
                        })
                    self._transition(run_id, RunStatus.WAITING_FOR_APPROVAL,
                                     {"request_id": request_id, "task_id": task.task_id})
                    return self.store.get_run(run_id)  # type: ignore[return-value]
                if call_count >= self.settings.max_tool_calls:
                    raise PolicyError("Per-run tool-call limit exceeded")
                call_count += 1
                safe_arguments = _safe_arguments(task.arguments)
                self.store.add_event(run_id, "tool_call", {
                    "task_id": task.task_id, "tool_name": task.tool_name,
                    "arguments": safe_arguments,
                })
                try:
                    result = self.tools.invoke(task.tool_name, task.arguments)
                except Exception as error:
                    failure = {"task_id": task.task_id, "tool_name": task.tool_name,
                               "error": _redact(str(error))[:300]}
                    failed_tasks.append(failure)
                    self.store.add_event(run_id, "tool_result", {**failure, "success": False})
                    raise
                task_results[task.task_id] = result
                self.store.save_task_result(run_id, task.task_id, result)
                self.store.add_event(run_id, "tool_result", {
                    "task_id": task.task_id, "tool_name": task.tool_name, "success": True,
                    "summary": _result_summary(result),
                })

            current = self.store.get_run(run_id)
            if current and current["status"] == RunStatus.CANCELLED:
                return self._finish_cancelled(run_id, run["goal"], plan, task_results, started)
            self._transition(run_id, RunStatus.VERIFYING)
            evidence = self._gather_evidence(task_results)
            answer = self.provider.grounded_answer(run["goal"], evidence)
            calculations = [
                f"{result['expression']} = {result['result']}"
                for result in task_results.values() if "expression" in result and "result" in result
            ]
            if calculations and not evidence:
                answer = {"answer": "; ".join(calculations), "citations": [],
                          "limitations": ["Arithmetic was evaluated by the registered calculator tool."]}
            checks = verify_execution(plan, task_results, evidence, answer, failed_tasks)
            if any(check["status"] != "PASS" for check in checks):
                answer["limitations"] = list(answer.get("limitations", [])) + [
                    "One or more independent verification checks failed."
                ]
            success = not any(check["status"] != "PASS" for check in checks)
            status = RunStatus.SUCCEEDED if success else RunStatus.FAILED
            report = build_report({
                "run_id": run_id, "goal": run["goal"], "status": status.value,
                "execution_summary": f"Completed {len(task_results)} of {len(plan.tasks)} planned tasks.",
                "plan": plan.model_dump(mode="json"), "completed_tasks": [
                    {"task_id": task.task_id, "description": task.description,
                     "tool_name": task.tool_name, "result": task_results.get(task.task_id)}
                    for task in ordered_tasks if task.task_id in task_results
                ],
                "failed_tasks": failed_tasks, "tools_invoked": [
                    event["payload"] for event in self.store.list_events(run_id)
                    if event["kind"] == "tool_call"
                ],
                "evidence": evidence, "verification": checks,
                "errors": [item["error"] for item in failed_tasks],
                "limitations": answer.get("limitations", []), "answer": answer["answer"],
                "citations": answer.get("citations", []),
                "duration_seconds": round(time.monotonic() - started, 4),
            })
            self._transition(run_id, status, {"verification_passed": success})
            self.store.update_run(run_id, report_json=report)
            self.store.add_event(run_id, "report_created", {
                "status": status.value, "verification_checks": len(checks),
            })
            return self.store.get_run(run_id)  # type: ignore[return-value]
        except Exception as error:  # noqa: BLE001
            current = self.store.get_run(run_id)
            safe_error = _redact(str(error))[:500]
            if current and RunStatus(current["status"]) not in {
                RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.SUCCEEDED,
            }:
                self.store.add_event(run_id, "run_error", {"error": safe_error})
                self._transition(run_id, RunStatus.FAILED, {"error": safe_error})
                stored_plan = (
                    ExecutionPlan.model_validate_json(current["plan_json"])
                    if current.get("plan_json") else None
                )
                evidence = self._gather_evidence(task_results)
                failure_report = build_report({
                    "run_id": run_id, "goal": run["goal"], "status": RunStatus.FAILED.value,
                    "execution_summary": "Execution stopped before all verification checks passed.",
                    "plan": stored_plan.model_dump(mode="json") if stored_plan else None,
                    "completed_tasks": [
                        {"task_id": task_id, "result": result}
                        for task_id, result in task_results.items()
                    ],
                    "failed_tasks": failed_tasks,
                    "tools_invoked": [
                        event["payload"] for event in self.store.list_events(run_id)
                        if event["kind"] == "tool_call"
                    ],
                    "evidence": evidence,
                    "verification": [{
                        "check_name": "run_execution", "status": "FAIL",
                        "evidence": ["Execution stopped and was recorded in the event history"],
                        "failure_reason": safe_error,
                    }],
                    "errors": [safe_error],
                    "limitations": ["The run did not complete successfully; findings may be incomplete."],
                    "answer": f"Execution stopped safely: {safe_error}",
                    "citations": [],
                    "duration_seconds": round(time.monotonic() - started, 4),
                })
                self.store.update_run(run_id, error=safe_error, report_json=failure_report)
            logger.error("Run execution failed", extra={"run_id": run_id})
            return self.store.get_run(run_id)  # type: ignore[return-value]

    def _transition(self, run_id: str, following: RunStatus, payload: dict[str, Any] | None = None) -> None:
        current = self.store.get_run(run_id)
        if current is None:
            raise KeyError("Run not found")
        validate_transition(current["status"], following)
        self.store.update_run(run_id, status=following.value)
        self.store.add_event(run_id, "state_transition", {
            "from": current["status"], "to": following.value, **(payload or {}),
        })

    def _finish_cancelled(
        self, run_id: str, goal: str, plan: ExecutionPlan, results: dict[str, dict[str, Any]],
        started: float,
    ) -> dict[str, Any]:
        completed = [
            {"task_id": task.task_id, "description": task.description,
             "tool_name": task.tool_name, "result": results[task.task_id]}
            for task in plan.tasks if task.task_id in results
        ]
        report = build_cancelled_report(
            run_id, goal, plan.model_dump(mode="json"), completed,
            [event["payload"] for event in self.store.list_events(run_id)
             if event["kind"] == "tool_call"],
            self._gather_evidence(results), round(time.monotonic() - started, 4),
        )
        self.store.update_run(run_id, report_json=report)
        self.store.add_event(run_id, "report_created", {"status": "CANCELLED"})
        return self.store.get_run(run_id)  # type: ignore[return-value]

    @staticmethod
    def _gather_evidence(results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [chunk for result in results.values() for chunk in result.get("results", [])]


def _redact(value: str) -> str:
    return re.sub(r"(?i)(api[_-]?key|token|password|secret)(\s*[:=]\s*)\S+",
                  r"\1\2[REDACTED]", value)


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key, value in arguments.items():
        if any(secret in key.lower() for secret in ("token", "password", "secret", "key")):
            safe[key] = "[REDACTED]"
        elif isinstance(value, str):
            safe[key] = _redact(value)[:200]
        else:
            safe[key] = value
    return safe


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    if "results" in result:
        return {"retrieved_count": len(result["results"]),
                "chunk_ids": [item["chunk_id"] for item in result["results"]]}
    return result