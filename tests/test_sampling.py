from app.sampling import is_sampled_in


def test_same_input_is_deterministic_across_calls():
    results = {is_sampled_in("rule-1", "user-42", 50) for _ in range(1000)}
    assert len(results) == 1


def test_same_input_deterministic_fresh_import():
    # Simulates a process restart: re-derive the answer from scratch with no
    # shared state, and it must still agree with a prior call.
    first = is_sampled_in("rule-1", "user-42", 37)
    import importlib

    import app.sampling as sampling_module

    importlib.reload(sampling_module)
    second = sampling_module.is_sampled_in("rule-1", "user-42", 37)
    assert first == second


def test_boundary_percentages():
    for user_id in ("a", "b", "c", "d", "e"):
        assert is_sampled_in("rule-x", user_id, 100) is True
        assert is_sampled_in("rule-x", user_id, 0) is False


def test_distribution_roughly_matches_percent():
    n = 10_000
    for percent in (10, 20, 50, 80):
        count_in = sum(
            1 for i in range(n) if is_sampled_in("rule-dist", f"user-{i}", percent)
        )
        observed_pct = 100 * count_in / n
        # generous tolerance: this is a statistical check, not an exact one
        assert abs(observed_pct - percent) < 3, (
            f"percent={percent} observed={observed_pct}"
        )


def test_different_rules_give_independent_buckets_for_same_user():
    # If sampling only hashed on user_id, every rule would agree on the same
    # users for a given percent. Assert that's not the case.
    user_ids = [f"user-{i}" for i in range(2000)]
    bucket_a = {u for u in user_ids if is_sampled_in("rule-a", u, 50)}
    bucket_b = {u for u in user_ids if is_sampled_in("rule-b", u, 50)}

    assert bucket_a != bucket_b
    # Two independent ~50% coin flips over the same population should overlap
    # somewhere between roughly 1/4 (independent) and not be identical/disjoint.
    overlap = len(bucket_a & bucket_b)
    assert 0.15 * len(user_ids) < overlap < 0.35 * len(user_ids)


def test_uses_sha256_not_builtin_hash(monkeypatch):
    # Guard against regressions to Python's salted builtin hash().
    calls = []
    real_hash = hash

    def spy_hash(value):
        calls.append(value)
        return real_hash(value)

    monkeypatch.setattr("builtins.hash", spy_hash)
    is_sampled_in("rule-1", "user-1", 50)
    assert calls == []
