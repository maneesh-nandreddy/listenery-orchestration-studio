# Design Notes

## Approach

The pipeline is deliberately linear and stateless between steps, with
Postgres as the single durable record at every stage:

```
POST /events  ->  Event row (pending)  ->  [Celery] process_event
                                              -> match rules
                                              -> sample
                                              -> dedup
                                              -> Dispatch row (pending/skipped_*)
                                                     |
                                     [Celery beat, every N seconds]
                                              -> dispatch_due
                                              -> Dispatch rows past due_at
                                              -> send_interview() stub
                                              -> Dispatch row (sent/failed)
```

Every transition is a database write with an explicit status. Nothing about
"what happens next" lives only in a queue message or a Python variable.

## Key design decisions

### 1. Schedule state lives in Postgres, not Celery ETAs

This was the constraint I treated as non-negotiable. Celery supports
`apply_async(eta=...)`, which would have been the "obvious" way to implement
delay — but that ETA is held in the broker (Redis here), and if Redis loses
that data (restart without persistence, eviction, a botched failover) the
scheduled send simply vanishes with no record it ever existed.

Instead, `process_event` writes a `Dispatch` row with a concrete `due_at`
timestamp and `status = pending` as soon as a rule matches (immediately,
synchronously, in the same transaction as everything else in that function).
That row *is* the schedule. A separate Celery Beat task (`dispatch_due`)
runs every 10 seconds (configurable) and simply asks Postgres: "which pending
dispatches have `due_at <= now()`?" It has no memory of what it did last
tick — it doesn't need any. If the worker process dies, Redis is flushed, or
the whole stack is restarted, the next tick asks the same question and gets
the same correct answer, because the answer was never anywhere but Postgres.

The tradeoff is latency granularity (dispatches fire up to ~10s late, not
sub-second) and constant light polling load, both of which are the right
trade for this domain — a research interview going out 24h + 8s after the
target delay instead of exactly 24h is a non-issue.

`FOR UPDATE SKIP LOCKED` on the due-dispatch query means this also scales
horizontally to multiple worker processes without double-sending, for free.

### 2. Deterministic sampling via SHA-256, not `hash()`

`app/sampling.py` hashes `f"{rule_id}:{user_id}"` with `hashlib.sha256` and
takes the result mod 100 against the sample percentage. This is a pure
function with no I/O and no shared state, which is what makes it: (a)
trivially unit-testable, and (b) actually deterministic across restarts.

Python's builtin `hash()` on strings is deliberately randomized per process
(`PYTHONHASHSEED`) as a security mitigation. Using it here would have meant
a user could be in the 20% sample on one process and outside it on the next
— silently, with no error, and the bug would only surface as inexplicable
inconsistency days or weeks later. `tests/test_sampling.py` includes a
regression guard (`test_uses_sha256_not_builtin_hash`) that fails loudly if
`hash()` is ever called from this function.

Hashing `(rule_id, user_id)` together rather than just `user_id` means two
different rules with the same percentage make independent decisions about
the same user — required so that a 20% rule for "feature A feedback" and a
20% rule for "feature B feedback" don't happen to always agree.

### 3. Dedup logic is a pure function over data the DB already filtered

`app/dedup.py`'s `find_duplicate()` takes a list of candidate dispatches and
decides, in plain Python, whether a new one would be a duplicate. The
Postgres query that feeds it only does the cheap, indexed part (filter by
`client_id`, `user_id`, and a time-range on `created_at`); the exact business
rule — scoped per `interview_id`, only certain statuses count, which match
wins if several do — lives in code with no database dependency, so it's
unit-tested the same way as sampling: fast, deterministic, no fixtures.

Skipped dispatches (`skipped_sampled_out`, `skipped_duplicate`) never count
as blocking a future send — only `sent` and `pending` do. Every dispatch,
including the skipped ones, is a permanent row with a `skip_reason`, so
"why didn't this user get an interview" is always answerable by reading one
table, not by grepping logs.

**Caught by exercising the demo UI, not by the unit tests:** the first cut of
this matching logic scoped a duplicate by `(user_id, interview_id)` only —
no `client_id`. That's correct for a single tenant, but seeding the demo
workspace more than once creates multiple `Client` rows that (before a fix
to `seed.py`) all reused the literal string `"interview_churn_v1"`. A second
demo client's very first event for a user who happened to share a `user_id`
with an earlier demo client (e.g. the persona name `"dharma"`, reused by
every seed run) was wrongly suppressed as a duplicate of a *different
tenant's* dispatch. Fixed by adding `client_id` to both `DispatchRecord`
and the match criteria in `find_duplicate()`, and to the Postgres prefilter
and its supporting index. `tests/test_dedup.py` now has a regression test
(`test_dedup_scoped_per_client_even_with_same_user_and_interview_id`) for
exactly this case. The lesson: unit tests validated the dedup *algorithm*
correctly, but the multi-tenancy boundary was a design gap the tests never
would have caught because every test used a single implicit client — it
only surfaced from clicking through the actual app with real, repeated
seed data.

### 4. Sender is a `Protocol`, not an abstract base class

`app/sender.py` defines `Sender` as a `typing.Protocol` with one method,
`send_interview`. `LoggingSender` is the only implementation, and it just
logs a structured record and returns success. Swapping in a real provider
later means writing one class with one method and pointing `default_sender`
at it — no framework, no plugin registry, no premature abstraction.

## What was deliberately skipped or simplified

- **Retries/backoff on send failure.** `dispatch_due` marks a failed send as
  `status=failed` and stops; nothing retries it. A real version would need a
  retry count, backoff schedule, and a dead-letter path.
- **Idempotency keys on ingest.** `POST /events` will happily create two
  `Event` rows for the same logical event if the client double-sends (e.g.
  after a client-side timeout/retry). Each would independently go through
  matching, so a flaky client integration could produce duplicate sends
  faster than the dedup window catches them if they land far enough apart.
  Worth an `idempotency_key` unique constraint per client.
- **Per-client rate limiting on ingest.** Nothing stops one client from
  saturating the ingest endpoint or the worker queue. Fine for a take-home,
  not fine for shared infrastructure.
- **Observability/metrics.** Logging only, via the standard library logger.
  No latency histograms on ingest, no counters on match/sample/dedup
  outcomes, no alerting on a growing backlog of `pending` dispatches whose
  `due_at` has passed by an alarming margin (a real symptom of beat being
  down that today you'd only notice by querying the table).
- **Admin UI.** Two unauthenticated POST endpoints and a seed script, not a
  real rules management surface. No auth on `/admin/*` at all — acceptable
  for local demo, not for anything that leaves localhost.
- **Multiple sample_percent/dedup semantics per event type.** A user can
  match multiple rules for the same event (different interviews); each is
  sampled and deduped completely independently. That's intentional, but it
  means there's currently no cross-rule limit like "at most one interview
  invite per user per week regardless of which rule fired."
- **Event replay/backfill tooling.** If a rule's config changes, there's no
  mechanism to reprocess already-ingested `Event` rows against the new rule
  set. Each event is matched once, against whatever rules existed for its
  client/event_name at the moment `process_event` ran.

## What I'd do next with more time

1. Idempotency keys on `POST /events` (client-supplied, unique per client).
2. Retry/backoff + dead-letter handling in `dispatch_due` for failed sends.
3. Per-client rate limiting on ingest (token bucket in Redis, since Redis is
   already in the stack purely as a cache/broker).
4. Metrics: counts of dispatches by status per rule, and an alert on
   `pending` dispatches whose `due_at` is more than N minutes in the past
   (the direct symptom of beat/worker being stuck).
5. A real (auth-protected) admin surface for managing rules, since editing
   sampling/dedup config live is exactly the kind of thing a customer-facing
   team would need without engineering involvement.
