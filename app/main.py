import secrets
import uuid

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_client
from app.db import get_db
from app.models import Client, Dispatch, Event, Rule
from app.schemas import (
    ClientCreate,
    ClientOut,
    DispatchOut,
    EventAccepted,
    EventIn,
    RuleCreate,
    RuleOut,
)

app = FastAPI(title="Listenery Event Trigger Engine")


@app.post("/events", response_model=EventAccepted, status_code=202)
def ingest_event(
    payload: EventIn,
    db: Session = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    event = Event(
        client_id=client.id,
        event_name=payload.event_name,
        user_id=payload.user_id,
        email=payload.email,
        phone=payload.phone,
        properties=payload.properties,
        event_timestamp=payload.timestamp,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # Import kept local so the ingest path never has to import Celery's
    # broker/config machinery unless a request actually arrives.
    from app.worker.tasks import process_event

    process_event.delay(str(event.id))

    return EventAccepted(event_id=str(event.id))


# --- Admin endpoints: unauthenticated, local-use-only helpers for exercising
# the system without touching the DB by hand (see README). ---


@app.post("/admin/clients", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    client = Client(name=payload.name, api_key=secrets.token_hex(16))
    db.add(client)
    db.commit()
    db.refresh(client)
    return ClientOut(id=str(client.id), name=client.name, api_key=client.api_key)


@app.post("/admin/rules", response_model=RuleOut)
def create_rule(payload: RuleCreate, db: Session = Depends(get_db)):
    client = db.get(Client, uuid.UUID(payload.client_id))
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    rule = Rule(
        client_id=client.id,
        event_name=payload.event_name,
        interview_id=payload.interview_id,
        delay_seconds=payload.delay_seconds,
        sample_percent=payload.sample_percent,
        dedup_window_seconds=payload.dedup_window_seconds,
        is_active=payload.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return RuleOut(
        id=str(rule.id),
        client_id=str(rule.client_id),
        event_name=rule.event_name,
        interview_id=rule.interview_id,
        delay_seconds=rule.delay_seconds,
        sample_percent=rule.sample_percent,
        dedup_window_seconds=rule.dedup_window_seconds,
        is_active=rule.is_active,
    )


@app.get("/dispatches", response_model=list[DispatchOut])
def list_dispatches(
    user_id: str | None = None,
    db: Session = Depends(get_db),
    client: Client = Depends(get_current_client),
):
    query = db.query(Dispatch).filter(Dispatch.client_id == client.id)
    if user_id:
        query = query.filter(Dispatch.user_id == user_id)
    dispatches = query.order_by(Dispatch.created_at.desc()).limit(200).all()

    return [
        DispatchOut(
            id=str(d.id),
            event_id=str(d.event_id),
            rule_id=str(d.rule_id),
            client_id=str(d.client_id),
            user_id=d.user_id,
            interview_id=d.interview_id,
            due_at=d.due_at,
            status=d.status.value,
            skip_reason=d.skip_reason,
            created_at=d.created_at,
            sent_at=d.sent_at,
        )
        for d in dispatches
    ]


@app.post("/admin/seed")
def seed_demo_data(db: Session = Depends(get_db)):
    from app.admin.seed import seed
    return seed(db)


from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
@app.get("/demo")
def get_demo():
    return FileResponse(os.path.join(static_dir, "index.html"))

