import json
import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import get_settings
from app.llm import provider_from_settings
from app.orchestrator import AgentOrchestrator
from app.rag import KnowledgeBase
from app.reporting import build_cancelled_report
from app.schemas import ApprovalDecision, DocumentIngestRequest, KnowledgeSearchRequest, RunRequest
from app.state_machine import validate_transition
from app.storage import Store
from app.tools import ToolRegistry

router = APIRouter(prefix="/api/v1")


def get_store(request: Request) -> Store:
    from app.main import store_for

    return store_for(request.app)


def get_run(store: Store, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def require_admin(authorization: str | None) -> None:
    expected = get_settings().admin_token
    if not expected or not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=403, detail="Authorized local administrator token required")


@router.post("/runs", status_code=status.HTTP_201_CREATED, tags=["runs"])
def create_run(body: RunRequest, request: Request) -> dict[str, Any]:
    store = get_store(request)
    run = store.create_run(body.goal)
    AgentOrchestrator(store, get_settings(), provider_from_settings(get_settings().llm_provider)).execute(run["id"])
    return _run_response(get_run(store, run["id"]))


@router.get("/runs/{run_id}", tags=["runs"])
def read_run(run_id: str, request: Request) -> dict[str, Any]:
    return _run_response(get_run(get_store(request), run_id))


@router.get("/runs/{run_id}/plan", tags=["runs"])
def read_plan(run_id: str, request: Request) -> dict[str, Any]:
    run = get_run(get_store(request), run_id)
    if not run["plan_json"]:
        raise HTTPException(status_code=404, detail="No plan has been created")
    return json.loads(run["plan_json"])


@router.get("/runs/{run_id}/events", tags=["runs"])
def read_events(run_id: str, request: Request) -> list[dict[str, Any]]:
    store = get_store(request)
    get_run(store, run_id)
    return store.list_events(run_id)


@router.get("/runs/{run_id}/report", tags=["runs"])
def read_report(run_id: str, request: Request) -> dict[str, Any]:
    run = get_run(get_store(request), run_id)
    if not run["report_json"]:
        raise HTTPException(status_code=404, detail="No report is available for this run")
    return json.loads(run["report_json"])


@router.post("/knowledge/documents", status_code=status.HTTP_201_CREATED, tags=["knowledge"])
def ingest_document(body: DocumentIngestRequest, request: Request) -> dict[str, Any]:
    settings = get_settings()
    try:
        return KnowledgeBase(get_store(request)).ingest(
            body.source_name, body.content, settings.max_upload_bytes,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/knowledge/search", tags=["knowledge"])
def search_knowledge(body: KnowledgeSearchRequest, request: Request) -> dict[str, Any]:
    return {"query": body.query, "results": KnowledgeBase(get_store(request)).search(body.query, body.limit)}


@router.get("/tools", tags=["tools"])
def list_tools(request: Request) -> list[dict[str, Any]]:
    return ToolRegistry(get_store(request), get_settings().tool_timeout_seconds).describe()


@router.post("/runs/{run_id}/approve", tags=["runs"])
def approve_action(
    run_id: str, body: ApprovalDecision, request: Request,
    authorization: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    require_admin(authorization)
    store = get_store(request)
    run = get_run(store, run_id)
    if run["status"] != "WAITING_FOR_APPROVAL":
        raise HTTPException(status_code=409, detail="Run has no pending approval")
    request_id = body.request_id
    pending = next((event["payload"] for event in store.list_events(run_id)
                    if event["kind"] == "approval_requested"
                    and event["payload"].get("request_id") == request_id), None)
    if not pending:
        raise HTTPException(status_code=422, detail="request_id does not identify a pending action")
    if body.approved:
        store.add_event(run_id, "approval_granted", {
            "request_id": request_id, "task_id": pending["task_id"],
        })
        AgentOrchestrator(store, get_settings(), provider_from_settings(get_settings().llm_provider)).execute(run_id)
    else:
        store.add_event(run_id, "approval_denied", {
            "request_id": request_id, "task_id": pending["task_id"],
        })
        validate_transition(run["status"], "FAILED")
        store.update_run(run_id, status="FAILED", error="Pending action was denied")
    return _run_response(get_run(store, run_id))


@router.post("/runs/{run_id}/cancel", tags=["runs"])
def cancel_run(
    run_id: str, request: Request,
    authorization: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    require_admin(authorization)
    store = get_store(request)
    run = get_run(store, run_id)
    try:
        validate_transition(run["status"], "CANCELLED")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    store.update_run(run_id, status="CANCELLED")
    store.add_event(run_id, "state_transition", {"from": run["status"], "to": "CANCELLED"})
    plan = json.loads(run["plan_json"]) if run["plan_json"] else None
    store.update_run(run_id, report_json=build_cancelled_report(
        run_id, run["goal"], plan, [], [], [], 0,
    ))
    return _run_response(get_run(store, run_id))


def _run_response(run: dict[str, Any]) -> dict[str, Any]:
    return {key: run[key] for key in ("id", "goal", "status", "created_at", "updated_at", "error")}
