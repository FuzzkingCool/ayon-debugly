"""In-memory chunked upload sessions for Notion attachments (AYON → assemble → Notion)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

try:
    from nxtools import logging as log
except ImportError:
    import logging

    log = logging.getLogger(__name__)

MAX_FILE_BYTES = 100 * 1024 * 1024
SESSION_TTL_SEC = 3600
_MAX_SESSIONS = 500


@dataclass
class UploadSession:
    upload_id: str
    page_id: str
    filename: str
    file_size: int
    total_chunks: int
    chunks: Dict[int, bytes] = field(default_factory=dict)
    created: float = field(default_factory=time.time)


_lock = threading.Lock()
_sessions: Dict[str, UploadSession] = {}


def _cleanup_unlocked(now: float) -> None:
    if len(_sessions) <= _MAX_SESSIONS:
        # Still drop expired
        expired = [
            uid
            for uid, s in _sessions.items()
            if now - s.created > SESSION_TTL_SEC
        ]
        for uid in expired:
            _sessions.pop(uid, None)
        return
    # Too many: remove oldest first
    items = sorted(_sessions.items(), key=lambda x: x[1].created)
    while len(_sessions) > _MAX_SESSIONS and items:
        uid, _ = items.pop(0)
        _sessions.pop(uid, None)
    for uid in list(_sessions.keys()):
        if now - _sessions[uid].created > SESSION_TTL_SEC:
            _sessions.pop(uid, None)


def begin(
    page_id: str, filename: str, file_size: int, total_chunks: int
) -> dict[str, Any]:
    if file_size < 0 or file_size > MAX_FILE_BYTES:
        return {
            "error": f"file_size must be 0..{MAX_FILE_BYTES} bytes",
        }
    if total_chunks < 1 or total_chunks > 10000:
        return {"error": "total_chunks must be 1..10000"}
    uid = str(uuid.uuid4())
    with _lock:
        _cleanup_unlocked(time.time())
        _sessions[uid] = UploadSession(
            upload_id=uid,
            page_id=page_id.strip(),
            filename=filename,
            file_size=file_size,
            total_chunks=total_chunks,
        )
    log.debug(
        "Notion upload session begin id=%s... file=%s size=%s chunks=%s",
        uid[:8],
        filename,
        file_size,
        total_chunks,
    )
    return {"success": True, "upload_id": uid}


def add_chunk(
    upload_id: str, chunk_index: int, chunk_bytes: bytes
) -> dict[str, Any]:
    if not upload_id or chunk_index < 0:
        return {"error": "invalid upload_id or chunk_index"}
    with _lock:
        _cleanup_unlocked(time.time())
        sess = _sessions.get(upload_id)
        if not sess:
            return {"error": "upload session not found or expired"}
        if chunk_index >= sess.total_chunks:
            return {"error": "chunk_index out of range"}
        if chunk_index in sess.chunks:
            return {"error": "duplicate chunk_index"}
        sess.chunks[chunk_index] = chunk_bytes
        received = len(sess.chunks)
    return {
        "success": True,
        "received_chunks": received,
        "total_chunks": sess.total_chunks,
    }


def complete(upload_id: str) -> dict[str, Any]:
    with _lock:
        _cleanup_unlocked(time.time())
        sess = _sessions.pop(upload_id, None)
    if not sess:
        return {"error": "upload session not found or expired"}
    if len(sess.chunks) != sess.total_chunks:
        return {
            "error": f"missing chunks: have {len(sess.chunks)}/{sess.total_chunks}",
        }
    parts: list[bytes] = []
    for i in range(sess.total_chunks):
        b = sess.chunks.get(i)
        if b is None:
            return {"error": f"missing chunk {i}"}
        parts.append(b)
    blob = b"".join(parts)
    if len(blob) != sess.file_size:
        return {
            "error": f"assembled size {len(blob)} != declared {sess.file_size}",
        }
    log.debug(
        "Notion upload session complete id=%s... assembled=%s",
        upload_id[:8],
        len(blob),
    )
    return {
        "success": True,
        "page_id": sess.page_id,
        "filename": sess.filename,
        "file_bytes": blob,
    }
