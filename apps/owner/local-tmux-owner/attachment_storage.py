"""Bounded attachment type detection, retention, and storage."""

from __future__ import annotations

import datetime as dt
from http import HTTPStatus
from pathlib import Path
import secrets
import shutil
from typing import Any


DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
DEFAULT_RETENTION_DAYS = 7
IMAGE_MIME_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}
DOCUMENT_MIME_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/rtf": ".rtf",
}
ALLOWED_ATTACHMENT_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".odt", ".odp", ".ods", ".md", ".txt", ".csv", ".json", ".rtf",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}


class AttachmentStorageError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status


def attachment_suffix(filename: str | None, content_type: str | None, data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"heif", b"mif1", b"msf1"}:
        return ".heic"
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    mime_suffix = IMAGE_MIME_SUFFIXES.get(mime) or DOCUMENT_MIME_SUFFIXES.get(mime)
    if mime_suffix:
        return mime_suffix
    suffix = Path(filename or "").suffix.lower()
    if suffix in ALLOWED_ATTACHMENT_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    raise AttachmentStorageError("unsupported attachment type; use image, pdf, office, md, txt, csv, or json")


def cleanup_old_uploads(root: Path, *, retention_days: int = DEFAULT_RETENTION_DAYS, today: dt.date | None = None) -> None:
    cutoff = (today or dt.datetime.now().date()) - dt.timedelta(days=max(1, retention_days) - 1)
    try:
        children = list(root.iterdir())
    except FileNotFoundError:
        return
    for child in children:
        if not child.is_dir():
            continue
        try:
            day = dt.date.fromisoformat(child.name)
        except ValueError:
            continue
        if day < cutoff:
            try:
                shutil.rmtree(child)
            except OSError:
                pass


def save_uploaded_attachment(
    file_item: Any,
    root: Path,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: dt.datetime | None = None,
) -> tuple[Path, int, str]:
    filename = Path(getattr(file_item, "filename", "") or "attachment").name
    file_obj = getattr(file_item, "file", None)
    if file_obj is None:
        raise AttachmentStorageError("missing attachment file")
    data = file_obj.read(max_bytes + 1)
    if not data:
        raise AttachmentStorageError("empty attachment")
    if len(data) > max_bytes:
        raise AttachmentStorageError("attachment too large; max 25 MB", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    suffix = attachment_suffix(filename, getattr(file_item, "type", None), data)
    current = now or dt.datetime.now()
    cleanup_old_uploads(root, retention_days=retention_days, today=current.date())
    target_dir = root / current.strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = current.strftime("%Y%m%d-%H%M%S")
    for _ in range(10):
        path = target_dir / f"{stamp}-{secrets.token_hex(3)}{suffix}"
        try:
            with path.open("xb") as handle:
                handle.write(data)
            return path, len(data), "image" if suffix in IMAGE_SUFFIXES else "file"
        except FileExistsError:
            continue
    raise AttachmentStorageError("failed to allocate attachment path", HTTPStatus.INTERNAL_SERVER_ERROR)
