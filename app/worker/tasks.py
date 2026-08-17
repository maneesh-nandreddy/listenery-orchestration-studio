import uuid
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.dedup import DispatchRecord, find_duplicate
from app.models import Dispatch, DispatchStatus, Event, ProcessingStatus, Rule
from app.sampling import is_sampled_in
from app.sender import default_sender
from app.worker.celery_app import celery_app


@celery_app.task(name="app.worker.tasks.process_event")
def process_event(event_id: str) -> None:
    """Match an ingested Event against its client's rules, then sample and
    dedup each match into a Dispatch row. This is the only place Dispatch
    rows get created — the ingest request path never touches this logic.
    """
    db = SessionLocal()
    try:
        event = db.get(Event, uuid.UUID(event_id))
        if event is None:
            return

        rules = (
            db.query(Rule)
            .filter(
                Rule.client_id == event.client_id,
                Rule.event_name == event.event_name,
                Rule.is_active.is_(True),
            )
            .all()
        )

        for rule in rules:
            due_at = event.event_timestamp + timedelta(seconds=rule.delay_seconds)

            if not is_sampled_in(str(rule.id), event.user_id, rule.sample_percent):
                db.add(
                    Dispatch(
                        event_id=event.id,
                        rule_id=rule.id,
                        client_id=event.client_id,
                        user_id=event.user_id,
                        interview_id=rule.interview_id,
                        due_at=due_at,
                        status=DispatchStatus.skipped_sampled_out,
                        skip_reason=f"user not selected by sample_percent={rule.sample_percent}",
                    )
                )
                continue

            if rule.dedup_window_seconds > 0:
                window_start = datetime.now(timezone.utc) - timedelta(
                    seconds=rule.dedup_window_seconds
                )
                # Coarse, indexed prefilter in Postgres (by client_id, user_id
                # and time range only); the exact interview-scoped,
                # status-scoped comparison lives in the pure `find_duplicate`
                # function so it's unit-testable without a database.
                candidates = (
                    db.query(Dispatch)
                    .filter(
                        Dispatch.client_id == event.client_id,
                        Dispatch.user_id == event.user_id,
                        Dispatch.created_at >= window_start,
                    )
                    .all()
                )
                existing = find_duplicate(
                    [
                        DispatchRecord(
                            id=str(c.id),
                            client_id=str(c.client_id),
                            user_id=c.user_id,
                            interview_id=c.interview_id,
                            status=c.status.value,
                            created_at=c.created_at,
                        )
                        for c in candidates
                    ],
                    client_id=str(event.client_id),
                    user_id=event.user_id,
                    interview_id=rule.interview_id,
                    window_start=window_start,
                )
                if existing is not None:
                    db.add(
                        Dispatch(
                            event_id=event.id,
                            rule_id=rule.id,
                            client_id=event.client_id,
                            user_id=event.user_id,
                            interview_id=rule.interview_id,
                            due_at=due_at,
                            status=DispatchStatus.skipped_duplicate,
                            skip_reason=(
                                f"duplicate of dispatch {existing.id} within "
                                f"{rule.dedup_window_seconds}s dedup window"
                            ),
                        )
                    )
                    continue

            db.add(
                Dispatch(
                    event_id=event.id,
                    rule_id=rule.id,
                    client_id=event.client_id,
                    user_id=event.user_id,
                    interview_id=rule.interview_id,
                    due_at=due_at,
                    status=DispatchStatus.pending,
                )
            )

        event.processing_status = ProcessingStatus.processed
        db.commit()
    except Exception:
        db.rollback()
        event = db.get(Event, uuid.UUID(event_id))
        if event is not None:
            event.processing_status = ProcessingStatus.failed
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="app.worker.tasks.dispatch_due")
def dispatch_due() -> int:
    """Periodic beat task: poll Postgres for pending dispatches whose due_at
    has passed, and fire the sender stub for each.

    Postgres — not Celery ETAs, not an in-memory scheduler — is the source of
    truth for "what's due and when". If this worker or Redis restarts, the
    next tick simply re-queries `due_at <= now()` and picks up exactly where
    it left off. `FOR UPDATE SKIP LOCKED` lets multiple worker processes run
    this same task concurrently without double-sending.
    """
    db = SessionLocal()
    sent_count = 0
    try:
        now = datetime.now(timezone.utc)
        due = (
            db.query(Dispatch)
            .filter(Dispatch.status == DispatchStatus.pending, Dispatch.due_at <= now)
            .with_for_update(skip_locked=True)
            .all()
        )

        for dispatch in due:
            event = db.get(Event, dispatch.event_id)
            contact = (event.email or event.phone) if event else None

            result = default_sender.send_interview(
                client_id=str(dispatch.client_id),
                user_id=dispatch.user_id,
                contact=contact or "",
                interview_id=dispatch.interview_id,
                timestamp=now,
            )

            if result.success:
                dispatch.status = DispatchStatus.sent
                dispatch.sent_at = now
                sent_count += 1
            else:
                dispatch.status = DispatchStatus.failed
                dispatch.skip_reason = result.detail

        db.commit()
        return sent_count
    finally:
        db.close()
