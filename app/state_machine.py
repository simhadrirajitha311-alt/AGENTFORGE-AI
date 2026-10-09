from app.schemas import RunStatus

TRANSITIONS = {
    RunStatus.PENDING: {RunStatus.PLANNING, RunStatus.CANCELLED},
    RunStatus.PLANNING: {RunStatus.PLANNED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.PLANNED: {
        RunStatus.RUNNING, RunStatus.WAITING_FOR_APPROVAL, RunStatus.FAILED, RunStatus.CANCELLED,
    },
    RunStatus.RUNNING: {
        RunStatus.WAITING_FOR_APPROVAL, RunStatus.VERIFYING, RunStatus.SUCCEEDED,
        RunStatus.FAILED, RunStatus.CANCELLED,
    },
    RunStatus.WAITING_FOR_APPROVAL: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.VERIFYING: {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


def validate_transition(current: RunStatus | str, following: RunStatus | str) -> None:
    current_status, next_status = RunStatus(current), RunStatus(following)
    if next_status not in TRANSITIONS[current_status]:
        raise ValueError(f"Invalid run state transition: {current_status} -> {next_status}")
