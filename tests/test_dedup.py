from datetime import datetime, timedelta, timezone

from freezegun import freeze_time

from app.dedup import DispatchRecord, find_duplicate

NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


def _window_start(seconds: int) -> datetime:
    return NOW - timedelta(seconds=seconds)


def _record(**overrides):
    defaults = dict(
        id="d1",
        client_id="client-1",
        user_id="user-1",
        interview_id="interview-a",
        status="sent",
        created_at=NOW - timedelta(hours=1),
    )
    defaults.update(overrides)
    return DispatchRecord(**defaults)


@freeze_time(NOW)
def test_second_event_inside_window_is_suppressed():
    window_seconds = 86400
    prior = _record()
    duplicate = find_duplicate(
        [prior],
        client_id="client-1",
        user_id="user-1",
        interview_id="interview-a",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is prior


@freeze_time(NOW)
def test_event_outside_window_is_allowed_through():
    window_seconds = 86400
    prior = _record(created_at=NOW - timedelta(days=2))  # older than the 24h window
    duplicate = find_duplicate(
        [prior],
        client_id="client-1",
        user_id="user-1",
        interview_id="interview-a",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is None


@freeze_time(NOW)
def test_dedup_scoped_per_interview_not_globally_per_user():
    window_seconds = 86400
    prior = _record()
    # Same client and user, different interview, well within the window ->
    # must NOT be treated as a duplicate.
    duplicate = find_duplicate(
        [prior],
        client_id="client-1",
        user_id="user-1",
        interview_id="interview-b",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is None


@freeze_time(NOW)
def test_dedup_scoped_per_user_not_globally_per_interview():
    window_seconds = 86400
    prior = _record()
    duplicate = find_duplicate(
        [prior],
        client_id="client-1",
        user_id="user-2",
        interview_id="interview-a",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is None


@freeze_time(NOW)
def test_dedup_scoped_per_client_even_with_same_user_and_interview_id():
    # Regression test: two different clients/tenants whose rules happen to
    # reuse the same interview_id string (e.g. both seeded from the same
    # demo script) and the same user_id must NOT dedup against each other.
    # Caught live: repeatedly seeding the demo workspace created multiple
    # clients all using the hardcoded interview_id "interview_churn_v1",
    # and a fresh client's first-ever event was wrongly suppressed as a
    # duplicate of a different client's prior dispatch.
    window_seconds = 86400
    prior = _record(client_id="client-1")
    duplicate = find_duplicate(
        [prior],
        client_id="client-2",
        user_id="user-1",
        interview_id="interview-a",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is None


@freeze_time(NOW)
def test_skipped_statuses_never_block_a_new_dispatch():
    window_seconds = 86400
    prior = _record(status="skipped_sampled_out")
    duplicate = find_duplicate(
        [prior],
        client_id="client-1",
        user_id="user-1",
        interview_id="interview-a",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is None


@freeze_time(NOW)
def test_boundary_at_exactly_window_edge_counts_as_inside():
    window_seconds = 86400
    prior = _record(created_at=_window_start(window_seconds))  # exactly at the edge
    duplicate = find_duplicate(
        [prior],
        client_id="client-1",
        user_id="user-1",
        interview_id="interview-a",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is prior


@freeze_time(NOW)
def test_returns_most_recent_match_when_multiple_exist():
    window_seconds = 86400
    older = _record(id="d1", created_at=NOW - timedelta(hours=5))
    newer = _record(id="d2", status="pending", created_at=NOW - timedelta(hours=1))
    duplicate = find_duplicate(
        [older, newer],
        client_id="client-1",
        user_id="user-1",
        interview_id="interview-a",
        window_start=_window_start(window_seconds),
    )
    assert duplicate is newer
