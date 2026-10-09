import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._memory_connection: sqlite3.Connection | None = None
        if str(database_path) != ":memory:":
            database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if str(self.database_path) == ":memory:":
            if self._memory_connection is None:
                self._memory_connection = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_connection.row_factory = sqlite3.Row
                self._memory_connection.execute("PRAGMA foreign_keys = ON")
            connection = self._memory_connection
        else:
            connection = sqlite3.connect(str(self.database_path), timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if connection is not self._memory_connection:
                connection.close()

    def close(self) -> None:
        if self._memory_connection is not None:
            self._memory_connection.close()
            self._memory_connection = None

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    plan_json TEXT, report_json TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    kind TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, source_name TEXT NOT NULL, content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    UNIQUE(source_name, content_hash)
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    ordinal INTEGER NOT NULL, text TEXT NOT NULL,
                    UNIQUE(document_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS task_results (
                    run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT NOT NULL,
                    result_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, task_id)
                );
                """
            )

    def create_run(self, goal: str) -> dict[str, Any]:
        run_id = str(uuid4())
        now = timestamp()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO runs (id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, goal, "PENDING", now, now),
            )
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def update_run(self, run_id: str, **fields: Any) -> None:
        values = {**fields, "updated_at": timestamp()}
        for key in ("plan_json", "report_json"):
            if key in values and not isinstance(values[key], str):
                values[key] = json.dumps(values[key], ensure_ascii=True)
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE runs SET {assignments} WHERE id = ?", (*values.values(), run_id)
            )

    def add_event(self, run_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "id": str(uuid4()), "run_id": run_id, "kind": kind,
            "created_at": timestamp(), "payload": payload,
        }
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO events (id, run_id, kind, created_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                (event["id"], run_id, kind, event["created_at"], json.dumps(payload)),
            )
        return event

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY created_at, rowid", (run_id,)
            ).fetchall()
        return [
            {"id": row["id"], "run_id": row["run_id"], "kind": row["kind"],
             "created_at": row["created_at"], "payload": json.loads(row["payload_json"])}
            for row in rows
        ]

    def add_document(
        self, document_id: str, source_name: str, content_hash: str, metadata: dict[str, Any],
        chunks: list[tuple[str, int, str]],
    ) -> bool:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM documents WHERE source_name = ? AND content_hash = ?",
                (source_name, content_hash),
            ).fetchone()
            if existing:
                return False
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
                (document_id, source_name, content_hash, timestamp(), json.dumps(metadata)),
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                [(chunk_id, document_id, ordinal, text) for chunk_id, ordinal, text in chunks],
            )
        return True

    def list_chunks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT c.id AS chunk_id, c.text, d.id AS document_id, d.source_name, "
                "d.metadata_json FROM chunks c JOIN documents d ON d.id = c.document_id "
                "ORDER BY d.created_at, c.ordinal"
            ).fetchall()
        return [
            {"chunk_id": row["chunk_id"], "document_id": row["document_id"],
             "source_name": row["source_name"], "metadata": json.loads(row["metadata_json"]),
             "text": row["text"]}
            for row in rows
        ]

    def save_task_result(self, run_id: str, task_id: str, result: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO task_results VALUES (?, ?, ?, ?)",
                (run_id, task_id, json.dumps(result), timestamp()),
            )

    def get_task_results(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT task_id, result_json FROM task_results WHERE run_id = ?", (run_id,)
            ).fetchall()
        return {row["task_id"]: json.loads(row["result_json"]) for row in rows}
