import ast
import logging
import math
import operator
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.storage import Store

logger = logging.getLogger(__name__)


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalculatorInput(ToolInput):
    expression: str = Field(min_length=1, max_length=120)


class SearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=1000)


class InspectInput(ToolInput):
    run_id: str = Field(min_length=1, max_length=80)


class EmptyInput(ToolInput):
    pass


class CalculatorOutput(BaseModel):
    expression: str
    result: float


class RetrievedChunkOutput(BaseModel):
    chunk_id: str
    document_id: str
    source_name: str
    metadata: dict[str, Any]
    text: str
    score: float


class SearchOutput(BaseModel):
    results: list[RetrievedChunkOutput]


class RunInspectOutput(BaseModel):
    run_id: str
    status: str
    event_count: int


def calculate(expression: str) -> dict[str, Any]:
    operations: dict[type, Callable[[Any, Any], Any]] = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    }

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("Exponent magnitude exceeds 10")
            result = operations[type(node.op)](left, right)
            if not math.isfinite(result) or abs(result) > 1e100:
                raise ValueError("Calculator result is outside supported bounds")
            return result
        raise ValueError("Expression contains an unsupported operation")

    result = evaluate(ast.parse(expression, mode="eval"))
    return {"expression": expression, "result": result}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[..., dict[str, Any]]
    output_model: type[BaseModel]
    permission: str = "read"
    timeout_seconds: float = 10
    approval_required: bool = False


class ToolRegistry:
    def __init__(self, store: Store, timeout_seconds: float = 10):
        self.store = store
        self.timeout_seconds = timeout_seconds
        self._tools: dict[str, ToolSpec] = {}
        self.register(ToolSpec(
            "calculator", "Evaluate bounded arithmetic", CalculatorInput, calculate,
            CalculatorOutput,
        ))
        self.register(ToolSpec(
            "knowledge_search", "Retrieve matching local document chunks", SearchInput,
            lambda query: self._search(query), SearchOutput,
        ))
        self.register(ToolSpec(
            "document_search", "Search approved ingested documents", SearchInput,
            lambda query: self._search(query), SearchOutput,
        ))
        self.register(ToolSpec(
            "run_inspect", "Inspect an execution run and its event summary", InspectInput,
            self._inspect, RunInspectOutput,
        ))

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def names(self) -> set[str]:
        return set(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {"name": item.name, "description": item.description,
             "input_schema": item.input_model.model_json_schema(),
             "output_schema": item.output_model.model_json_schema(),
             "permission": item.permission, "timeout_seconds": item.timeout_seconds,
             "approval_required": item.approval_required}
            for item in self._tools.values()
        ]

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            raise PermissionError(f"Tool is not registered: {name}")
        tool = self._tools[name]
        try:
            validated = tool.input_model.model_validate(arguments)
        except ValidationError as error:
            raise ValueError(f"Invalid arguments for {name}: {error.errors()}") from error
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(tool.handler, **validated.model_dump())
        try:
            result = future.result(timeout=min(tool.timeout_seconds, self.timeout_seconds))
            return tool.output_model.model_validate(result).model_dump(mode="json")
        except TimeoutError as error:
            future.cancel()
            raise TimeoutError(f"Tool timed out: {name}") from error
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _search(self, query: str) -> dict[str, Any]:
        from app.rag import KnowledgeBase

        return {"results": KnowledgeBase(self.store).search(query, limit=5)}

    def _inspect(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError("Run not found")
        events = self.store.list_events(run_id)
        return {"run_id": run_id, "status": run["status"], "event_count": len(events)}
