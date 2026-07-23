"""Local avatar file storage for provider photos."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile

ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
}

MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB


def uploads_root() -> Path:
    # nexhealth-backend/uploads
    return Path(__file__).resolve().parents[2] / "uploads"


def avatars_dir() -> Path:
    path = uploads_root() / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_avatar_upload(provider_id: uuid.UUID, upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()
    ext = ALLOWED_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise ValueError("Photo must be a JPG or PNG file.")

    data = await upload.read()
    if not data:
        raise ValueError("Empty file.")
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError("Photo must be 2 MB or smaller.")

    filename = f"{provider_id}_{uuid.uuid4().hex}{ext}"
    dest = avatars_dir() / filename
    dest.write_bytes(data)
    return f"/uploads/avatars/{filename}"


def delete_avatar_file(avatar_url: str | None) -> None:
    if not avatar_url or not avatar_url.startswith("/uploads/avatars/"):
        return
    path = uploads_root() / avatar_url.lstrip("/")
    if path.is_file():
        path.unlink(missing_ok=True)
