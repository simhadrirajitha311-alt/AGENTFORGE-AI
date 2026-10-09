from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RiskLevel(StrEnum):
    LOW = "low"
    HIGH = "high"


class RunRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)


class PlanTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    description: str = Field(min_length=1, max_length=500)
    tool_name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    expected_output: str = Field(min_length=1, max_length=500)
    risk_level: RiskLevel = RiskLevel.LOW
    verification_criteria: list[str] = Field(default_factory=list)
    approval_required: bool = False


class ExecutionPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    goal: str = Field(min_length=3, max_length=2000)
    tasks: list[PlanTask] = Field(min_length=1, max_length=32)
    estimated_task_count: int = Field(ge=1, le=32)


class VerificationResult(BaseModel):
    check_name: str
    status: str
    evidence: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RunResponse(BaseModel):
    run_id: str
    goal: str
    status: RunStatus
    created_at: str
    updated_at: str
    error: str | None = None


class DocumentIngestRequest(BaseModel):
    source_name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


class ApprovalDecision(BaseModel):
    request_id: str = Field(min_length=1, max_length=80)
    approved: bool
