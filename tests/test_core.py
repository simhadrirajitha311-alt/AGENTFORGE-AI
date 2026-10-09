
import pytest

from app.config import Settings
from app.orchestrator import AgentOrchestrator
from app.policies import PolicyError, validate_plan
from app.rag import KnowledgeBase, TfidfRanker, chunk_text
from app.schemas import ExecutionPlan, PlanTask, RiskLevel, RunStatus
from app.state_machine import validate_transition
from app.storage import Store
from app.tools import CalculatorOutput, EmptyInput, ToolRegistry, ToolSpec, calculate


def test_policy_rejects_unknown_tool_and_cycles():
    first = PlanTask(task_id="first", description="first", tool_name="calculator",
                     arguments={"expression": "1 + 1"}, expected_output="number",
                     dependencies=["second"])
    second = PlanTask(task_id="second", description="second", tool_name="calculator",
                      arguments={"expression": "2 + 2"}, expected_output="number",
                      dependencies=["first"])
    plan = ExecutionPlan(goal="Calculate something", tasks=[first, second], estimated_task_count=2)
    with pytest.raises(PolicyError, match="cycle"):
        validate_plan(plan, {"calculator"}, 4)
    first.dependencies = []
    first.tool_name = "shell"
    with pytest.raises(PolicyError, match="Unknown"):
        validate_plan(plan, {"calculator"}, 4)


def test_policy_orders_tasks_after_dependencies():
    later = PlanTask(task_id="later", description="later", tool_name="calculator",
                     arguments={"expression": "1 + 1"}, expected_output="number",
                     dependencies=["first"])
    first = PlanTask(task_id="first", description="first", tool_name="calculator",
                     arguments={"expression": "2 + 2"}, expected_output="number")
    plan = ExecutionPlan(goal="Calculate something", tasks=[later, first], estimated_task_count=2)
    assert [task.task_id for task in validate_plan(plan, {"calculator"}, 4)] == ["first", "later"]


def test_policy_requires_approval_for_high_risk_tasks():
    task = PlanTask(task_id="high", description="high impact", tool_name="calculator",
                    arguments={"expression": "1 + 1"}, expected_output="number",
                    risk_level=RiskLevel.HIGH)
    plan = ExecutionPlan(goal="Calculate something", tasks=[task], estimated_task_count=1)
    with pytest.raises(PolicyError, match="requires human approval"):
        validate_plan(plan, {"calculator"}, 4)


def test_state_machine_rejects_terminal_transition():
    with pytest.raises(ValueError, match="Invalid run state"):
        validate_transition(RunStatus.SUCCEEDED, RunStatus.RUNNING)


def test_calculator_and_tool_arguments_are_bounded(tmp_path):
    assert calculate("(12 + 4) * 2")["result"] == 32
    with pytest.raises(ValueError, match="unsupported"):
        calculate("__import__('os').system('id')")
    registry = ToolRegistry(Store(tmp_path / "tools.db"))
    with pytest.raises(PermissionError):
        registry.invoke("shell", {"command": "id"})
    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.invoke("calculator", {"expression": "1 + 1", "extra": True})
    registry.register(ToolSpec(
        "bad_output", "test schema", EmptyInput, lambda: {"result": "not a number"},
        CalculatorOutput,
    ))
    with pytest.raises(ValueError, match="result"):
        registry.invoke("bad_output", {})


def test_rag_ingestion_retrieval_and_path_rejection(tmp_path):
    store = Store(tmp_path / "rag.db")
    knowledge = KnowledgeBase(store)
    text = "AgentForge requires approval before high impact actions. " * 15
    result = knowledge.ingest("policy.md", text)
    matches = knowledge.search("approval for high impact actions")
    assert result["status"] == "ingested"
    assert matches and matches[0]["source_name"] == "policy.md"
    assert matches[0]["document_id"] == result["document_id"]
    assert knowledge.ingest("policy.md", text)["status"] == "duplicate"
    with pytest.raises(ValueError, match="filenames"):
        knowledge.ingest("../policy.md", text)
    with pytest.raises(ValueError, match="byte limit"):
        knowledge.ingest("large.txt", "x" * 20, max_bytes=10)
    assert len(chunk_text("word " * 200)) > 1
    assert TfidfRanker().rank("unused query", []) == []


def test_run_persists_results_and_grounded_report(tmp_path):
    database = tmp_path / "persistent.db"
    store = Store(database)
    KnowledgeBase(store).ingest("guide.txt", "The test system requires approval for payments.")
    run = store.create_run("According to the document, explain payment approval")
    AgentOrchestrator(store, Settings(database_path=database)).execute(run["id"])
    reopened = Store(database)
    record = reopened.get_run(run["id"])
    import json

    report = json.loads(record["report_json"])
    assert record["status"] == "SUCCEEDED"
    assert report["evidence"][0]["source_name"] == "guide.txt"
    assert report["citations"] == [report["evidence"][0]["chunk_id"]]
    assert all(event["kind"] != "tool_result" or "text" not in event["payload"]
               for event in reopened.list_events(run["id"]))