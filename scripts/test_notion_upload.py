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
  python scripts/test_notion_upload.py --list-entries-only
      # offline check of list_zip_attach_entries member selection (no token/network)
  python scripts/test_notion_upload.py --probe-upload-hosts
      # POST file_uploads only; log raw vs resolved send_host (run on AYON server)

Reproduce production-like failing filenames (403 on …/file_uploads/…/send in client logs):
  python scripts/test_notion_upload.py --repro-failing-names
  python scripts/test_notion_upload.py --repro-failing-names --repro-attach-page
      # also create a test row and PATCH Attachments with successful uploads

Multipart here hits Notion directly (NOTION_SINGLE_PART_MAX_BYTES + 1). If that fails but
small .txt works, the integration or plan may block large/multi-part uploads. The client
sends the whole report ZIP to the server in one notion/attach_bundle request; AYON HTTP 405
on that route is a **server deploy** issue (route not mounted). This script does not call
AYON for uploads except --list-entries-only (which is pure/offline).

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


def _count_page_attachments(
    token: str, page_id: str, notion_version: str
) -> int:
    import requests

    resp = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}/properties/Attachments",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": notion_version,
        },
        timeout=(30, 120),
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"GET Attachments property failed: HTTP {resp.status_code} {resp.text[:500]}"
        )
    return len((resp.json() or {}).get("files") or [])


def _run_zip_bundle_pass(
    log: logging.Logger,
    token: str,
    database_id: str,
    ds_hint: str | None,
    *,
    small_file_count: int = 18,
) -> int:
    """Exercise attach_zip_bytes_to_page (rate-limited server pass) and read-back count."""
    import io
    import zipfile

    from notion_service import NotionService  # noqa: E402

    svc = NotionService(
        token=token,
        database_id=database_id,
        data_source_id_hint=ds_hint,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("issue.json", '{"title":"zip-bundle-test"}\n')
        zf.writestr("collected_data.json", '{"env":{}}\n')
        for i in range(small_file_count):
            zf.writestr(
                f"logs/test_log_{i:02d}.log",
                f"log line {i}\n" * 32,
            )
        zf.writestr(
            "attachments/screenshot_note.txt",
            b"attachment payload for zip bundle pass\n",
        )
        mp_size = 21 * 1024 * 1024
        zf.writestr(
            "attachments/large_multipart.txt",
            b"M" * mp_size,
        )
    zip_bytes = buf.getvalue()
    expected_members = small_file_count + 4  # issue, collected_data, screenshot, large

    title = f"[Debugly zip bundle pass] {time.strftime('%Y-%m-%d %H:%M:%S')}"
    log.info("Creating page for zip bundle pass: %s", title)
    result = svc.submit_issue(
        title=title,
        user_message="scripts/test_notion_upload.py --zip-bundle-pass",
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
        return 20

    log.info(
        "Running attach_zip_bytes_to_page (%s byte ZIP, ~%s members)...",
        len(zip_bytes),
        expected_members,
    )
    out = svc.attach_zip_bytes_to_page(zip_bytes, page_id)
    log.info("attach_zip_bytes_to_page result: %r", out)
    uploaded = int(out.get("attachments_uploaded") or 0)
    failed = int(out.get("attachments_failed") or 0)
    if failed:
        log.warning("Failures (%s): %s", failed, out.get("attachment_failures"))

    on_page = _count_page_attachments(token, page_id, svc.notion_version)
    log.info(
        "Read-back Attachments count=%s (uploaded=%s expected~=%s)",
        on_page,
        uploaded,
        expected_members,
    )
    if on_page != uploaded:
        log.error("Read-back count %s != reported uploaded %s", on_page, uploaded)
        return 21
    if uploaded < expected_members - 1:
        log.error(
            "Too few attachments on page: got %s expected at least %s",
            uploaded,
            expected_members - 1,
        )
        return 22
    log.info("OK zip bundle pass. url=%s", result.get("url"))
    return 0


def _run_list_entries_test(log: logging.Logger) -> int:
    """Offline check that list_zip_attach_entries selects + renames members correctly."""
    import io
    import zipfile

    from notion_service import list_zip_attach_entries  # noqa: E402

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("issue.json", '{"title":"t"}\n')
        zf.writestr("collected_data.json", '{"env":{}}\n')
        zf.writestr("logs/app.log", b"log\n" * 10)
        zf.writestr("attachments/note.txt", b"note\n")
        zf.writestr("screenshot/shot.png", b"\x89PNG\r\n\x1a\n")
        # Members outside the relevant set must be ignored.
        zf.writestr("ignored/other.bin", b"x")
        zf.writestr("root_file.txt", b"x")
    entries = list_zip_attach_entries(buf.getvalue())

    by_path = {zip_path: display for zip_path, display, _ in entries}
    expected_paths = {
        "issue.json",
        "collected_data.json",
        "logs/app.log",
        "attachments/note.txt",
        "screenshot/shot.png",
    }
    got_paths = set(by_path)
    if got_paths != expected_paths:
        log.error(
            "Member selection mismatch: got=%s expected=%s (extra=%s missing=%s)",
            sorted(got_paths),
            sorted(expected_paths),
            sorted(got_paths - expected_paths),
            sorted(expected_paths - got_paths),
        )
        return 10

    # .log / .json display names must become .txt to avoid Notion 403 on those types.
    renames = {
        "issue.json": "issue.txt",
        "collected_data.json": "collected_data.txt",
        "logs/app.log": "app.txt",
        "attachments/note.txt": "note.txt",
        "screenshot/shot.png": "shot.png",
    }
    for zip_path, expected_name in renames.items():
        if by_path.get(zip_path) != expected_name:
            log.error(
                "Display-name mismatch for %s: got %r expected %r",
                zip_path,
                by_path.get(zip_path),
                expected_name,
            )
            return 11

    log.info("OK list_zip_attach_entries: %d members, .log/.json -> .txt", len(entries))
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
                svc._set_page_attachments(page_id, files_payload)
                log.info("Done. url=%s", result.get("url"))
            except Exception as e:
                log.error("PATCH Attachments failed: %s", e)
                failed += 1

    if failed:
        log.error("Repro finished with %d failure(s) (see errors above)", failed)
        return 5
    log.info("Repro: all upload steps succeeded")
    return 0


def _run_probe_upload_hosts(log: logging.Logger, token: str) -> int:
    """Create file_upload objects only; log upload_url / send_host resolution (no send)."""
    import requests

    from notion_service import (  # noqa: E402
        NOTION_MULTIPART_CHUNK_BYTES,
        NOTION_SINGLE_PART_MAX_BYTES,
        _resolve_file_upload_complete_url,
        _resolve_file_upload_send_url,
        _url_host,
    )

    nv = "2026-03-11"
    base = "https://api.notion.com/v1"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": nv,
    }
    log.info(
        "Probe: run from AYON server host (same egress as notion/attach_bundle)"
    )

    def _log_response_meta(resp: requests.Response, label: str) -> None:
        ray = resp.headers.get("cf-ray") or resp.headers.get("CF-Ray")
        log.info("  %s HTTP %s cf-ray=%s", label, resp.status_code, ray or "?")

    log.info("Probe: POST /file_uploads single_part create (no send)")
    resp = requests.post(
        f"{base}/file_uploads",
        headers=headers,
        json={
            "mode": "single_part",
            "filename": "probe_single.txt",
            "content_type": "text/plain",
        },
        timeout=(30, 120),
    )
    _log_response_meta(resp, "single_part create")
    if resp.status_code != 200:
        log.error("  body: %s", (resp.text or "")[:1500])
        return 3
    info = resp.json()
    fid = info["id"]
    raw_upload = info.get("upload_url")
    send_url, use_auth = _resolve_file_upload_send_url(base, fid, raw_upload)
    log.info(
        "  single_part raw_upload_host=%s send_host=%s auth=%s",
        _url_host(raw_upload or ""),
        _url_host(send_url),
        use_auth,
    )

    mp_size = NOTION_SINGLE_PART_MAX_BYTES + 1
    chunk = NOTION_MULTIPART_CHUNK_BYTES
    number_of_parts = (mp_size + chunk - 1) // chunk
    log.info(
        "Probe: POST /file_uploads multi_part create parts=%s (no send)",
        number_of_parts,
    )
    resp2 = requests.post(
        f"{base}/file_uploads",
        headers=headers,
        json={
            "mode": "multi_part",
            "number_of_parts": number_of_parts,
            "filename": "probe_multipart.txt",
            "content_type": "text/plain",
        },
        timeout=(30, 120),
    )
    _log_response_meta(resp2, "multi_part create")
    if resp2.status_code != 200:
        log.error("  body: %s", (resp2.text or "")[:1500])
        return 4
    info2 = resp2.json()
    fid2 = info2["id"]
    raw_upload2 = info2.get("upload_url")
    raw_complete = info2.get("complete_url")
    send_url2, use_auth2 = _resolve_file_upload_send_url(base, fid2, raw_upload2)
    complete_url2 = _resolve_file_upload_complete_url(base, fid2, raw_complete)
    log.info(
        "  multi_part raw_upload_host=%s send_host=%s auth=%s",
        _url_host(raw_upload2 or ""),
        _url_host(send_url2),
        use_auth2,
    )
    log.info(
        "  multi_part raw_complete_host=%s complete_host=%s",
        _url_host(raw_complete or ""),
        _url_host(complete_url2),
    )
    log.info("Probe done (create only; no bytes sent)")
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
        "--list-entries-only",
        action="store_true",
        help="Offline: verify list_zip_attach_entries member selection + .txt renames (no Notion API)",
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
    parser.add_argument(
        "--zip-bundle-pass",
        action="store_true",
        help="Create a multi-member report ZIP and run attach_zip_bytes_to_page; "
        "verify read-back Attachments count",
    )
    parser.add_argument(
        "--probe-upload-hosts",
        action="store_true",
        help="POST file_uploads (single + multi_part) only; log upload_url/send_host "
        "resolution and cf-ray — run on AYON server egress",
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

    if args.list_entries_only:
        return _run_list_entries_test(log)

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

    if args.probe_upload_hosts:
        return _run_probe_upload_hosts(log, token)

    if args.repro_failing_names:
        return _run_repro_failing_names(
            log,
            token,
            database_id,
            ds_hint,
            attach_page=args.repro_attach_page,
        )

    if args.zip_bundle_pass:
        return _run_zip_bundle_pass(log, token, database_id, ds_hint)

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
    svc._set_page_attachments(page_id, files_payload)
    log.info("Done. Check Notion row: %s", page_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
