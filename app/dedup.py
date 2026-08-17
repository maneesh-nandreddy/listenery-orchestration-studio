from dataclasses import dataclass
from datetime import datetime

# Statuses that count as "this user already has an interview coming/sent" for
# dedup purposes. skipped_* rows never block a future send.
BLOCKING_STATUSES = ("sent", "pending")


@dataclass(frozen=True)
class DispatchRecord:
    id: str
    client_id: str
    user_id: str
    interview_id: str
    status: str
    created_at: datetime


def find_duplicate(
    candidates: list[DispatchRecord],
    client_id: str,
    user_id: str,
    interview_id: str,
    window_start: datetime,
) -> DispatchRecord | None:
    """Return the most recent prior dispatch that makes a new one a duplicate,
    or None if the new dispatch is allowed through.

    A duplicate is a dispatch for the same (client_id, user_id, interview_id),
    in a blocking status, created at or after `window_start`. Scoped strictly
    per client and per interview_id — a dispatch for a different client (even
    one that happens to reuse the same user_id and interview_id string) or a
    different interview never counts, however recent.
    """
    matches = [
        c
        for c in candidates
        if c.client_id == client_id
        and c.user_id == user_id
        and c.interview_id == interview_id
        and c.status in BLOCKING_STATUSES
        and c.created_at >= window_start
    ]
    if not matches:
        return None
    return max(matches, key=lambda c: c.created_at)
