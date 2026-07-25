#!/usr/bin/env python3
"""
Async (background) delegation registry.

Backs ``delegate_task(background=true)``: the parent agent dispatches a
subagent that runs on a module-level daemon executor and returns a handle
immediately, so the user and the model can keep working while the child runs.

When the child finishes, a completion event is pushed onto the SHARED
``process_registry.completion_queue`` with ``type="async_delegation"``. The
CLI (``cli.py`` process_loop) and gateway (``_run_process_watcher`` /
``completion_queue`` drain) already poll that queue while the agent is idle
and forge a fresh user/internal turn from each event. We deliberately reuse
that rail rather than reaching into a running agent loop:

  - completions surface as a NEW turn when the agent is idle, never spliced
    between a tool result and an assistant message. That keeps strict
    message-role alternation legal and the prompt cache intact (hard
    invariant: never mutate past context).
  - we inherit the queue's de-dup, crash-recovery checkpoint, and the
    existing CLI + gateway drain wiring for free — no new drain loops in the
    two largest files in the repo.

The completion payload carries a RICH, self-contained task-source block (the
original goal, the context the parent supplied, toolsets, model, dispatch
time, status, and the full result summary). When the result re-enters the
conversation the parent may be deep in unrelated context and won't remember
why the subagent existed; the block lets it either use the result or
re-dispatch if the world has moved on.

This module owns ONLY the async lifecycle. The actual child build + run is
delegated back to ``delegate_tool._run_single_child`` via an injected
runner, so all the credential leasing, heartbeat, timeout, and result-shaping
logic stays in one place.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from hermes_constants import get_hermes_home
from tools.daemon_pool import DaemonThreadPoolExecutor
from tools.thread_context import propagate_context_to_thread

logger = logging.getLogger(__name__)

# Back-compat alias — the daemon executor now lives in tools.daemon_pool so
# other subsystems (tool_executor, memory_manager, delegate_tool, skills_hub)
# can share it. Existing imports of ``_DaemonThreadPoolExecutor`` keep working.
_DaemonThreadPoolExecutor = DaemonThreadPoolExecutor


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
# A persistent daemon executor (NOT a `with ThreadPoolExecutor()` block, which
# would join on exit and defeat the whole point of async). Workers are daemon
# threads so a hard process exit doesn't hang on an in-flight child.
_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()
_executor_max_workers: int = 0

_records_lock = threading.Lock()
# delegation_id -> record dict. Kept for the lifetime of the run plus a short
# tail after completion so `list_async_delegations()` can show recent results.
_records: Dict[str, Dict[str, Any]] = {}

_DEFAULT_MAX_ASYNC_CHILDREN = 3
# How many completed records to retain for status queries before pruning.
_MAX_RETAINED_COMPLETED = 50
_DURABLE_RETENTION_SECONDS = 7 * 24 * 60 * 60
_MAX_DURABLE_PENDING = 1000
# A pending completion whose delivery keeps failing is retried across claim
# cycles (and across restarts via restore_undelivered_completions). Cap the
# attempts so an unroutable row converges to a terminal 'dropped' state
# instead of replaying on every restart forever.
_MAX_DELIVERY_ATTEMPTS = 8
_DB_LOCK = threading.Lock()

_DEFAULT_LEASE_SECONDS = 90
_LEASE_RENEW_INTERVAL_SECONDS = 30
_DEFAULT_ESCALATION_MAX_ATTEMPTS = 3
_ESCALATION_CLAIM_SECONDS = 30
_AGENTBROKER_DEFAULT_URL = "http://127.0.0.1:8765"
_AGENTBROKER_SCOPE = "/Users/yb/AI/HermesWork"


def _db_path():
    return get_hermes_home() / "state.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        _initialize_schema(conn)
    except Exception:
        # A PRAGMA/DDL failure after a successful connect() must not leak the
        # just-opened connection back to the caller.
        conn.close()
        raise
    return conn


def _initialize_schema(conn: sqlite3.Connection) -> None:
    from hermes_state import apply_wal_with_fallback

    apply_wal_with_fallback(conn, db_label="state.db (async_delegation)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS async_delegations (
            delegation_id TEXT PRIMARY KEY,
            origin_session TEXT NOT NULL,
            origin_ui_session_id TEXT NOT NULL DEFAULT '',
            parent_session_id TEXT,
            state TEXT NOT NULL,
            dispatched_at REAL NOT NULL,
            completed_at REAL,
            updated_at REAL NOT NULL,
            event_json TEXT,
            result_json TEXT,
            delivery_state TEXT NOT NULL DEFAULT 'pending',
            delivery_attempts INTEGER NOT NULL DEFAULT 0,
            delivered_at REAL,
            owner_pid INTEGER,
            owner_started_at INTEGER,
            task_json TEXT,
            delivery_claim TEXT,
            delivery_claimed_at REAL,
            idempotency_key TEXT,
            request_fingerprint TEXT,
            lease_expires_at REAL,
            escalation_state TEXT NOT NULL DEFAULT 'not_required',
            escalation_attempts INTEGER NOT NULL DEFAULT 0,
            escalation_max_attempts INTEGER NOT NULL DEFAULT 3,
            escalation_next_at REAL,
            escalation_reason TEXT,
            escalation_task_id TEXT,
            escalation_error TEXT,
            receipt_json TEXT,
            origin_session_id TEXT NOT NULL DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS async_delegation_audit (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            delegation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            created_at REAL NOT NULL,
            data_json TEXT NOT NULL
        )"""
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(async_delegations)")}
    for name, sql_type in (
        ("owner_pid", "INTEGER"),
        ("owner_started_at", "INTEGER"),
        ("task_json", "TEXT"),
        ("delivery_claim", "TEXT"),
        ("delivery_claimed_at", "REAL"),
        ("idempotency_key", "TEXT"),
        ("request_fingerprint", "TEXT"),
        ("lease_expires_at", "REAL"),
        ("escalation_state", "TEXT NOT NULL DEFAULT 'not_required'"),
        ("escalation_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("escalation_max_attempts", "INTEGER NOT NULL DEFAULT 3"),
        ("escalation_next_at", "REAL"),
        ("escalation_reason", "TEXT"),
        ("escalation_task_id", "TEXT"),
        ("escalation_error", "TEXT"),
        ("receipt_json", "TEXT"),
        # Raw api_server session id (X-Hermes-Session-Id) of the ORIGINATING
        # request — the wake self-post target. Without persisting it,
        # completions recovered after a process restart are unroutable on
        # api_server (the in-memory record that carried it is gone).
        ("origin_session_id", "TEXT"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE async_delegations ADD COLUMN {name} {sql_type}")
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_async_delegations_idempotency
           ON async_delegations(idempotency_key)
           WHERE idempotency_key IS NOT NULL"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_async_delegations_escalation
           ON async_delegations(escalation_state, escalation_next_at)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_async_delegation_audit_parent
           ON async_delegation_audit(delegation_id, event_id)"""
    )


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit/rollback on exit, and ALWAYS close it.

    ``sqlite3.Connection.__enter__``/``__exit__`` only commit or roll back the
    transaction; they do not close the connection. Using ``with _connect()``
    alone therefore leaks a connection — and its WAL/SHM file descriptors — on
    every durable dispatch, completion, and delivery-claim, deferring the close
    to the garbage collector. On a long-running gateway that exhausts
    ``RLIMIT_NOFILE`` (the cron-ledger sibling of this bug was #69567 / PR #69594).
    """
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_fingerprint(record: Dict[str, Any]) -> str:
    immutable = {
        key: record.get(key)
        for key in (
            "goal", "goals", "context", "toolsets", "role", "model", "is_batch",
            "session_key", "origin_ui_session_id", "parent_session_id",
        )
        if key in record
    }
    return hashlib.sha256(_canonical_json(immutable).encode("utf-8")).hexdigest()


def _redact_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _redact_audit_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_audit_value(item) for item in value]
    if isinstance(value, str):
        try:
            from agent.redact import redact_sensitive_text

            return redact_sensitive_text(
                value[:4000], force=True, redact_url_credentials=True
            )
        except Exception:  # pragma: no cover - fail closed at the audit boundary
            return "[redacted: redactor unavailable]"
    return value


def _insert_audit(
    conn: sqlite3.Connection,
    delegation_id: str,
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    created_at: Optional[float] = None,
) -> None:
    conn.execute(
        """INSERT INTO async_delegation_audit
           (delegation_id, event_type, created_at, data_json)
           VALUES (?, ?, ?, ?)""",
        (
            delegation_id,
            event_type,
            time.time() if created_at is None else created_at,
            _canonical_json(_redact_audit_value(data or {})),
        ),
    )


def _persist_dispatch(record: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    try:
        from gateway.status import get_process_start_time
        owner_started_at = get_process_start_time(os.getpid())
    except Exception:
        owner_started_at = None
    idempotency_key = str(record.get("idempotency_key") or record["delegation_id"])
    fingerprint = str(record.get("request_fingerprint") or _request_fingerprint(record))
    lease_seconds = max(30, min(int(record.get("lease_seconds") or _DEFAULT_LEASE_SECONDS), 86400))
    record["idempotency_key"] = idempotency_key
    record["request_fingerprint"] = fingerprint
    record["lease_seconds"] = lease_seconds
    task_payload = {
        key: record.get(key)
        for key in ("goal", "goals", "context", "toolsets", "role", "model", "is_batch")
        if key in record
    }
    with _DB_LOCK, _transaction() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """SELECT delegation_id, request_fingerprint, state
               FROM async_delegations
               WHERE delegation_id=? OR idempotency_key=?""",
            (record["delegation_id"], idempotency_key),
        ).fetchall()
        if rows:
            existing = rows[0]
            conflict = len(rows) > 1 or (existing[1] or "") != fingerprint
            _insert_audit(
                conn,
                str(existing[0]),
                "dispatch_conflict" if conflict else "duplicate_suppressed",
                {"request_fingerprint": fingerprint},
                created_at=now,
            )
            return {
                "created": False,
                "conflict": conflict,
                "delegation_id": str(existing[0]),
                "state": str(existing[2]),
            }
        conn.execute(
            """INSERT INTO async_delegations
               (delegation_id, origin_session, origin_ui_session_id,
                parent_session_id, state, dispatched_at, updated_at,
                delivery_state, delivery_attempts, owner_pid,
                owner_started_at, task_json, idempotency_key,
                request_fingerprint, lease_expires_at,
                escalation_state, escalation_attempts, escalation_max_attempts,
                origin_session_id)
               VALUES (?, ?, ?, ?, 'running', ?, ?, 'pending', 0, ?, ?, ?,
                       ?, ?, ?, 'not_required', 0, ?, ?)""",
            (record["delegation_id"], record.get("session_key", ""),
             record.get("origin_ui_session_id", ""), record.get("parent_session_id"),
             record["dispatched_at"], now, os.getpid(), owner_started_at,
             _canonical_json(task_payload), idempotency_key, fingerprint,
             now + lease_seconds,
             int(record.get("escalation_max_attempts") or _DEFAULT_ESCALATION_MAX_ATTEMPTS),
             record.get("origin_session_id", "")),
        )
        _insert_audit(
            conn,
            record["delegation_id"],
            "dispatched",
            {"request_fingerprint": fingerprint, "lease_seconds": lease_seconds},
            created_at=now,
        )
    _prune_durable_records()
    return {
        "created": True,
        "conflict": False,
        "delegation_id": record["delegation_id"],
        "state": "running",
    }


def _delete_durable_delegation(delegation_id: str) -> None:
    with _DB_LOCK, _transaction() as conn:
        conn.execute("DELETE FROM async_delegation_audit WHERE delegation_id=?", (delegation_id,))
        conn.execute("DELETE FROM async_delegations WHERE delegation_id=?", (delegation_id,))


def _prune_durable_records() -> None:
    """Bound terminal history, preferring delivered records for deletion."""
    now = time.time()
    cutoff = now - _DURABLE_RETENTION_SECONDS
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            "DELETE FROM async_delegations WHERE delivery_state='delivered' AND updated_at < ?",
            (cutoff,),
        )
        terminal_count = conn.execute(
            "SELECT COUNT(*) FROM async_delegations WHERE state NOT IN ('running','finalizing')"
        ).fetchone()[0]
        excess = max(0, terminal_count - _MAX_RETAINED_COMPLETED)
        if excess:
            conn.execute(
                """DELETE FROM async_delegations WHERE delegation_id IN (
                     SELECT delegation_id FROM async_delegations
                     WHERE state NOT IN ('running','finalizing')
                     ORDER BY CASE delivery_state WHEN 'delivered' THEN 0 ELSE 1 END,
                              updated_at ASC LIMIT ?
                   )""",
                (excess,),
            )
        pending_count = conn.execute(
            """SELECT COUNT(*) FROM async_delegations
               WHERE state NOT IN ('running','finalizing') AND delivery_state='pending'"""
        ).fetchone()[0]
        overflow = max(0, pending_count - _MAX_DURABLE_PENDING)
        if overflow:
            conn.execute(
                """DELETE FROM async_delegations WHERE delegation_id IN (
                     SELECT delegation_id FROM async_delegations
                     WHERE state NOT IN ('running','finalizing') AND delivery_state='pending'
                     ORDER BY updated_at ASC LIMIT ?
                   )""",
                (overflow,),
            )
        conn.execute(
            """DELETE FROM async_delegation_audit
               WHERE delegation_id NOT IN (SELECT delegation_id FROM async_delegations)"""
        )


def _persist_completion(event: Dict[str, Any], result: Dict[str, Any]) -> None:
    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            """UPDATE async_delegations SET state=?, completed_at=?, updated_at=?,
               event_json=?, result_json=?, delivery_state='pending',
               lease_expires_at=NULL
               WHERE delegation_id=?""",
            (event.get("status", "completed"), event.get("completed_at", now), now,
             _canonical_json(event), _canonical_json(result), event["delegation_id"]),
        )
        _insert_audit(
            conn,
            str(event["delegation_id"]),
            "completed",
            {
                "status": event.get("status", "completed"),
                "error": event.get("error") or result.get("error"),
            },
            created_at=now,
        )


def _note_delivery_attempt(delegation_id: str) -> None:
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            "UPDATE async_delegations SET delivery_attempts=delivery_attempts+1, updated_at=? WHERE delegation_id=?",
            (time.time(), delegation_id),
        )


def _renew_lease(delegation_id: str, lease_seconds: int) -> bool:
    now = time.time()
    try:
        with _DB_LOCK, _transaction() as conn:
            cur = conn.execute(
                """UPDATE async_delegations
                   SET lease_expires_at=?, updated_at=?
                   WHERE delegation_id=? AND state IN ('running','finalizing')
                     AND owner_pid=?""",
                (now + lease_seconds, now, delegation_id, os.getpid()),
            )
            return cur.rowcount == 1
    except Exception:
        logger.debug("Async delegation %s lease renewal failed", delegation_id, exc_info=True)
        return False


def _run_with_lease(
    delegation_id: str, lease_seconds: int, runner: Callable[[], Dict[str, Any]]
) -> Dict[str, Any]:
    stop = threading.Event()

    def _heartbeat() -> None:
        while not stop.wait(min(_LEASE_RENEW_INTERVAL_SECONDS, lease_seconds / 3)):
            if not _renew_lease(delegation_id, lease_seconds):
                return

    heartbeat = threading.Thread(
        target=_heartbeat,
        name=f"async-lease-{delegation_id}",
        daemon=True,
    )
    heartbeat.start()
    try:
        return runner() or {}
    finally:
        stop.set()


class AgentBrokerUnavailable(RuntimeError):
    """AgentBroker is not configured or cannot be reached safely."""


def _agentbroker_token() -> str:
    token = os.environ.get("BROKER_TOKEN", "").strip()
    if 32 <= len(token) <= 4096 and not any(char.isspace() for char in token):
        return token

    token_file = os.environ.get("BROKER_TOKEN_FILE", "").strip()
    if not token_file:
        return ""
    try:
        path = Path(token_file).expanduser()
        if not path.is_absolute():
            raise ValueError("BROKER_TOKEN_FILE must be absolute")
        path = path.resolve(strict=True)
        metadata = path.stat()
        if not path.is_file() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError("BROKER_TOKEN_FILE must be owner-only")
        if metadata.st_size > 64 * 1024:
            raise ValueError("BROKER_TOKEN_FILE is too large")
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        logger.warning("AgentBroker token file rejected: %s", exc)
        return ""

    candidate = contents.strip()
    for line in contents.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "BROKER_TOKEN":
            candidate = value.strip()
            break
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {'"', "'"}:
        candidate = candidate[1:-1]
    return (
        candidate
        if 32 <= len(candidate) <= 4096
        and not any(char.isspace() for char in candidate)
        else ""
    )


def _agentbroker_base_url() -> str:
    raw = os.environ.get("AGENTBROKER_URL", _AGENTBROKER_DEFAULT_URL).strip().rstrip("/")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
    ):
        raise AgentBrokerUnavailable("AgentBroker URL must be loopback HTTP")
    return raw


def _agentbroker_json(
    method: str, path: str, payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    token = _agentbroker_token()
    if not token:
        raise AgentBrokerUnavailable("BROKER_TOKEN is not configured")
    request = Request(
        _agentbroker_base_url() + path,
        data=_canonical_json(payload).encode("utf-8") if payload is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310 - loopback-only URL above
            raw = response.read(1024 * 1024)
    except HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        safe = _redact_audit_value(body)
        raise RuntimeError(f"AgentBroker HTTP {exc.code}: {safe}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise AgentBrokerUnavailable(f"AgentBroker unavailable: {type(exc).__name__}") from exc
    data = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(data, dict):
        raise RuntimeError("AgentBroker returned a non-object response")
    return data


def _submit_agentbroker_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _agentbroker_json("POST", "/tasks", payload)


def _build_escalation_task(row: Dict[str, Any]) -> Dict[str, Any]:
    source_key = str(row.get("idempotency_key") or row["delegation_id"])
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:32]
    return {
        "task_id": f"hermes_escalation_{digest}",
        "idempotency_key": f"hermes_escalation_{digest}",
        "correlation_id": str(row["delegation_id"]),
        "requesting_agent": "hermes-manager",
        "target_agent": "qa-agent",
        "task_type": "code_qa",
        "allowed_scope": _AGENTBROKER_SCOPE,
        "permission_level": "read_only",
        "timeout_seconds": 300,
        "human_approval_required": True,
        "max_attempts": _DEFAULT_ESCALATION_MAX_ATTEMPTS,
        "payload": {
            "kind": "hermes_delegation_recovery",
            "delegation_id": str(row["delegation_id"]),
            "request_fingerprint": str(row.get("request_fingerprint") or ""),
            "failure_state": str(row.get("state") or "unknown"),
            "reason": str(row.get("escalation_reason") or "Delegation outcome unknown"),
            "requested_action": (
                "Review the failed delegated session and return a safe recovery "
                "recommendation. Do not execute consequential actions."
            ),
        },
    }


def _queue_escalation(delegation_id: str, reason: str) -> bool:
    now = time.time()
    safe_reason = str(_redact_audit_value(reason))[:2000]
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            """UPDATE async_delegations
               SET escalation_state='pending', escalation_next_at=?,
                   escalation_reason=?, escalation_error=NULL, updated_at=?
               WHERE delegation_id=? AND escalation_state='not_required'""",
            (now, safe_reason, now, delegation_id),
        )
        if cur.rowcount:
            _insert_audit(
                conn,
                delegation_id,
                "escalation_queued",
                {"reason": safe_reason},
                created_at=now,
            )
        return cur.rowcount == 1


def _schedule_escalation_retry(delegation_id: str, delay_seconds: int) -> None:
    timer = threading.Timer(
        delay_seconds,
        lambda: process_pending_escalations(delegation_id=delegation_id),
    )
    timer.name = f"async-escalation-{delegation_id}"
    timer.daemon = True
    timer.start()


def process_pending_escalations(
    *,
    submitter: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    now: Optional[float] = None,
    limit: int = 20,
    delegation_id: Optional[str] = None,
) -> int:
    """Submit due recovery requests to AgentBroker with a durable retry bound."""
    using_default_submitter = submitter is None
    if submitter is None:
        if not _agentbroker_token():
            return 0
        submitter = _submit_agentbroker_task
    clock = time.time() if now is None else float(now)
    processed = 0
    for _ in range(max(0, min(int(limit), 100))):
        with _DB_LOCK, _transaction() as conn:
            conn.execute(
                """UPDATE async_delegations
                   SET escalation_state=CASE
                         WHEN escalation_attempts >= escalation_max_attempts
                         THEN 'exhausted' ELSE 'pending' END,
                       updated_at=?
                   WHERE escalation_state='submitting'
                     AND escalation_next_at IS NOT NULL
                     AND escalation_next_at <= ?""",
                (clock, clock),
            )
            params: List[Any] = [clock]
            selector = ""
            if delegation_id:
                selector = " AND delegation_id=?"
                params.append(delegation_id)
            row = conn.execute(
                """SELECT delegation_id, idempotency_key, request_fingerprint,
                          state, escalation_attempts, escalation_max_attempts,
                          escalation_reason
                   FROM async_delegations
                   WHERE escalation_state='pending'
                     AND escalation_attempts < escalation_max_attempts
                     AND COALESCE(escalation_next_at, 0) <= ?"""
                + selector
                + " ORDER BY updated_at, delegation_id LIMIT 1",
                tuple(params),
            ).fetchone()
            if row is None:
                break
            item = {
                "delegation_id": row[0],
                "idempotency_key": row[1],
                "request_fingerprint": row[2],
                "state": row[3],
                "escalation_attempts": int(row[4] or 0),
                "escalation_max_attempts": int(
                    row[5] or _DEFAULT_ESCALATION_MAX_ATTEMPTS
                ),
                "escalation_reason": row[6],
            }
            attempt = item["escalation_attempts"] + 1
            claimed = conn.execute(
                """UPDATE async_delegations
                   SET escalation_state='submitting', escalation_attempts=?,
                       escalation_next_at=?, updated_at=?
                   WHERE delegation_id=? AND escalation_state='pending'
                     AND escalation_attempts=?""",
                (
                    attempt,
                    clock + _ESCALATION_CLAIM_SECONDS,
                    clock,
                    item["delegation_id"],
                    item["escalation_attempts"],
                ),
            )
            if claimed.rowcount != 1:
                continue
            _insert_audit(
                conn,
                item["delegation_id"],
                "escalation_attempted",
                {"attempt": attempt, "max_attempts": item["escalation_max_attempts"]},
                created_at=clock,
            )

        processed += 1
        try:
            response = submitter(_build_escalation_task(item))
            if not isinstance(response, dict) or not response.get("task_id"):
                raise RuntimeError("AgentBroker response missing task_id")
            safe_response = _redact_audit_value(response)
            task_id = str(response["task_id"])
            with _DB_LOCK, _transaction() as conn:
                conn.execute(
                    """UPDATE async_delegations
                       SET escalation_state='submitted', escalation_task_id=?,
                           escalation_next_at=NULL, escalation_error=NULL,
                           receipt_json=?, updated_at=?
                       WHERE delegation_id=?""",
                    (
                        task_id,
                        _canonical_json({"submission": safe_response, "updated_at": clock}),
                        clock,
                        item["delegation_id"],
                    ),
                )
                _insert_audit(
                    conn,
                    item["delegation_id"],
                    "escalation_submitted",
                    {"task_id": task_id, "status": response.get("status")},
                    created_at=clock,
                )
        except Exception as exc:  # noqa: BLE001 - durable retry boundary
            safe_error = str(_redact_audit_value(f"{type(exc).__name__}: {exc}"))[:2000]
            exhausted = attempt >= item["escalation_max_attempts"]
            backoff = min(2 ** max(0, attempt - 1), 60)
            with _DB_LOCK, _transaction() as conn:
                conn.execute(
                    """UPDATE async_delegations
                       SET escalation_state=?, escalation_next_at=?,
                           escalation_error=?, updated_at=?
                       WHERE delegation_id=?""",
                    (
                        "exhausted" if exhausted else "pending",
                        None if exhausted else clock + backoff,
                        safe_error,
                        clock,
                        item["delegation_id"],
                    ),
                )
                _insert_audit(
                    conn,
                    item["delegation_id"],
                    "escalation_exhausted" if exhausted else "escalation_failed",
                    {"attempt": attempt, "error": safe_error},
                    created_at=clock,
                )
            if not exhausted and using_default_submitter:
                _schedule_escalation_retry(item["delegation_id"], backoff)
    return processed


def _failure_reason(status: str, result: Dict[str, Any]) -> Optional[str]:
    if status not in {"error", "failed", "failure", "timeout", "unknown"}:
        return None
    errors = [str(result.get("error") or "").strip()]
    for child in result.get("results") or []:
        if isinstance(child, dict) and child.get("status") not in {"completed", "success"}:
            errors.append(str(child.get("error") or child.get("exit_reason") or "").strip())
    detail = "; ".join(value for value in errors if value)[:2000]
    return f"Delegation ended with status {status}" + (f": {detail}" if detail else "")


def _attach_escalation_to_event(event: Dict[str, Any]) -> None:
    delegation_id = str(event.get("delegation_id") or "")
    with _DB_LOCK, _transaction() as conn:
        row = conn.execute(
            """SELECT escalation_state, escalation_attempts,
                      escalation_max_attempts, escalation_task_id,
                      escalation_error
               FROM async_delegations WHERE delegation_id=?""",
            (delegation_id,),
        ).fetchone()
        if row is None:
            return
        event["escalation"] = {
            "state": row[0],
            "attempts": int(row[1] or 0),
            "max_attempts": int(row[2] or _DEFAULT_ESCALATION_MAX_ATTEMPTS),
            "task_id": row[3],
            "error": row[4],
        }
        conn.execute(
            "UPDATE async_delegations SET event_json=? WHERE delegation_id=?",
            (_canonical_json(event), delegation_id),
        )


def recover_abandoned_delegations(
    *,
    escalation_submitter: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> int:
    """Classify records whose owning process disappeared as outcome unknown."""
    try:
        from gateway.status import _pid_exists, get_process_start_time
    except Exception:
        return 0
    now = time.time()
    recovered_events: List[Dict[str, Any]] = []
    with _DB_LOCK, _transaction() as conn:
        rows = conn.execute(
            """SELECT delegation_id, origin_session, origin_ui_session_id,
                      parent_session_id, dispatched_at, owner_pid,
                      owner_started_at, task_json, lease_expires_at,
                      origin_session_id
               FROM async_delegations WHERE state IN ('running','finalizing')"""
        ).fetchall()
        for row in rows:
            (
                delegation_id, session_key, origin_ui, parent_id, dispatched_at,
                pid, started, task_json, lease_expires_at, origin_session_id,
            ) = row
            live = False
            if pid:
                live = _pid_exists(int(pid))
                if live and started is not None:
                    live = get_process_start_time(int(pid)) == int(started)
                if live and lease_expires_at is not None:
                    live = float(lease_expires_at) > now
            if live:
                continue
            task = json.loads(task_json or "{}")
            event = {
                "type": "async_delegation", "delegation_id": delegation_id,
                "session_key": session_key, "origin_ui_session_id": origin_ui,
                # Restore the durable wake target so completions recovered
                # after a restart remain routable to api_server sessions.
                "origin_session_id": origin_session_id or "",
                "parent_session_id": parent_id, "goal": task.get("goal", ""),
                "goals": task.get("goals"), "context": task.get("context"),
                "toolsets": task.get("toolsets"), "role": task.get("role"),
                "model": task.get("model"), "is_batch": bool(task.get("is_batch")),
                "status": "unknown", "summary": None,
                "error": (
                    "Delegation owner lease expired before recording a terminal "
                    "result; outcome unknown."
                ),
                "dispatched_at": dispatched_at, "completed_at": now,
            }
            result = {"status": "unknown", "summary": None, "error": event["error"]}
            conn.execute(
                """UPDATE async_delegations SET state='unknown', completed_at=?,
                   updated_at=?, event_json=?, result_json=?, delivery_state='pending',
                   lease_expires_at=NULL
                   WHERE delegation_id=?""",
                (now, now, _canonical_json(event), _canonical_json(result), delegation_id),
            )
            _insert_audit(
                conn,
                delegation_id,
                "abandoned_recovered",
                {"status": "unknown", "reason": event["error"]},
                created_at=now,
            )
            recovered_events.append(event)
    for event in recovered_events:
        _queue_escalation(str(event["delegation_id"]), str(event["error"]))
    if recovered_events:
        process_pending_escalations(submitter=escalation_submitter)
        for event in recovered_events:
            _attach_escalation_to_event(event)
    return len(recovered_events)


def restore_undelivered_completions(target_queue) -> int:
    """Enqueue durable pending completions as fresh turns after process start.

    Every restored event is stamped ``restored=True`` (in-memory only — the
    stamp is added after the durable payload is deserialized and is never
    persisted). Restored events originate from a *previous* process, so no
    consumer in THIS process implicitly owns them: drain paths that run
    without an ownership filter (the legacy single-session behavior) must
    leave them queued for a consumer that can positively prove ownership,
    otherwise a brand-new session adopts a dead session's delegation
    results seconds after boot (#64484).
    """
    recover_abandoned_delegations()
    process_pending_escalations()
    with _DB_LOCK, _transaction() as conn:
        rows = conn.execute(
            """SELECT delegation_id, event_json, escalation_state,
                      escalation_attempts, escalation_max_attempts,
                      escalation_task_id, escalation_error
               FROM async_delegations
               WHERE state != 'running' AND delivery_state='pending' AND event_json IS NOT NULL
               ORDER BY completed_at, delegation_id"""
        ).fetchall()
        for (
            _delegation_id, payload, escalation_state, escalation_attempts,
            escalation_max_attempts, escalation_task_id, escalation_error,
        ) in rows:
            evt = json.loads(payload)
            if isinstance(evt, dict):
                evt["restored"] = True
                evt["escalation"] = {
                    "state": escalation_state,
                    "attempts": int(escalation_attempts or 0),
                    "max_attempts": int(
                        escalation_max_attempts or _DEFAULT_ESCALATION_MAX_ATTEMPTS
                    ),
                    "task_id": escalation_task_id,
                    "error": escalation_error,
                }
            target_queue.put(evt)
    return len(rows)


def mark_completion_delivered(delegation_id: str) -> bool:
    """Atomically acknowledge successful injection of a durable completion."""
    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            """UPDATE async_delegations SET delivery_state='delivered', delivered_at=?, updated_at=?
               WHERE delegation_id=? AND delivery_state!='delivered'""",
            (now, now, delegation_id),
        )
        return cur.rowcount == 1


def claim_completion_delivery(delegation_id: str, claim_id: str) -> bool:
    """Claim one pending completion across competing consumers/processes."""
    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        row = conn.execute(
            "SELECT delivery_state FROM async_delegations WHERE delegation_id=?",
            (delegation_id,),
        ).fetchone()
        if row is None:
            return True  # legacy event created before durable dispatch
        cur = conn.execute(
            """UPDATE async_delegations SET delivery_claim=?, delivery_claimed_at=?,
                      delivery_attempts=delivery_attempts+1, updated_at=?
               WHERE delegation_id=? AND delivery_state='pending'
                 AND (delivery_claim IS NULL OR delivery_claimed_at < ?)""",
            (claim_id, now, now, delegation_id, now - 300),
        )
        return cur.rowcount == 1


def claim_event_delivery(evt: Dict[str, Any], consumer: str) -> Optional[str]:
    """Claim a durable delegation event; non-durable events need no token."""
    if evt.get("type") != "async_delegation":
        return ""
    delegation_id = str(evt.get("delegation_id") or "")
    if not delegation_id:
        return ""
    claim_id = f"{consumer}:{__import__('os').getpid()}:{uuid.uuid4().hex}"
    return claim_id if claim_completion_delivery(delegation_id, claim_id) else None


def release_completion_delivery(delegation_id: str, claim_id: str) -> bool:
    """Release a failed delivery claim so another consumer may retry.

    Attempts are counted at claim time, so a row that keeps being claimed and
    released has burned real delivery attempts. Once the budget is exhausted
    the row converges to a terminal ``dropped`` state instead of returning to
    ``pending`` — otherwise an undeliverable completion replays on every
    gateway restart forever (restore_undelivered_completions only restores
    pending rows).
    """
    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        capped = conn.execute(
            """UPDATE async_delegations SET delivery_state='dropped',
                      delivery_claim=NULL, delivery_claimed_at=NULL, updated_at=?
               WHERE delegation_id=? AND delivery_state='pending'
                 AND delivery_claim=? AND delivery_attempts>=?""",
            (now, delegation_id, claim_id, _MAX_DELIVERY_ATTEMPTS),
        )
        if capped.rowcount == 1:
            logger.warning(
                "Async delegation %s exhausted its %d delivery attempts; "
                "marking terminally dropped (result remains queryable).",
                delegation_id, _MAX_DELIVERY_ATTEMPTS,
            )
            return True
        cur = conn.execute(
            """UPDATE async_delegations SET delivery_claim=NULL,
                      delivery_claimed_at=NULL, updated_at=?
               WHERE delegation_id=? AND delivery_state='pending'
                 AND delivery_claim=?""",
            (now, delegation_id, claim_id),
        )
        return cur.rowcount == 1


def drop_completion_delivery(delegation_id: str, claim_id: str) -> bool:
    """Terminally drop a claimed completion that can never be delivered.

    Used when the delivery target is permanently gone — the spawning session
    ended at an explicit user boundary (/new, reset) rather than a compression
    rotation. Marking the row ``dropped`` (not ``delivered``) keeps the ack
    honest, and (not ``pending``) keeps restart recovery from replaying a
    completion that will be fail-closed dropped again every time.
    """
    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            """UPDATE async_delegations SET delivery_state='dropped',
                      updated_at=?, delivery_claim=NULL,
                      delivery_claimed_at=NULL
               WHERE delegation_id=? AND delivery_state='pending'
                 AND delivery_claim=?""",
            (now, delegation_id, claim_id),
        )
        return cur.rowcount == 1


def complete_completion_delivery(delegation_id: str, claim_id: str) -> bool:
    """Acknowledge acceptance for the consumer holding this claim."""
    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            """UPDATE async_delegations SET delivery_state='delivered',
                      delivered_at=?, updated_at=?, delivery_claim=NULL,
                      delivery_claimed_at=NULL
               WHERE delegation_id=? AND delivery_state='pending'
                 AND delivery_claim=?""",
            (now, now, delegation_id, claim_id),
        )
        return cur.rowcount == 1


def complete_event_delivery(evt: Dict[str, Any], claim_id: str) -> None:
    if claim_id and evt.get("type") == "async_delegation":
        complete_completion_delivery(str(evt.get("delegation_id") or ""), claim_id)


def release_event_delivery(evt: Dict[str, Any], claim_id: str) -> None:
    if claim_id and evt.get("type") == "async_delegation":
        release_completion_delivery(str(evt.get("delegation_id") or ""), claim_id)


def get_durable_delegation(delegation_id: str) -> Optional[Dict[str, Any]]:
    with _DB_LOCK, _transaction() as conn:
        row = conn.execute(
            """SELECT origin_session, state, dispatched_at, completed_at,
                      result_json, delivery_state, delivery_attempts,
                      idempotency_key, request_fingerprint, lease_expires_at,
                      escalation_state, escalation_attempts,
                      escalation_max_attempts, escalation_next_at,
                      escalation_reason, escalation_task_id, escalation_error,
                      receipt_json, origin_session_id
               FROM async_delegations WHERE delegation_id=?""", (delegation_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "delegation_id": delegation_id, "origin_session": row[0], "state": row[1],
        "dispatched_at": row[2], "completed_at": row[3],
        "result": json.loads(row[4]) if row[4] else None,
        "delivery_state": row[5], "delivery_attempts": row[6],
        "idempotency_key": row[7], "request_fingerprint": row[8],
        "lease_expires_at": row[9],
        "escalation": {
            "state": row[10], "attempts": int(row[11] or 0),
            "max_attempts": int(row[12] or _DEFAULT_ESCALATION_MAX_ATTEMPTS),
            "next_at": row[13], "reason": row[14], "task_id": row[15],
            "error": row[16],
        },
        "receipt": json.loads(row[17]) if row[17] else None,
        "origin_session_id": row[18] or "",
    }


def get_delegation_audit(delegation_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
    bounded = max(1, min(int(limit), 500))
    with _DB_LOCK, _transaction() as conn:
        rows = conn.execute(
            """SELECT event_id, event_type, created_at, data_json
               FROM async_delegation_audit WHERE delegation_id=?
               ORDER BY event_id DESC LIMIT ?""",
            (delegation_id, bounded),
        ).fetchall()
    return [
        {
            "event_id": row[0],
            "event_type": row[1],
            "created_at": row[2],
            "data": json.loads(row[3]) if row[3] else {},
        }
        for row in reversed(rows)
    ]


def refresh_delegation_receipt(
    delegation_id: str,
    *,
    fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    current = get_durable_delegation(delegation_id)
    if current is None:
        return None
    task_id = str(current["escalation"].get("task_id") or "")
    if not task_id:
        return current.get("receipt")
    if fetcher is None:
        if not _agentbroker_token():
            return current.get("receipt")
        fetcher = lambda path: _agentbroker_json("GET", path)
    task = fetcher(f"/tasks/{task_id}")
    receipt = None
    try:
        receipt = fetcher(f"/tasks/{task_id}/receipt")
    except Exception as exc:  # receipt is absent until the broker task is terminal
        if "404" not in str(exc):
            raise
    updated_at = time.time()
    snapshot = _redact_audit_value(
        {"task": task, "receipt": receipt, "updated_at": updated_at}
    )
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            "UPDATE async_delegations SET receipt_json=?, updated_at=? WHERE delegation_id=?",
            (_canonical_json(snapshot), updated_at, delegation_id),
        )
        _insert_audit(
            conn,
            delegation_id,
            "receipt_refreshed",
            {"task_id": task_id, "status": task.get("status")},
            created_at=updated_at,
        )
    return snapshot


def get_delegation_receipt(
    delegation_id: str,
    *,
    refresh: bool = False,
    fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if refresh:
        return refresh_delegation_receipt(delegation_id, fetcher=fetcher)
    current = get_durable_delegation(delegation_id)
    return None if current is None else current.get("receipt")


def get_delegation_status(delegation_id: str) -> Optional[Dict[str, Any]]:
    current = get_durable_delegation(delegation_id)
    if current is not None:
        current["audit"] = get_delegation_audit(delegation_id)
    return current


def _get_executor(max_workers: int) -> ThreadPoolExecutor:
    """Lazily create (or grow) the shared daemon executor.

    We never shrink — ThreadPoolExecutor can't resize — but if the configured
    cap grows between calls we rebuild a larger pool. Existing in-flight
    futures keep running on the old pool until it's garbage collected.
    """
    global _executor, _executor_max_workers
    with _executor_lock:
        if _executor is None or max_workers > _executor_max_workers:
            # Daemon threads: thread_name_prefix aids debugging in stack dumps.
            _executor = _DaemonThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="async-delegate",
            )
            _executor_max_workers = max_workers
        return _executor


def active_count() -> int:
    """Number of async delegations currently running."""
    with _records_lock:
        return sum(1 for r in _records.values() if r.get("status") in {"running", "finalizing"})


def _new_delegation_id() -> str:
    return f"deleg_{uuid.uuid4().hex[:8]}"


def _delegation_id_for_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
    return f"deleg_{digest}"


def _prune_completed_locked() -> None:
    """Drop the oldest completed records beyond the retention cap.

    Caller must hold ``_records_lock``.
    """
    completed = [
        (rid, r)
        for rid, r in _records.items()
        if r.get("status") != "running"
    ]
    if len(completed) <= _MAX_RETAINED_COMPLETED:
        return
    # Oldest-first by completion time (fall back to dispatch time).
    completed.sort(key=lambda kv: kv[1].get("completed_at") or kv[1].get("dispatched_at") or 0)
    for rid, _ in completed[: len(completed) - _MAX_RETAINED_COMPLETED]:
        _records.pop(rid, None)


def _current_origin_session_id() -> str:
    """Raw session id of the ORIGINATING api_server request, or ``""``.

    The obvious source — ``HERMES_SESSION_ID`` via ``get_session_env`` — is
    NOT safe to read at dispatch time: constructing a child agent
    (``agent/agent_init.py``) calls ``set_current_session_id(child.session_id)``,
    clobbering that ContextVar *and* ``os.environ`` with the subagent's
    internal ``{timestamp}_{uuid}`` id moments before the dispatch code reads
    it, so the completion wake would self-post into the subagent's own
    (unread) session instead of the spawner's.

    The request-scoped ``HERMES_SESSION_CHAT_ID`` binding survives child
    construction: ``_bind_api_server_session`` binds ``chat_id`` to the raw
    ``X-Hermes-Session-Id``, and its only writer is ``set_session_vars`` —
    ``set_current_session_id`` never touches it. Gate on the platform: on
    push platforms ``chat_id`` is a chat, not a session, so yield ``""``
    there.
    """
    try:
        from gateway.session_context import get_session_env

        if get_session_env("HERMES_SESSION_PLATFORM", "") != "api_server":
            return ""
        return get_session_env("HERMES_SESSION_CHAT_ID", "") or ""
    except Exception:
        return ""


def dispatch_async_delegation(
    *,
    goal: str,
    context: Optional[str],
    toolsets: Optional[List[str]],
    role: str,
    model: Optional[str],
    session_key: str,
    parent_session_id: Optional[str] = None,
    runner: Callable[[], Dict[str, Any]],
    origin_ui_session_id: str = "",
    origin_session_id: str = "",
    interrupt_fn: Optional[Callable[[], None]] = None,
    max_async_children: int = _DEFAULT_MAX_ASYNC_CHILDREN,
    delegation_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    lease_seconds: int = _DEFAULT_LEASE_SECONDS,
    escalation_max_attempts: int = _DEFAULT_ESCALATION_MAX_ATTEMPTS,
) -> Dict[str, Any]:
    """Spawn ``runner`` on the daemon executor and return a handle immediately.

    Parameters
    ----------
    goal, context, toolsets, role, model
        The dispatch-time task spec, captured verbatim for the rich
        completion block.
    session_key
        The gateway session_key (from ``tools.approval.get_current_session_key``)
        captured on the parent thread BEFORE dispatch, because the daemon
        worker thread won't carry the contextvar. Used to route the
        completion back to the originating session.
    parent_session_id
        The durable ``state.db`` session id of the parent agent that spawned
        the delegation. Carried on the completion event so the gateway can
        pin routing to the spawning session instead of recovering the latest
        ``ended_at IS NULL`` row for the peer tuple (#57498).
    runner
        Zero-arg callable that builds + runs the child and returns the same
        result dict ``_run_single_child`` produces. Runs on the worker thread.
    interrupt_fn
        Optional callable to signal the child to stop (used on shutdown /
        explicit cancel).
    max_async_children
        Concurrency cap. When at capacity the dispatch is REJECTED (the caller
        should fall back to sync or tell the user) rather than queued, so a
        runaway model can't pile up unbounded background work.

    Returns
    -------
    dict
        ``{"status": "dispatched", "delegation_id": ...}`` on success, or
        ``{"status": "rejected", "error": ...}`` when at capacity.
    """
    idempotency_key = str(idempotency_key or delegation_id or _new_delegation_id())
    delegation_id = delegation_id or _delegation_id_for_key(idempotency_key)
    dispatched_at = time.time()
    record: Dict[str, Any] = {
        "delegation_id": delegation_id,
        "goal": goal,
        "context": context,
        "toolsets": list(toolsets) if toolsets else None,
        "role": role,
        "model": model,
        "session_key": session_key,
        "origin_ui_session_id": origin_ui_session_id,
        "origin_session_id": origin_session_id,
        "parent_session_id": parent_session_id,
        "status": "running",
        "dispatched_at": dispatched_at,
        "completed_at": None,
        "interrupt_fn": interrupt_fn,
        "idempotency_key": idempotency_key,
        "lease_seconds": lease_seconds,
        "escalation_max_attempts": max(
            1, min(int(escalation_max_attempts), 10)
        ),
    }
    # Capacity check and record insert under ONE lock hold — checking
    # active_count() separately would let two concurrent dispatches (e.g.
    # from different gateway sessions) both pass the check and exceed the cap.
    with _records_lock:
        persisted = _persist_dispatch(record)
        if not persisted["created"]:
            if persisted["conflict"]:
                return {
                    "status": "rejected",
                    "reason": "idempotency_conflict",
                    "error": "Async delegation idempotency key conflicts with different task content.",
                    "delegation_id": persisted["delegation_id"],
                }
            return {
                "status": "dispatched",
                "delegation_id": persisted["delegation_id"],
                "state": persisted["state"],
                "idempotent_replay": True,
            }
        running = sum(
            1 for r in _records.values() if r.get("status") == "running"
        )
        if running >= max_async_children:
            _delete_durable_delegation(delegation_id)
            return {
                "status": "rejected",
                "error": (
                    f"Async delegation capacity reached ({max_async_children} "
                    f"running). Wait for one to finish (its result will re-enter "
                    f"the chat), or run this task synchronously "
                    f"(background=false). Raise delegation.max_concurrent_children in "
                    f"config.yaml to allow more concurrent background subagents."
                ),
            }
        _records[delegation_id] = record

    executor = _get_executor(max_async_children)

    def _worker() -> None:
        result: Dict[str, Any] = {}
        status = "error"
        try:
            result = _run_with_lease(delegation_id, record["lease_seconds"], runner)
            status = result.get("status") or "completed"
        except Exception as exc:  # noqa: BLE001 — must never crash the worker
            logger.exception("Async delegation %s crashed", delegation_id)
            result = {
                "status": "error",
                "summary": None,
                "error": f"{type(exc).__name__}: {exc}",
                "api_calls": 0,
                "duration_seconds": round(time.time() - dispatched_at, 2),
            }
            status = "error"
        finally:
            _finalize(delegation_id, result, status)

    try:
        # Propagate the dispatching profile so the detached child resolves
        # get_hermes_home() under the right profile.
        executor.submit(propagate_context_to_thread(_worker))
    except Exception as exc:  # pragma: no cover — pool submit failure is rare
        with _records_lock:
            _records.pop(delegation_id, None)
        _delete_durable_delegation(delegation_id)
        return {
            "status": "rejected",
            "error": f"Failed to schedule async delegation: {exc}",
        }

    logger.info(
        "Dispatched async delegation %s (session_key=%s): %s",
        delegation_id, session_key or "<cli>", (goal or "")[:80],
    )
    return {"status": "dispatched", "delegation_id": delegation_id}


def _finalize(delegation_id: str, result: Dict[str, Any], status: str) -> None:
    """Mark a record complete and push the completion event onto the queue."""
    with _records_lock:
        record = _records.get(delegation_id)
        if record is None:
            return
        # Stay active until durable persistence and queue publication finish;
        # otherwise process shutdown can kill this daemon worker in the narrow
        # gap after status flips but before SQLite is committed.
        record["status"] = "finalizing"
        record["completed_at"] = time.time()
        record["interrupt_fn"] = None  # drop the closure; child is done
        event_record = dict(record)

    _push_completion_event(event_record, result, status)
    with _records_lock:
        record = _records.get(delegation_id)
        if record is not None:
            record["status"] = status
        _prune_completed_locked()


def _push_completion_event(
    record: Dict[str, Any], result: Dict[str, Any], status: str
) -> None:
    """Push a type='async_delegation' event onto the shared completion queue.

    Best-effort: a failure here must not crash the worker, but it WOULD mean a
    silently-lost result, so we log loudly.
    """
    try:
        from tools.process_registry import process_registry
    except Exception as exc:  # pragma: no cover
        logger.error(
            "Async delegation %s finished but process_registry import failed; "
            "result lost: %s",
            record.get("delegation_id"), exc,
        )
        return

    summary = result.get("summary")
    error = result.get("error")
    dispatched_at = record.get("dispatched_at") or time.time()
    completed_at = record.get("completed_at") or time.time()

    evt = {
        "type": "async_delegation",
        "delegation_id": record.get("delegation_id"),
        # session_key routes the completion back to the originating gateway
        # session; empty string => CLI (single-session) path.
        "session_key": record.get("session_key", ""),
        "origin_ui_session_id": record.get("origin_ui_session_id", ""),
        "origin_session_id": record.get("origin_session_id", ""),
        "parent_session_id": record.get("parent_session_id"),
        "goal": record.get("goal", ""),
        "context": record.get("context"),
        "toolsets": record.get("toolsets"),
        "role": record.get("role"),
        "model": result.get("model") or record.get("model"),
        "status": status,
        "summary": summary,
        "error": error,
        "api_calls": result.get("api_calls", 0),
        "duration_seconds": result.get(
            "duration_seconds", round(completed_at - dispatched_at, 2)
        ),
        "dispatched_at": dispatched_at,
        "completed_at": completed_at,
        "exit_reason": result.get("exit_reason"),
    }
    _persist_completion(evt, result)
    reason = _failure_reason(status, result)
    if reason:
        _queue_escalation(str(record.get("delegation_id") or ""), reason)
        process_pending_escalations(delegation_id=str(record.get("delegation_id") or ""))
    _attach_escalation_to_event(evt)
    try:
        process_registry.completion_queue.put(evt)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "Async delegation %s: failed to enqueue completion event; "
            "result lost: %s",
            record.get("delegation_id"), exc,
        )


def dispatch_async_delegation_batch(
    *,
    goals: List[str],
    context: Optional[str],
    toolsets: Optional[List[str]],
    role: str,
    model: Optional[str],
    session_key: str,
    parent_session_id: Optional[str] = None,
    runner: Callable[[], Dict[str, Any]],
    origin_ui_session_id: str = "",
    origin_session_id: str = "",
    interrupt_fn: Optional[Callable[[], None]] = None,
    max_async_children: int = _DEFAULT_MAX_ASYNC_CHILDREN,
    delegation_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    lease_seconds: int = _DEFAULT_LEASE_SECONDS,
    escalation_max_attempts: int = _DEFAULT_ESCALATION_MAX_ATTEMPTS,
) -> Dict[str, Any]:
    """Dispatch a WHOLE fan-out batch as ONE background unit.

    Unlike ``dispatch_async_delegation`` (which backs a single subagent),
    ``runner`` here runs the entire batch — it builds and joins on every child
    in parallel and returns the combined ``{"results": [...],
    "total_duration_seconds": N}`` dict that the synchronous path would have
    returned. We occupy ONE async slot for the whole batch (the in-batch
    parallelism is bounded separately by ``max_concurrent_children``), so a
    single ``delegate_task`` fan-out never exhausts the async pool by itself.

    When the batch finishes, a SINGLE completion event is pushed onto the
    shared ``process_registry.completion_queue`` carrying the full per-task
    ``results`` list, so the consolidated summaries re-enter the conversation
    as one message once every child is done — the chat is never blocked while
    they run.

    Returns ``{"status": "dispatched", "delegation_id": ...}`` on success or
    ``{"status": "rejected", "error": ...}`` when the async pool is at
    capacity.
    """
    idempotency_key = str(idempotency_key or delegation_id or _new_delegation_id())
    delegation_id = delegation_id or _delegation_id_for_key(idempotency_key)
    dispatched_at = time.time()
    n = len(goals)
    # A combined goal label for status listings / the completion header.
    combined_goal = (
        goals[0] if n == 1 else f"{n} parallel subagents: " + "; ".join(g[:40] for g in goals)
    )
    record: Dict[str, Any] = {
        "delegation_id": delegation_id,
        "goal": combined_goal,
        "goals": list(goals),
        "context": context,
        "toolsets": list(toolsets) if toolsets else None,
        "role": role,
        "model": model,
        "session_key": session_key,
        "origin_ui_session_id": origin_ui_session_id,
        "origin_session_id": origin_session_id,
        "parent_session_id": parent_session_id,
        "status": "running",
        "dispatched_at": dispatched_at,
        "completed_at": None,
        "interrupt_fn": interrupt_fn,
        "is_batch": True,
        "idempotency_key": idempotency_key,
        "lease_seconds": lease_seconds,
        "escalation_max_attempts": max(
            1, min(int(escalation_max_attempts), 10)
        ),
    }
    with _records_lock:
        persisted = _persist_dispatch(record)
        if not persisted["created"]:
            if persisted["conflict"]:
                return {
                    "status": "rejected",
                    "reason": "idempotency_conflict",
                    "error": "Async delegation idempotency key conflicts with different task content.",
                    "delegation_id": persisted["delegation_id"],
                }
            return {
                "status": "dispatched",
                "delegation_id": persisted["delegation_id"],
                "state": persisted["state"],
                "idempotent_replay": True,
            }
        running = sum(
            1 for r in _records.values() if r.get("status") == "running"
        )
        if running >= max_async_children:
            _delete_durable_delegation(delegation_id)
            return {
                "status": "rejected",
                "error": (
                    f"Async delegation capacity reached ({max_async_children} "
                    f"running). Wait for one to finish (its result will re-enter "
                    f"the chat), or raise delegation.max_concurrent_children in "
                    f"config.yaml to allow more concurrent background units."
                ),
            }
        _records[delegation_id] = record

    executor = _get_executor(max_async_children)

    def _worker() -> None:
        combined: Dict[str, Any] = {}
        status = "error"
        try:
            combined = _run_with_lease(delegation_id, record["lease_seconds"], runner)
            # Batch status: completed unless every child errored/was interrupted.
            child_results = combined.get("results") or []
            child_statuses = [str(r.get("status") or "") for r in child_results]
            if child_statuses and all(value == "timeout" for value in child_statuses):
                status = "timeout"
            elif child_results and all(
                (r.get("status") not in ("completed", "success"))
                for r in child_results
            ):
                status = "error"
            else:
                status = "completed"
        except Exception as exc:  # noqa: BLE001 — must never crash the worker
            logger.exception("Async delegation batch %s crashed", delegation_id)
            combined = {
                "results": [],
                "error": f"{type(exc).__name__}: {exc}",
                "total_duration_seconds": round(time.time() - dispatched_at, 2),
            }
            status = "error"
        finally:
            _finalize_batch(delegation_id, combined, status)

    try:
        # Propagate the dispatching profile to the detached batch children.
        executor.submit(propagate_context_to_thread(_worker))
    except Exception as exc:  # pragma: no cover
        with _records_lock:
            _records.pop(delegation_id, None)
        _delete_durable_delegation(delegation_id)
        return {
            "status": "rejected",
            "error": f"Failed to schedule async delegation batch: {exc}",
        }

    logger.info(
        "Dispatched async delegation batch %s (%d task(s), session_key=%s)",
        delegation_id, n, session_key or "<cli>",
    )
    return {"status": "dispatched", "delegation_id": delegation_id}


def _finalize_batch(
    delegation_id: str, combined: Dict[str, Any], status: str
) -> None:
    """Mark a batch record complete and push ONE combined completion event."""
    with _records_lock:
        record = _records.get(delegation_id)
        if record is None:
            return
        record["status"] = "finalizing"
        record["completed_at"] = time.time()
        record["interrupt_fn"] = None
        event_record = dict(record)

    try:
        from tools.process_registry import process_registry
    except Exception as exc:  # pragma: no cover
        logger.error(
            "Async delegation batch %s finished but process_registry import "
            "failed; result lost: %s",
            delegation_id, exc,
        )
        return

    dispatched_at = event_record.get("dispatched_at") or time.time()
    completed_at = event_record.get("completed_at") or time.time()
    evt = {
        "type": "async_delegation",
        "delegation_id": delegation_id,
        "session_key": event_record.get("session_key", ""),
        "origin_ui_session_id": event_record.get("origin_ui_session_id", ""),
        "origin_session_id": event_record.get("origin_session_id", ""),
        "parent_session_id": event_record.get("parent_session_id"),
        "goal": event_record.get("goal", ""),
        "goals": event_record.get("goals"),
        "context": event_record.get("context"),
        "toolsets": event_record.get("toolsets"),
        "role": event_record.get("role"),
        "model": event_record.get("model"),
        "status": status,
        "is_batch": True,
        # The full per-task results list — the formatter renders a
        # consolidated multi-task block from this.
        "results": combined.get("results") or [],
        # Per-task live transcript log paths (cache/delegation/live/...).
        # They persist after completion and double as the full-fidelity
        # operational record of each child's run.
        "live_transcripts": combined.get("live_transcripts"),
        "error": combined.get("error"),
        "total_duration_seconds": combined.get("total_duration_seconds"),
        "dispatched_at": dispatched_at,
        "completed_at": completed_at,
    }
    _persist_completion(evt, combined)
    reason = _failure_reason(status, combined)
    if reason:
        _queue_escalation(delegation_id, reason)
        process_pending_escalations(delegation_id=delegation_id)
    _attach_escalation_to_event(evt)
    try:
        process_registry.completion_queue.put(evt)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "Async delegation batch %s: failed to enqueue completion event; "
            "result lost: %s",
            delegation_id, exc,
        )
    finally:
        with _records_lock:
            record = _records.get(delegation_id)
            if record is not None:
                record["status"] = status
            _prune_completed_locked()


def list_async_delegations() -> List[Dict[str, Any]]:
    """Snapshot of async delegations (running + recently completed).

    Safe to call from any thread. Excludes the non-serialisable interrupt_fn.
    """
    with _records_lock:
        return [
            {k: v for k, v in r.items() if k != "interrupt_fn"}
            for r in _records.values()
        ]


def interrupt_all(reason: str = "shutdown") -> int:
    """Signal every running async delegation to stop. Returns how many.

    Used on ``/stop`` and gateway shutdown so a dangling background subagent
    can't keep burning tokens with no one listening. The child still emits a
    completion event (status='interrupted') via the normal finalize path.
    """
    count = 0
    with _records_lock:
        targets = [
            r for r in _records.values() if r.get("status") == "running"
        ]
    for r in targets:
        fn = r.get("interrupt_fn")
        if callable(fn):
            try:
                fn()
                count += 1
            except Exception as exc:
                logger.debug(
                    "interrupt_all: %s interrupt failed: %s",
                    r.get("delegation_id"), exc,
                )
    if count:
        logger.info("Interrupted %d async delegation(s) (%s)", count, reason)
    return count


def interrupt_for_session(
    session_key: str = "",
    origin_ui_session_id: str = "",
    parent_session_id: str = "",
    reason: str = "session_end",
) -> int:
    """Signal running async delegations owned by ONE session to stop.

    A delegation's lifecycle is bound to the session that spawned it: when
    that session ends, its in-flight background subagents must end with it —
    a completed orphan would otherwise sit on the shared completion queue
    with no live owner, either leaking into another chat or burning tokens
    with no one listening (#55578).

    Selectors (any matching field claims the record):
    - ``origin_ui_session_id``: the live TUI tab/window that commissioned it.
    - ``session_key``: the durable routing key captured at dispatch.
    - ``parent_session_id``: the spawning agent's durable session-db id —
      the right selector for gateway chats, whose ``session_key`` (the
      platform conversation key) SURVIVES a ``/new`` reset while the
      session id rotates.

    Returns how many were interrupted.
    """
    if not session_key and not origin_ui_session_id and not parent_session_id:
        return 0
    count = 0
    with _records_lock:
        targets = [
            r for r in _records.values()
            if r.get("status") == "running"
            and (
                (origin_ui_session_id and str(r.get("origin_ui_session_id") or "") == origin_ui_session_id)
                or (session_key and str(r.get("session_key") or "") == session_key)
                or (parent_session_id and str(r.get("parent_session_id") or "") == parent_session_id)
            )
        ]
    for r in targets:
        fn = r.get("interrupt_fn")
        if callable(fn):
            try:
                fn()
                count += 1
            except Exception as exc:
                logger.debug(
                    "interrupt_for_session: %s interrupt failed: %s",
                    r.get("delegation_id"), exc,
                )
    if count:
        logger.info(
            "Interrupted %d async delegation(s) for ending session (%s)",
            count, reason,
        )
    return count


def _reset_for_tests() -> None:
    """Test-only: clear all state and tear down the executor."""
    global _executor, _executor_max_workers
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False)
        _executor = None
        _executor_max_workers = 0
    with _records_lock:
        _records.clear()
