"""Viewer-safe public profiles addressed by reserved handles."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProfileHandle
from app.db.session import get_db
from app.services.profiles import handle_key, public_profile_payload

router = APIRouter(prefix="/profiles", tags=["profiles"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/{handle}")
def get_public_profile(handle: str, db: DbSession):
    try:
        key = handle_key(handle)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        ) from None
    historical = db.scalar(select(ProfileHandle).where(ProfileHandle.handle_key == key))
    if historical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    current = db.scalar(
        select(ProfileHandle).where(
            ProfileHandle.user_id == historical.user_id,
            ProfileHandle.is_current.is_(True),
        )
    )
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    if historical.id != current.id or handle != current.display_handle:
        return RedirectResponse(
            url=f"/api/profiles/{quote(current.display_handle)}",
            status_code=status.HTTP_308_PERMANENT_REDIRECT,
        )
    payload = public_profile_payload(db, user_id=current.user_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return payload
