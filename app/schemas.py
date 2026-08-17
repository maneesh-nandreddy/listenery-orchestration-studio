from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_name: str
    user_id: str
    email: str | None = None
    phone: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class EventAccepted(BaseModel):
    event_id: str
    status: str = "accepted"


class ClientCreate(BaseModel):
    name: str


class ClientOut(BaseModel):
    id: str
    name: str
    api_key: str


class RuleCreate(BaseModel):
    client_id: str
    event_name: str
    interview_id: str
    delay_seconds: int = 0
    sample_percent: int = Field(default=100, ge=0, le=100)
    dedup_window_seconds: int = 0
    is_active: bool = True


class RuleOut(BaseModel):
    id: str
    client_id: str
    event_name: str
    interview_id: str
    delay_seconds: int
    sample_percent: int
    dedup_window_seconds: int
    is_active: bool


class DispatchOut(BaseModel):
    id: str
    event_id: str
    rule_id: str
    client_id: str
    user_id: str
    interview_id: str
    due_at: datetime
    status: str
    skip_reason: str | None
    created_at: datetime
    sent_at: datetime | None
