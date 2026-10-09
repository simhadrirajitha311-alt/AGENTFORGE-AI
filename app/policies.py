from app.schemas import ExecutionPlan, RiskLevel


class PolicyError(ValueError):
    pass


def validate_plan(plan: ExecutionPlan, allowed_tools: set[str], max_tasks: int) -> list:
    tasks = plan.tasks
    if len(tasks) > max_tasks:
        raise PolicyError(f"Plan contains {len(tasks)} tasks; maximum is {max_tasks}")
    if plan.estimated_task_count != len(tasks):
        raise PolicyError("estimated_task_count must match the number of tasks")

    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise PolicyError("Task IDs must be unique")
    known_ids = set(task_ids)
    for task in tasks:
        if task.tool_name not in allowed_tools:
            raise PolicyError(f"Unknown or disallowed tool: {task.tool_name}")
        if task.risk_level == RiskLevel.HIGH and not task.approval_required:
            raise PolicyError(f"High-risk task {task.task_id} requires human approval")
        if task.task_id in task.dependencies or not set(task.dependencies) <= known_ids:
            raise PolicyError(f"Invalid dependencies for task {task.task_id}")

    visited: set[str] = set()
    active: set[str] = set()
    by_id = {task.task_id: task for task in tasks}

    def visit(task_id: str) -> None:
        if task_id in active:
            raise PolicyError("Plan contains a dependency cycle")
        if task_id in visited:
            return
        active.add(task_id)
        for dependency in by_id[task_id].dependencies:
            visit(dependency)
        active.remove(task_id)
        visited.add(task_id)

    ordered_ids: list[str] = []

    def order(task_id: str) -> None:
        if task_id in ordered_ids:
            return
        for dependency in by_id[task_id].dependencies:
            order(dependency)
        ordered_ids.append(task_id)

    for task_id in task_ids:
        visit(task_id)
        order(task_id)
    return [by_id[task_id] for task_id in ordered_ids]
