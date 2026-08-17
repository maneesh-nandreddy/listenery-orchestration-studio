import enum
import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    ForeignKey,
    DateTime,
    Enum,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db import Base


def uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class ProcessingStatus(str, enum.Enum):
    pending = "pending"
    processed = "processed"
    failed = "failed"


class DispatchStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    skipped_sampled_out = "skipped_sampled_out"
    skipped_duplicate = "skipped_duplicate"
    failed = "failed"


class Client(Base):
    __tablename__ = "clients"

    id = uuid_pk()
    name = Column(String, nullable=False)
    api_key = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rules = relationship("Rule", back_populates="client")


class Rule(Base):
    __tablename__ = "rules"

    id = uuid_pk()
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    event_name = Column(String, nullable=False, index=True)
    interview_id = Column(String, nullable=False)
    delay_seconds = Column(Integer, nullable=False, default=0)
    sample_percent = Column(Integer, nullable=False, default=100)
    dedup_window_seconds = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="rules")

    __table_args__ = (
        Index("ix_rules_client_event_active", "client_id", "event_name", "is_active"),
    )


class Event(Base):
    __tablename__ = "events"

    id = uuid_pk()
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    event_name = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    properties = Column(JSONB, nullable=False, default=dict)
    event_timestamp = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    processing_status = Column(
        Enum(ProcessingStatus, name="processing_status"),
        nullable=False,
        default=ProcessingStatus.pending,
    )


class Dispatch(Base):
    __tablename__ = "dispatches"

    id = uuid_pk()
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    user_id = Column(String, nullable=False, index=True)
    interview_id = Column(String, nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(
        Enum(DispatchStatus, name="dispatch_status"),
        nullable=False,
        default=DispatchStatus.pending,
        index=True,
    )
    skip_reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dispatches_status_due_at", "status", "due_at"),
        Index(
            "ix_dispatches_client_user_interview_created",
            "client_id",
            "user_id",
            "interview_id",
            "created_at",
        ),
    )
