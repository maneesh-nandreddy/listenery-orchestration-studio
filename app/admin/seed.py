"""One-shot local seed script: creates a demo Client and a couple of Rules
so the system can be exercised end-to-end without hand-editing the DB.

Run with: python -m app.admin.seed
"""

import secrets

from app.db import SessionLocal
from app.models import Client, Rule


def seed(db) -> dict:
    client = Client(name="Demo Co", api_key=secrets.token_hex(16))
    db.add(client)
    db.flush()

    # Suffix interview_ids per seed run so repeated seeding (e.g. clicking
    # "Seed Workspace" more than once in the demo UI) always creates a fully
    # independent workspace, even though dedup is now correctly scoped by
    # client_id regardless.
    suffix = secrets.token_hex(3)

    immediate_rule = Rule(
        client_id=client.id,
        event_name="user_churned",
        interview_id=f"interview_churn_v1_{suffix}",
        delay_seconds=0,
        sample_percent=100,
        dedup_window_seconds=86400,
    )
    delayed_sampled_rule = Rule(
        client_id=client.id,
        event_name="feature_tried",
        interview_id=f"interview_feature_feedback_v1_{suffix}",
        delay_seconds=86400,  # 24 hours
        sample_percent=20,
        dedup_window_seconds=30 * 86400,  # 30 days
    )
    db.add_all([immediate_rule, delayed_sampled_rule])
    db.commit()

    return {
        "client_id": str(client.id),
        "api_key": client.api_key,
        "rules": [str(immediate_rule.id), str(delayed_sampled_rule.id)],
    }


def main() -> None:
    db = SessionLocal()
    try:
        res = seed(db)
        print(f"client_id: {res['client_id']}")
        print(f"api_key:   {res['api_key']}")
        print(f"rules: {res['rules']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

