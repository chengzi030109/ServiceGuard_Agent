import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings

SCHEMA_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, "initial_core_tables"),
    (2, "report_and_batch_actor_scope"),
    (3, "human_review_workflow"),
    (4, "audit_hash_chain"),
    (5, "batch_job_lifecycle"),
    (6, "backup_and_privacy_governance_metadata"),
    (7, "operational_metrics_and_schema_ledger"),
    (8, "knowledge_document_security_review"),
    (9, "batch_job_idempotency_records"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Small SQLite repository used for project metadata and logs."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.settings = get_settings()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=max(self.settings.sqlite_busy_timeout_ms / 1000, 0.001),
        )
        conn.row_factory = sqlite3.Row
        self._configure_connection(conn)
        return conn

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA busy_timeout = {self.settings.sqlite_busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA journal_mode = {self.settings.sqlite_journal_mode.upper()}")
        conn.execute(f"PRAGMA synchronous = {self.settings.sqlite_synchronous.upper()}")

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    path TEXT NOT NULL,
                    security_review_status TEXT NOT NULL DEFAULT 'approved',
                    prompt_injection_risks_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    page INTEGER,
                    token_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL DEFAULT 'unknown',
                    actor_hash TEXT NOT NULL DEFAULT 'unknown',
                    review_status TEXT NOT NULL DEFAULT 'not_required',
                    review_comment TEXT,
                    reviewed_by_hash TEXT,
                    reviewed_at TEXT,
                    raw_text TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_call_logs (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_calls TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    actor_hash TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    client_host TEXT,
                    previous_hash TEXT NOT NULL DEFAULT '',
                    event_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    actor_role TEXT NOT NULL DEFAULT 'unknown',
                    actor_hash TEXT NOT NULL DEFAULT 'unknown',
                    total INTEGER NOT NULL DEFAULT 0,
                    succeeded INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idempotency_records (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    actor_hash TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, actor_hash, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_idempotency_records_resource_id
                    ON idempotency_records(resource_id);
                """
            )
            self._ensure_column(
                conn,
                "batch_jobs",
                "actor_role",
                "ALTER TABLE batch_jobs ADD COLUMN actor_role TEXT NOT NULL DEFAULT 'unknown'",
            )
            self._ensure_column(
                conn,
                "batch_jobs",
                "actor_hash",
                "ALTER TABLE batch_jobs ADD COLUMN actor_hash TEXT NOT NULL DEFAULT 'unknown'",
            )
            self._ensure_column(
                conn,
                "reports",
                "actor_role",
                "ALTER TABLE reports ADD COLUMN actor_role TEXT NOT NULL DEFAULT 'unknown'",
            )
            self._ensure_column(
                conn,
                "reports",
                "actor_hash",
                "ALTER TABLE reports ADD COLUMN actor_hash TEXT NOT NULL DEFAULT 'unknown'",
            )
            self._ensure_column(
                conn,
                "reports",
                "review_status",
                "ALTER TABLE reports ADD COLUMN review_status TEXT NOT NULL DEFAULT 'not_required'",
            )
            self._ensure_column(
                conn,
                "reports",
                "review_comment",
                "ALTER TABLE reports ADD COLUMN review_comment TEXT",
            )
            self._ensure_column(
                conn,
                "reports",
                "reviewed_by_hash",
                "ALTER TABLE reports ADD COLUMN reviewed_by_hash TEXT",
            )
            self._ensure_column(
                conn,
                "reports",
                "reviewed_at",
                "ALTER TABLE reports ADD COLUMN reviewed_at TEXT",
            )
            self._ensure_column(
                conn,
                "audit_events",
                "previous_hash",
                "ALTER TABLE audit_events ADD COLUMN previous_hash TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "audit_events",
                "event_hash",
                "ALTER TABLE audit_events ADD COLUMN event_hash TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "documents",
                "security_review_status",
                "ALTER TABLE documents ADD COLUMN "
                "security_review_status TEXT NOT NULL DEFAULT 'approved'",
            )
            self._ensure_column(
                conn,
                "documents",
                "prompt_injection_risks_json",
                "ALTER TABLE documents ADD COLUMN "
                "prompt_injection_risks_json TEXT NOT NULL DEFAULT '{}'",
            )
            self._record_schema_migrations(conn)

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        alter_statement: str,
    ) -> None:
        columns = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(alter_statement)

    def _record_schema_migrations(self, conn: sqlite3.Connection) -> None:
        conn.executemany(
            """
            INSERT OR IGNORE INTO schema_migrations (version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            [(version, name, utc_now()) for version, name in SCHEMA_MIGRATIONS],
        )

    def schema_status(self) -> dict[str, Any]:
        expected_versions = {version for version, _ in SCHEMA_MIGRATIONS}
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT version, name, applied_at
                FROM schema_migrations
                ORDER BY version ASC
                """
            ).fetchall()
        applied = [dict(row) for row in rows]
        applied_versions = {int(item["version"]) for item in applied}
        pending_versions = sorted(expected_versions - applied_versions)
        current_version = max(applied_versions) if applied_versions else 0
        expected_version = max(expected_versions)
        return {
            "status": "up_to_date" if not pending_versions else "pending",
            "current_version": current_version,
            "expected_version": expected_version,
            "pending_versions": pending_versions,
            "applied_migrations": applied,
        }

    def upsert_document(
        self,
        *,
        doc_id: str,
        filename: str,
        file_type: str,
        status: str,
        path: str,
        chunk_count: int = 0,
        security_review_status: str = "approved",
        prompt_injection_risks: dict[str, int] | None = None,
    ) -> None:
        risks_json = json.dumps(prompt_injection_risks or {}, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents
                    (id, filename, file_type, status, created_at, chunk_count, path,
                     security_review_status, prompt_injection_risks_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    filename=excluded.filename,
                    file_type=excluded.file_type,
                    status=excluded.status,
                    chunk_count=excluded.chunk_count,
                    path=excluded.path,
                    security_review_status=excluded.security_review_status,
                    prompt_injection_risks_json=excluded.prompt_injection_risks_json
                """,
                (
                    doc_id,
                    filename,
                    file_type,
                    status,
                    utc_now(),
                    chunk_count,
                    path,
                    security_review_status,
                    risks_json,
                ),
            )

    def list_documents(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [self._document_from_row(row) for row in rows]

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return self._document_from_row(row) if row else None

    def _document_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        risks_json = data.pop("prompt_injection_risks_json", "{}") or "{}"
        try:
            data["prompt_injection_risks"] = json.loads(str(risks_json))
        except json.JSONDecodeError:
            data["prompt_injection_risks"] = {}
        data["prompt_injection_detected"] = bool(data["prompt_injection_risks"])
        return data

    def delete_document(self, doc_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def replace_chunks(self, doc_id: str, chunks: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.executemany(
                """
                INSERT INTO chunks
                    (id, doc_id, chunk_index, text, source, page, token_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk["id"],
                        doc_id,
                        chunk["chunk_index"],
                        chunk["text"],
                        chunk["source"],
                        chunk.get("page"),
                        chunk["token_count"],
                        utc_now(),
                    )
                    for chunk in chunks
                ],
            )

    def list_chunks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT chunks.*, documents.filename AS document_name
                FROM chunks
                JOIN documents ON documents.id = chunks.doc_id
                ORDER BY chunks.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_chunks_by_doc_id(self, doc_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT chunks.*, documents.filename AS document_name
                FROM chunks
                JOIN documents ON documents.id = chunks.doc_id
                WHERE chunks.doc_id = ?
                ORDER BY chunks.chunk_index ASC
                """,
                (doc_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_report(
        self,
        report_id: str,
        ticket_id: str,
        raw_text: str,
        report: dict[str, Any],
        *,
        actor_role: str,
        actor_hash: str,
        review_status: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO reports
                    (id, ticket_id, actor_role, actor_hash, review_status,
                     review_comment, reviewed_by_hash, reviewed_at,
                     raw_text, report_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    ticket_id,
                    actor_role,
                    actor_hash,
                    review_status,
                    None,
                    None,
                    None,
                    raw_text,
                    json.dumps(report, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["report"] = json.loads(data.pop("report_json"))
        return data

    def list_reports(
        self,
        *,
        limit: int = 100,
        actor_hash: str | None = None,
        review_status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM reports"
        filters: list[str] = []
        params: list[Any] = []
        if actor_hash:
            filters.append("actor_hash = ?")
            params.append(actor_hash)
        if review_status:
            filters.append("review_status = ?")
            params.append(review_status)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        reports: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["report"] = json.loads(data.pop("report_json"))
            reports.append(data)
        return reports

    def update_report_review(
        self,
        report_id: str,
        *,
        review_status: str,
        review_comment: str | None,
        reviewed_by_hash: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE reports
                SET review_status = ?,
                    review_comment = ?,
                    reviewed_by_hash = ?,
                    reviewed_at = ?
                WHERE id = ?
                """,
                (review_status, review_comment, reviewed_by_hash, utc_now(), report_id),
            )
        return self.get_report(report_id)

    def report_review_stats(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT review_status, COUNT(*) AS count FROM reports GROUP BY review_status"
            ).fetchall()
        return {str(row["review_status"]): int(row["count"]) for row in rows}

    def purge_operational_data(
        self,
        *,
        cutoff_by_table: dict[str, str],
        dry_run: bool = True,
    ) -> dict[str, int]:
        allowed_tables = {
            "reports",
            "llm_call_logs",
            "batch_jobs",
            "idempotency_records",
            "audit_events",
        }
        with self.connect() as conn:
            deleted_counts = {
                table: int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE created_at < ?",
                        (cutoff,),
                    ).fetchone()[0]
                )
                for table, cutoff in cutoff_by_table.items()
                if table in allowed_tables
            }
            if not dry_run:
                for table, cutoff in cutoff_by_table.items():
                    if table not in allowed_tables:
                        continue
                    conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
        return deleted_counts

    def save_llm_log(
        self,
        *,
        log_id: str,
        request_id: str,
        model: str,
        prompt_version: str,
        latency_ms: int,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        tool_calls: list[str],
        error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_call_logs
                    (id, request_id, model, prompt_version, latency_ms,
                     input_tokens, output_tokens, total_tokens, tool_calls, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    request_id,
                    model,
                    prompt_version,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    json.dumps(tool_calls, ensure_ascii=False),
                    error,
                    utc_now(),
                ),
            )

    def list_logs(self, limit: int = 100, error_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM llm_call_logs"
        params: tuple[Any, ...] = ()
        if error_only:
            query += " WHERE error IS NOT NULL AND error != ''"
        query += " ORDER BY created_at DESC LIMIT ?"
        params = (limit,)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        logs = [dict(row) for row in rows]
        for log in logs:
            log["tool_calls"] = json.loads(log["tool_calls"])
        return logs

    def save_audit_event(
        self,
        *,
        event_id: str,
        request_id: str,
        actor_role: str,
        actor_hash: str,
        method: str,
        path: str,
        status_code: int,
        latency_ms: int,
        client_host: str | None,
    ) -> None:
        created_at = utc_now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous_hash = self._latest_audit_hash(conn)
            event_data = {
                "id": event_id,
                "request_id": request_id,
                "actor_role": actor_role,
                "actor_hash": actor_hash,
                "method": method,
                "path": path,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "client_host": client_host,
                "created_at": created_at,
            }
            event_hash = self._audit_event_hash(event_data, previous_hash)
            conn.execute(
                """
                INSERT INTO audit_events
                    (id, request_id, actor_role, actor_hash, method, path,
                     status_code, latency_ms, client_host, previous_hash, event_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    request_id,
                    actor_role,
                    actor_hash,
                    method,
                    path,
                    status_code,
                    latency_ms,
                    client_host,
                    previous_hash,
                    event_hash,
                    created_at,
                ),
            )

    def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_audit_chain(self) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT rowid AS _audit_rowid, * FROM audit_events ORDER BY rowid ASC",
            ).fetchall()

        total_events = len(rows)
        hashed_events = 0
        missing_hashes = 0
        event_by_hash: dict[str, dict[str, Any]] = {}
        children_by_previous_hash: dict[str, list[dict[str, Any]]] = {}
        invalid_event_ids: set[str] = set()

        for row in rows:
            data = dict(row)
            event_hash = data.get("event_hash") or ""
            stored_previous_hash = data.get("previous_hash") or ""
            if not event_hash:
                missing_hashes += 1
                continue

            hashed_events += 1
            expected_hash = self._audit_event_hash(data, stored_previous_hash)
            hash_mismatch = event_hash != expected_hash
            duplicate_hash = event_hash in event_by_hash
            if hash_mismatch or duplicate_hash:
                invalid_event_ids.add(str(data["id"]))

            event_by_hash[event_hash] = data
            children_by_previous_hash.setdefault(stored_previous_hash, []).append(data)

        if hashed_events:
            for previous_hash, children in children_by_previous_hash.items():
                if len(children) > 1:
                    invalid_event_ids.update(str(child["id"]) for child in children)
                if previous_hash != "GENESIS" and previous_hash not in event_by_hash:
                    invalid_event_ids.update(str(child["id"]) for child in children)

        visited_hashes: set[str] = set()
        current_previous_hash = "GENESIS"
        last_event_hash: str | None = None
        while True:
            children = children_by_previous_hash.get(current_previous_hash, [])
            if len(children) != 1:
                break
            child = children[0]
            event_hash = str(child["event_hash"])
            if event_hash in visited_hashes:
                invalid_event_ids.add(str(child["id"]))
                break
            visited_hashes.add(event_hash)
            last_event_hash = event_hash
            current_previous_hash = event_hash

        disconnected_events = hashed_events - len(visited_hashes)
        if disconnected_events > 0:
            invalid_event_ids.update(
                str(event["id"])
                for event_hash, event in event_by_hash.items()
                if event_hash not in visited_hashes
            )

        invalid_events = [
            dict(row) for row in rows if row["event_hash"] and str(row["id"]) in invalid_event_ids
        ]
        invalid_events.sort(key=lambda item: int(item.get("_audit_rowid") or 0))
        first_invalid_event_id = str(invalid_events[0]["id"]) if invalid_events else None
        tampered_events = len(invalid_event_ids)

        return {
            "valid": tampered_events == 0,
            "total_events": total_events,
            "hashed_events": hashed_events,
            "legacy_events_without_hash": missing_hashes,
            "tampered_events": tampered_events,
            "first_invalid_event_id": first_invalid_event_id,
            "last_event_hash": last_event_hash,
        }

    def _latest_audit_hash(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            """
            SELECT event_hash
            FROM audit_events
            WHERE event_hash IS NOT NULL AND event_hash != ''
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
        return str(row["event_hash"]) if row else "GENESIS"

    def _audit_event_hash(self, event_data: dict[str, Any], previous_hash: str) -> str:
        payload = {
            "id": event_data.get("id"),
            "request_id": event_data.get("request_id"),
            "actor_role": event_data.get("actor_role"),
            "actor_hash": event_data.get("actor_hash"),
            "method": event_data.get("method"),
            "path": event_data.get("path"),
            "status_code": event_data.get("status_code"),
            "latency_ms": event_data.get("latency_ms"),
            "client_host": event_data.get("client_host"),
            "created_at": event_data.get("created_at"),
            "previous_hash": previous_hash,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def create_batch_job(self, job_id: str, *, actor_role: str, actor_hash: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO batch_jobs
                    (id, status, actor_role, actor_hash, total, succeeded, failed,
                     result_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, "pending", actor_role, actor_hash, 0, 0, 0, None, None, now, now),
            )

    def create_batch_job_with_idempotency(
        self,
        job_id: str,
        *,
        actor_role: str,
        actor_hash: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        scope = "batch_job_create"
        response = {"job_id": job_id, "status": "pending"}
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO idempotency_records
                    (id, scope, idempotency_key, actor_hash, request_hash, resource_id,
                     response_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"idem_{hashlib.sha256(f'{scope}:{actor_hash}:{idempotency_key}'.encode()).hexdigest()[:24]}",
                    scope,
                    idempotency_key,
                    actor_hash,
                    request_hash,
                    job_id,
                    json.dumps(response, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 0:
                record = conn.execute(
                    """
                    SELECT *
                    FROM idempotency_records
                    WHERE scope = ?
                      AND actor_hash = ?
                      AND idempotency_key = ?
                    """,
                    (scope, actor_hash, idempotency_key),
                ).fetchone()
                if not record:
                    raise RuntimeError("Idempotency record could not be resolved")
                if str(record["request_hash"]) != request_hash:
                    raise ValueError("Idempotency-Key was reused with a different request body")
                job = conn.execute(
                    "SELECT * FROM batch_jobs WHERE id = ?",
                    (str(record["resource_id"]),),
                ).fetchone()
                if not job:
                    raise RuntimeError("Idempotency record points to a missing batch job")
                return self._batch_job_from_row(job), False

            conn.execute(
                """
                INSERT INTO batch_jobs
                    (id, status, actor_role, actor_hash, total, succeeded, failed,
                     result_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, "pending", actor_role, actor_hash, 0, 0, 0, None, None, now, now),
            )
            job = conn.execute("SELECT * FROM batch_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._batch_job_from_row(job), True

    def get_idempotent_batch_job(
        self,
        *,
        actor_hash: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        scope = "batch_job_create"
        with self.connect() as conn:
            record = conn.execute(
                """
                SELECT *
                FROM idempotency_records
                WHERE scope = ?
                  AND actor_hash = ?
                  AND idempotency_key = ?
                """,
                (scope, actor_hash, idempotency_key),
            ).fetchone()
            if not record:
                return None
            if str(record["request_hash"]) != request_hash:
                raise ValueError("Idempotency-Key was reused with a different request body")
            job = conn.execute(
                "SELECT * FROM batch_jobs WHERE id = ?",
                (str(record["resource_id"]),),
            ).fetchone()
            if not job:
                raise RuntimeError("Idempotency record points to a missing batch job")
            return self._batch_job_from_row(job)

    def update_batch_job(
        self,
        job_id: str,
        *,
        status: str,
        total: int = 0,
        succeeded: int = 0,
        failed: int = 0,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE batch_jobs
                SET status = ?,
                    total = ?,
                    succeeded = ?,
                    failed = ?,
                    result_json = ?,
                    error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    total,
                    succeeded,
                    failed,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error,
                    utc_now(),
                    job_id,
                ),
            )

    def cancel_batch_job(self, job_id: str, *, reason: str = "Canceled by requester") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE batch_jobs
                SET status = 'canceled',
                    error = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('pending', 'running')
                """,
                (reason, utc_now(), job_id),
            )

    def mark_interrupted_batch_jobs(
        self,
        *,
        reason: str = "Interrupted by service restart",
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE batch_jobs
                SET status = 'interrupted',
                    error = CASE
                        WHEN error IS NULL OR error = '' THEN ?
                        ELSE error
                    END,
                    updated_at = ?
                WHERE status IN ('pending', 'running')
                """,
                (reason, utc_now()),
            )
            return cursor.rowcount

    def get_batch_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM batch_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return self._batch_job_from_row(row)

    def list_batch_jobs(
        self, limit: int = 100, actor_hash: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM batch_jobs"
        params: tuple[Any, ...]
        if actor_hash:
            query += " WHERE actor_hash = ?"
            params = (actor_hash, limit)
        else:
            params = (limit,)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        jobs: list[dict[str, Any]] = []
        for row in rows:
            jobs.append(self._batch_job_from_row(row))
        return jobs

    def batch_job_status_stats(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM batch_jobs GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def active_batch_job_count(self, actor_hash: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM batch_jobs WHERE status IN ('pending', 'running')"
        params: tuple[Any, ...] = ()
        if actor_hash:
            query += " AND actor_hash = ?"
            params = (actor_hash,)
        with self.connect() as conn:
            return int(conn.execute(query, params).fetchone()[0])

    def health_check(self) -> bool:
        with self.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return True

    def sqlite_runtime_status(self) -> dict[str, Any]:
        with self.connect() as conn:
            journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
            busy_timeout_ms = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
            foreign_keys_enabled = bool(int(conn.execute("PRAGMA foreign_keys").fetchone()[0]))
            synchronous_value = int(conn.execute("PRAGMA synchronous").fetchone()[0])
            quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        return {
            "journal_mode": journal_mode,
            "busy_timeout_ms": busy_timeout_ms,
            "foreign_keys_enabled": foreign_keys_enabled,
            "synchronous": {
                0: "OFF",
                1: "NORMAL",
                2: "FULL",
                3: "EXTRA",
            }.get(synchronous_value, str(synchronous_value)),
            "quick_check": quick_check,
            "quick_check_ok": quick_check == "ok",
        }

    def stats(self) -> dict[str, int]:
        tables = [
            "documents",
            "chunks",
            "reports",
            "llm_call_logs",
            "audit_events",
            "batch_jobs",
            "idempotency_records",
        ]
        with self.connect() as conn:
            stats = {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
            }
            stats["documents_quarantined"] = int(
                conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE status = 'quarantined'"
                ).fetchone()[0]
            )
        return stats

    def _batch_job_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json")) if data.get("result_json") else None
        return data


@lru_cache
def get_database() -> Database:
    return Database(get_settings().sqlite_path)
