import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

logger = logging.getLogger("listenery.sender")


@dataclass
class SendResult:
    success: bool
    detail: str = ""


class Sender(Protocol):
    def send_interview(
        self,
        client_id: str,
        user_id: str,
        contact: str,
        interview_id: str,
        timestamp: datetime,
    ) -> SendResult:
        ...


class LoggingSender:
    """Stub sender: logs a structured payload instead of calling a real provider."""

    def send_interview(
        self,
        client_id: str,
        user_id: str,
        contact: str,
        interview_id: str,
        timestamp: datetime,
    ) -> SendResult:
        logger.info(
            "send_interview",
            extra={
                "client_id": client_id,
                "user_id": user_id,
                "contact": contact,
                "interview_id": interview_id,
                "timestamp": timestamp.isoformat(),
            },
        )
        return SendResult(success=True, detail="logged (stub sender)")


default_sender: Sender = LoggingSender()
