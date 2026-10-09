import re
from uuid import uuid4

from app.schemas import ExecutionPlan, PlanTask

ARITHMETIC = re.compile(r"(?<![\w.])(?:\d+(?:\.\d+)?\s*[+*/-]\s*)+\d+(?:\.\d+)?(?![\w.])")


class DeterministicPlanner:
    def generate(self, goal: str) -> ExecutionPlan:
        tasks: list[PlanTask] = []
        mentions_knowledge = any(
            word in goal.lower() for word in ("document", "knowledge", "source", "according", "research")
        )
        if mentions_knowledge:
            tasks.append(PlanTask(
                task_id=str(uuid4()),
                description="Retrieve relevant evidence from the local knowledge base",
                tool_name="knowledge_search",
                arguments={"query": goal},
                expected_output="Relevant document chunks, or an explicit statement that none were found",
                verification_criteria=["All sources reference stored document chunks"],
            ))
        expression = ARITHMETIC.search(goal)
        if expression:
            dependencies = [tasks[-1].task_id] if tasks else []
            tasks.append(PlanTask(
                task_id=str(uuid4()),
                description="Evaluate the requested arithmetic expression",
                tool_name="calculator",
                arguments={"expression": expression.group(0)},
                dependencies=dependencies,
                expected_output="A numeric result",
                verification_criteria=["Result is finite and returned by the calculator tool"],
            ))
        if not tasks:
            tasks.append(PlanTask(
                task_id=str(uuid4()),
                description="Search the local knowledge base for evidence related to the goal",
                tool_name="knowledge_search",
                arguments={"query": goal},
                expected_output="Relevant evidence, or an explicit evidence limitation",
                verification_criteria=["Citations reference retrieved chunks"],
            ))
        return ExecutionPlan(goal=goal, tasks=tasks, estimated_task_count=len(tasks))
