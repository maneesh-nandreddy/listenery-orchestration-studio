import hashlib

# Deterministic per-(rule_id, user_id) sampling.
#
# Python's built-in hash() is randomly salted per process (PYTHONHASHSEED) for
# strings, so the same input produces different results across restarts and
# machines. That would silently break the "same user always lands on the same
# side of the cut" requirement. We use sha256 instead, which is stable
# everywhere, forever.


def _bucket(rule_id: str, user_id: str) -> int:
    """Map (rule_id, user_id) to a stable integer in [0, 100)."""
    digest = hashlib.sha256(f"{rule_id}:{user_id}".encode("utf-8")).digest()
    # First 8 bytes as an unsigned int is plenty of entropy for a mod-100 bucket.
    value = int.from_bytes(digest[:8], byteorder="big")
    return value % 100


def is_sampled_in(rule_id: str, user_id: str, percent: int) -> bool:
    """True if this user falls inside `percent`% for this rule.

    Deterministic: same (rule_id, user_id, percent) always returns the same
    result, regardless of process, machine, or restarts.
    """
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    return _bucket(rule_id, user_id) < percent
