"""Local logo file storage for practice branding."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile

ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
}

MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


def uploads_root() -> Path:
    # nexhealth-backend/uploads
    return Path(__file__).resolve().parents[2] / "uploads"


def logos_dir() -> Path:
    path = uploads_root() / "logos"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_logo_upload(location_id: uuid.UUID, upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()
    ext = ALLOWED_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise ValueError("Logo must be a JPG or PNG file.")

    data = await upload.read()
    if not data:
        raise ValueError("Empty file.")
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("Logo must be 2 MB or smaller.")

    filename = f"{location_id}_{uuid.uuid4().hex}{ext}"
    dest = logos_dir() / filename
    dest.write_bytes(data)
    return f"/uploads/logos/{filename}"


def delete_logo_file(logo_url: str | None) -> None:
    if not logo_url or not logo_url.startswith("/uploads/logos/"):
        return
    path = uploads_root() / logo_url.lstrip("/")
    if path.is_file():
        path.unlink(missing_ok=True)
