from celery import Celery

from app.config import settings

celery_app = Celery(
    "listenery",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.beat_schedule = {
    "dispatch-due-every-tick": {
        "task": "app.worker.tasks.dispatch_due",
        "schedule": settings.dispatch_poll_interval_seconds,
    },
}

celery_app.autodiscover_tasks(["app.worker"])
