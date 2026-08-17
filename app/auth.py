from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Client


def get_current_client(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Client:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    api_key = authorization.removeprefix("Bearer ").strip()
    client = db.query(Client).filter(Client.api_key == api_key).first()
    if client is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return client
