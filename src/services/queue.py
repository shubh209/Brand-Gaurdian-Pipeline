"""
Job queue provider seam — enqueue / receive / delete by QUEUE_BACKEND.

Postgres-backed is the live backend, replacing the Azure Storage Queue. Preserves the
same semantics the worker relied on:
  - receive() claims a job INVISIBLY for `visibility_timeout` seconds (sets claimed_until)
  - delete() removes it on success
  - a claimed job whose worker died reappears once claimed_until passes (redelivery)

Concurrency-safe via SELECT ... FOR UPDATE SKIP LOCKED — two workers never grab the
same row.

ponytail: polling queue on Postgres. Ceiling: poll latency + no fan-out/priorities.
Upgrade trigger: if throughput/latency degrades under real traffic, put a managed queue
(SQS/Service Bus/Redis) behind this same seam — do NOT rewrite callers.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.config import config
from src.db.session import SessionLocal


@dataclass
class QueueMessage:
    id: str          # opaque handle passed back to delete()
    body: dict       # the job payload


def enqueue(payload: dict) -> str:
    """Add a job. Returns the job id."""
    if config.QUEUE_BACKEND != "postgres":
        raise ValueError(f"Unsupported QUEUE_BACKEND: {config.QUEUE_BACKEND!r}")
    db = SessionLocal()
    try:
        row = db.execute(
            text("INSERT INTO audit_jobs (payload) VALUES (:p) RETURNING id"),
            {"p": json.dumps(payload)},
        ).fetchone()
        db.commit()
        return str(row[0])
    finally:
        db.close()


def receive(visibility_timeout: int = 600) -> QueueMessage | None:
    """Claim the oldest visible job for `visibility_timeout` seconds. None if queue empty.

    A job is 'visible' when claimed_until is NULL or in the past. Claiming sets
    claimed_until into the future so other workers skip it.
    """
    now = datetime.now(timezone.utc)
    until = now + timedelta(seconds=visibility_timeout)
    db = SessionLocal()
    try:
        # FOR UPDATE SKIP LOCKED: atomically pick one visible row no other tx holds.
        row = db.execute(
            text(
                """
                SELECT id, payload FROM audit_jobs
                WHERE claimed_until IS NULL OR claimed_until < :now
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ),
            {"now": now},
        ).fetchone()
        if row is None:
            db.commit()
            return None
        job_id, payload = row[0], row[1]
        db.execute(
            text("UPDATE audit_jobs SET claimed_until = :until WHERE id = :id"),
            {"until": until, "id": job_id},
        )
        db.commit()
        body = payload if isinstance(payload, dict) else json.loads(payload)
        return QueueMessage(id=str(job_id), body=body)
    finally:
        db.close()


def delete(message_id: str) -> None:
    """Remove a job after successful processing."""
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM audit_jobs WHERE id = :id"), {"id": message_id})
        db.commit()
    finally:
        db.close()
