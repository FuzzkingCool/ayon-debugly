#!/usr/bin/env python3
"""
Local Notion upload / multi-part test using repo-root .env.

Requires in .env:
  NOTION_API_KEY   — integration token (Bearer)
  NOTION_DB_ID     — database UUID, optionally ?v=<data_source_id>

Usage (from repo root, with venv that has requests + nxtools):
  python scripts/test_notion_upload.py

Optional:
  python scripts/test_notion_upload.py --no-issue   # only upload bytes (no DB row)
  python scripts/test_notion_upload.py --small-only # skip ~21 MiB multi-part test
  python scripts/test_notion_upload.py --chunk-session-only
      # local AYON addon upload_begin/chunk/complete assembly only (no token)

Reproduce production-like failing filenames (403 on …/file_uploads/…/send in client logs):
  python scripts/test_notion_upload.py --repro-failing-names
  python scripts/test_notion_upload.py --repro-failing-names --repro-attach-page
      # also create a test row and PATCH Attachments with successful uploads

Multipart here hits Notion directly (NOTION_SINGLE_PART_MAX_BYTES + 1). If that fails but
small .txt works, the integration or plan may block large/multi-part uploads. AYON HTTP 405
on upload_begin/append_upload_failures is a **server deploy** issue (routes not mounted);
this script does not call AYON for uploads.

Properties (Issue Type / Project / Pipeline) are verified with:
  python scripts/test_notion_properties.py --create --assert-properties \\
    --issue-type Bug --project MyGame --pipeline production
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Repo root: .../ayon-debugly
ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]


def _load_env_file(path: Path) -> None:
    """Minimal .env loader if python-dotenv is not installed."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ[key] = val


def _normalize_notion_uuid(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    s = s.split("?", 1)[0].split("&", 1)[0].strip()
    s = s.replace("-", "").lower()
    if len(s) != 32 or not all(c in "0123456789abcdef" for c in s):
        return ""
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"


def _run_chunk_session_test(log: logging.Logger) -> int:
    """Mirror client UPLOAD_CHUNK_BYTES (4 MiB) and >20 MiB total against upload_sessions."""
    import math

    from notion_upload_sessions import (  # noqa: E402
        MAX_FILE_BYTES,
        add_chunk,
        begin,
        complete,
    )

    chunk_bytes = 4 * 1024 * 1024
    target = min(21 * 1024 * 1024, MAX_FILE_BYTES - 1)
    blob = b"Z" * target
    n = max(1, math.ceil(len(blob) / float(chunk_bytes)))
    page_id = "00000000-0000-4000-8000-000000000001"
    fname = "debugly_chunk_session_test.bin"
    log.info(
        "AYON upload session: %s bytes in %d chunks of <= %s",
        len(blob),
        n,
        chunk_bytes,
    )
    b0 = begin(page_id, fname, len(blob), n)
    if not b0.get("success"):
        log.error("begin failed: %r", b0)
        return 10
    uid = b0["upload_id"]
    for i in range(n):
        start = i * chunk_bytes
        piece = blob[start : start + chunk_bytes]
        r = add_chunk(uid, i, piece)
        if not r.get("success"):
            log.error("add_chunk %s failed: %r", i, r)
            return 11
    done = complete(uid)
    if not done.get("success"):
        log.error("complete failed: %r", done)
        return 12
    got = done.get("file_bytes")
    if got != blob:
        log.error("assembled mismatch: got %s want %s", len(got or b""), len(blob))
        return 13
    log.info("OK chunk session id=%s... assembled=%s bytes", uid[:8], len(blob))
    del blob, got
    return 0


def _parse_notion_database_and_data_source_hint(raw: str) -> tuple[str, str | None]:
    raw = (raw or "").strip()
    if not raw:
        return "", None
    base = raw.split("?", 1)[0].split("&", 1)[0]
    ds_hint: str | None = None
    if "?" in raw:
        qs = raw.split("?", 1)[1]
        for part in qs.split("&"):
            part = part.strip()
            if part.lower().startswith("v="):
                ds_hint = _normalize_notion_uuid(part[2:])
                if not ds_hint:
                    ds_hint = None
                break
    db_id = _normalize_notion_uuid(base)
    return db_id, ds_hint


def _guess_notion_upload_content_type(filename: str) -> str:
    """Match server __init__._guess_notion_upload_content_type (no ayon_server import)."""
    import mimetypes

    fn = (filename or "").strip().lower()
    if fn.endswith(".txt"):
        return "text/plain"
    ct, _ = mimetypes.guess_type(filename or "")
    return ct or "application/octet-stream"


def _check_workspace_limits(log: logging.Logger, token: str) -> None:
    """GET /workspace to log max_file_upload_size_in_bytes."""
    import requests

    try:
        resp = requests.get(
            "https://api.notion.com/v1/workspace",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2026-03-11",
            },
            timeout=(10, 30),
        )
        if resp.status_code == 200:
            data = resp.json()
            limits = data.get("workspace_limits") or {}
            max_bytes = limits.get("max_file_upload_size_in_bytes")
            if max_bytes is not None:
                mib = max_bytes / (1024 * 1024)
                log.info(
                    "Workspace max_file_upload_size: %s bytes (%.1f MiB) — "
                    "free=5 MiB, paid=5 GiB",
                    max_bytes,
                    mib,
                )
                if max_bytes <= 5 * 1024 * 1024:
                    log.warning(
                        "FREE workspace detected (5 MiB limit); files > 5 MiB will 403"
                    )
            else:
                log.warning("GET /workspace returned no max_file_upload_size_in_bytes: %s", data)
        else:
            log.warning("GET /workspace HTTP %s: %s", resp.status_code, resp.text[:300])
    except Exception as e:
        log.warning("GET /workspace failed: %s", e)


def _run_repro_failing_names(
    log: logging.Logger,
    token: str,
    database_id: str,
    ds_hint: str | None,
    *,
    attach_page: bool,
) -> int:
    """Upload issue.txt / collected_data.txt / unity log name + one multipart .txt; log errors."""
    from notion_service import (  # noqa: E402
        NOTION_SINGLE_PART_MAX_BYTES,
        NotionService,
        upload_file_bytes_to_notion,
    )

    svc = NotionService(
        token=token,
        database_id=database_id,
        data_source_id_hint=ds_hint,
    )
    nv = svc.notion_version
    failed = 0
    ok_files: list[tuple[str, str]] = []  # (display_name, file_upload_id)

    cases: list[tuple[str, str, bytes]] = [
        (
            "issue.txt",
            _guess_notion_upload_content_type("issue.txt"),
            b'{"title":"repro","issue_type":"Bug","project":"MyGame"}\n',
        ),
        (
            "collected_data.txt",
            _guess_notion_upload_content_type("collected_data.txt"),
            (b'{"user":{"ayon_email":"repro@example.com"},"env":{}}\n' * 200),
        ),
        (
            "ayon_unity_debug_redacted.txt",
            _guess_notion_upload_content_type("ayon_unity_debug_redacted.txt"),
            b"UNITY_LOG_LINE " * (4096),  # ~64 KiB
        ),
    ]

    for fname, content_type, blob in cases:
        try:
            log.info(
                "Repro: POST file_uploads + send %r (%d bytes) content_type=%s",
                fname,
                len(blob),
                content_type,
            )
            fid = upload_file_bytes_to_notion(
                token=token,
                notion_version=nv,
                file_name=fname,
                content_type=content_type,
                file_bytes=blob,
                upload_timeout=300,
            )
            log.info("  OK file_upload id=%s...", fid[:8])
            ok_files.append((fname, fid))
        except Exception as e:
            log.error("  FAIL %r: %s", fname, e)
            log.error(
                "  403 diagnostics: if 'restricted_resource', check integration "
                "capabilities (insert_content) and workspace plan (GET /workspace). "
                "Full Notion error body is in the exception above."
            )
            failed += 1

    mp_name = f"debugly_repro_multipart_{int(time.time())}.txt"
    mp_size = NOTION_SINGLE_PART_MAX_BYTES + 1
    try:
        log.info(
            "Repro: multipart Notion upload %r (%d bytes) content_type=text/plain",
            mp_name,
            mp_size,
        )
        mp_blob = b"R" * mp_size
        fid = upload_file_bytes_to_notion(
            token=token,
            notion_version=nv,
            file_name=mp_name,
            content_type="text/plain",
            file_bytes=mp_blob,
            upload_timeout=600,
        )
        log.info("  OK file_upload id=%s...", fid[:8])
        ok_files.append((mp_name, fid))
        del mp_blob
    except Exception as e:
        log.error("  FAIL multipart %r: %s", mp_name, e)
        failed += 1

    if attach_page and ok_files:
        title = f"[Debugly repro attach] {time.strftime('%Y-%m-%d %H:%M:%S')}"
        log.info("Creating page for attach: %s", title)
        result = svc.submit_issue(
            title=title,
            user_message="scripts/test_notion_upload.py --repro-attach-page. Safe to delete.",
            collected_data={},
            tags=[],
            attachments_zip_b64=None,
            assignee_id="",
            async_attachments=False,
            issue_type="Bug",
            project="Studio",
            pipeline_release="production",
        )
        page_id = result.get("page_id") or ""
        if not page_id:
            log.error("submit_issue failed: %r", result)
            failed += 1
        else:
            files_payload = [
                {
                    "type": "file_upload",
                    "file_upload": {"id": fid},
                    "name": name,
                }
                for name, fid in ok_files
            ]
            log.info(
                "PATCH Attachments on page %s... (%d file(s))",
                page_id[:8],
                len(files_payload),
            )
            try:
                svc._update_page_attachments(page_id, files_payload)
                log.info("Done. url=%s", result.get("url"))
            except Exception as e:
                log.error("PATCH Attachments failed: %s", e)
                failed += 1

    if failed:
        log.error("Repro finished with %d failure(s) (see errors above)", failed)
        return 5
    log.info("Repro: all upload steps succeeded")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Notion single/multi-part uploads via .env")
    parser.add_argument(
        "--no-issue",
        action="store_true",
        help="Do not create a database row; only run upload_file_bytes_to_notion",
    )
    parser.add_argument(
        "--small-only",
        action="store_true",
        help="Skip multi-part test (no large in-memory blob)",
    )
    parser.add_argument(
        "--chunk-session-only",
        action="store_true",
        help="Only test in-memory AYON upload session assembly (~21 MiB, no Notion API)",
    )
    parser.add_argument(
        "--repro-failing-names",
        action="store_true",
        help="Upload issue.txt, collected_data.txt, ayon_unity_debug_redacted.txt + one "
        "multipart .txt via Notion API only (diagnose 403 on /file_uploads/.../send)",
    )
    parser.add_argument(
        "--repro-attach-page",
        action="store_true",
        help="With --repro-failing-names: create a test row and PATCH Attachments with "
        "successful file_upload ids",
    )
    args = parser.parse_args()

    if args.repro_attach_page and not args.repro_failing_names:
        print(
            "--repro-attach-page requires --repro-failing-names",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("test_notion_upload")

    if args.chunk_session_only:
        return _run_chunk_session_test(log)

    env_path = ROOT / ".env"
    if load_dotenv:
        load_dotenv(env_path)
    else:
        _load_env_file(env_path)
        log.info("python-dotenv not installed; parsed .env with minimal loader")

    token = (os.environ.get("NOTION_API_KEY") or "").strip()
    raw_db = (os.environ.get("NOTION_DB_ID") or "").strip()
    database_id, ds_hint = _parse_notion_database_and_data_source_hint(raw_db)

    if not token:
        log.error("NOTION_API_KEY missing in environment (set in .env or export)")
        return 1
    if not database_id:
        log.error("NOTION_DB_ID missing or invalid in environment")
        return 2

    _check_workspace_limits(log, token)

    if args.repro_failing_names:
        return _run_repro_failing_names(
            log,
            token,
            database_id,
            ds_hint,
            attach_page=args.repro_attach_page,
        )

    from notion_service import (  # noqa: E402
        NOTION_SINGLE_PART_MAX_BYTES,
        NotionService,
        upload_file_bytes_to_notion,
    )

    svc = NotionService(
        token=token,
        database_id=database_id,
        data_source_id_hint=ds_hint,
    )
    nv = svc.notion_version

    log.info("Database id %s... data_source hint=%s", database_id[:8], ds_hint[:8] if ds_hint else None)
    log.info("Notion-Version %s", nv)

    # --- Upload tests (orphan file_upload objects in workspace until attached or GC) ---
    small_name = f"debugly_upload_test_small_{int(time.time())}.txt"
    small_bytes = b"single_part hello from scripts/test_notion_upload.py\n"
    log.info("Single-part upload: %s (%d bytes)", small_name, len(small_bytes))
    small_id = upload_file_bytes_to_notion(
        token=token,
        notion_version=nv,
        file_name=small_name,
        content_type="text/plain",
        file_bytes=small_bytes,
        upload_timeout=120,
    )
    log.info("OK single_part file_upload id=%s...", small_id[:8])

    large_id = None
    large_name = ""
    if not args.small_only:
        large_size = NOTION_SINGLE_PART_MAX_BYTES + 1
        large_name = f"debugly_chunk_test_{int(time.time())}.bin"
        log.info(
            "Multi-part upload: %s (%d bytes, > %d)",
            large_name,
            large_size,
            NOTION_SINGLE_PART_MAX_BYTES,
        )
        large_bytes = b"Z" * large_size
        large_id = upload_file_bytes_to_notion(
            token=token,
            notion_version=nv,
            file_name=large_name,
            content_type="application/octet-stream",
            file_bytes=large_bytes,
            upload_timeout=600,
        )
        log.info("OK multi_part file_upload id=%s...", large_id[:8])
        del large_bytes

    if args.no_issue:
        log.info("--no-issue: skipping submit_issue and Attachments patch")
        return 0

    title = f"[Debugly upload test] {time.strftime('%Y-%m-%d %H:%M:%S')}"
    log.info("Creating issue: %s", title)
    result = svc.submit_issue(
        title=title,
        user_message="Automated upload test (scripts/test_notion_upload.py). Safe to delete.",
        collected_data={},
        tags=[],
        attachments_zip_b64=None,
        assignee_id="",
        async_attachments=False,
        issue_type="Bug",
        project="Studio",
        pipeline_release="production",
    )
    page_id = result.get("page_id") or ""
    page_url = result.get("url") or ""
    if not page_id:
        log.error("submit_issue returned no page_id: %r", result)
        return 3
    log.info("Created page %s... url=%s", page_id[:8], page_url)

    files_payload: list[dict] = [
        {
            "type": "file_upload",
            "file_upload": {"id": small_id},
            "name": small_name,
        },
    ]
    if large_id and large_name:
        files_payload.append(
            {
                "type": "file_upload",
                "file_upload": {"id": large_id},
                "name": large_name,
            }
        )

    log.info("Patching page Attachments with %d file(s)", len(files_payload))
    svc._update_page_attachments(page_id, files_payload)
    log.info("Done. Check Notion row: %s", page_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
