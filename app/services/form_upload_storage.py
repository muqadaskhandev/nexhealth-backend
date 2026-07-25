"""Local file storage for digitize-form uploads."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

MAX_FORM_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def uploads_root() -> Path:
    return Path(__file__).resolve().parents[2] / "uploads"


def form_uploads_dir() -> Path:
    path = uploads_root() / "form_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_form_upload(upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()
    ext = ALLOWED_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise ValueError("File must be a PDF, JPG, PNG, DOC, or DOCX.")

    data = await upload.read()
    if not data:
        raise ValueError("Empty file.")
    if len(data) > MAX_FORM_UPLOAD_BYTES:
        raise ValueError("File must be 10 MB or smaller.")

    filename = f"{uuid.uuid4().hex}{ext}"
    dest = form_uploads_dir() / filename
    dest.write_bytes(data)
    return f"/uploads/form_uploads/{filename}"
