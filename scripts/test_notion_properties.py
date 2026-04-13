#!/usr/bin/env python3
"""
Verify Notion database schema + pages.create property payloads (API 2026-03-11).

Uses repo-root .env (same as test_notion_upload.py):
  NOTION_API_KEY — integration token
  NOTION_DB_ID   — database UUID, optional ?v=<data_source_hint>

Default: print schema (title key, select options). No writes.

Examples:
  python scripts/test_notion_properties.py
  python scripts/test_notion_properties.py --create
  python scripts/test_notion_properties.py --create --title-prefix "QA"

Confirm Issue Type / Project / Pipeline (mirror production UI), exit non-zero on mismatch:
  python scripts/test_notion_properties.py --create --assert-properties \\
    --issue-type Bug --project MyGame --pipeline production --dump-built-json

If --assert-properties passes locally but AYON-submitted rows stay empty, redeploy the
Debugly **server** addon so notion_submit runs the same NotionService as this repo.

**Parity with the desktop → AYON path (same Notion row fields):**
- Use the same Notion integration token as the AYON studio **secret** referenced by
  Debugly settings (`api_key` secret name → value must match `NOTION_API_KEY` here).
- Use the same database string as studio **database_id**, including any `?v=<uuid>`
  data-source hint (`NOTION_DB_ID`).
- After a desktop submit, compare client log
  ``Notion endpoint: POST notion/submit metadata`` with server log
  ``Debugly Notion: POST /notion/submit parsed`` and ``Notion pages.create payload summary``.

Requires: requests, server/notion_service.py on PYTHONPATH (script adds ../server).

Use when Notion changes API version, renames columns, or Debugly stops setting fields.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]


def _load_env_file(path: Path) -> None:
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


def _headers(token: str, notion_version: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version,
        "Content-Type": "application/json",
    }


def _print_schema(
    log: logging.Logger,
    token: str,
    database_id: str,
    notion_version: str,
) -> tuple[dict, str | None]:
    """Return (data_source_properties_dict, data_source_id)."""
    h = _headers(token, notion_version)
    base = "https://api.notion.com/v1"
    r = requests.get(f"{base}/databases/{database_id}", headers=h, timeout=60)
    r.raise_for_status()
    db = r.json()
    sources = db.get("data_sources") or []
    if not sources:
        log.error("No data_sources on database; use GET /databases properties only")
        props = db.get("properties") or {}
        for mk, spec in sorted(props.items(), key=lambda x: str(x[0])):
            if isinstance(spec, dict):
                log.info("  %r -> type=%s name=%r", mk, spec.get("type"), spec.get("name"))
        return props, None

    ds_id = sources[0]["id"]
    log.info("data_sources[0] id=%s... name=%r", ds_id[:8], sources[0].get("name"))
    r2 = requests.get(f"{base}/data_sources/{ds_id}", headers=h, timeout=60)
    r2.raise_for_status()
    props = r2.json().get("properties") or {}

    title_keys = [
        mk
        for mk, spec in props.items()
        if isinstance(spec, dict) and spec.get("type") == "title"
    ]
    log.info("Title property map_key(s): %s", title_keys or "(none)")

    interest = (
        "Status",
        "Priority",
        "Issue Type",
        "Project",
        "Pipeline Release",
        "Submitted By",
        "Attachments",
    )
    for name in interest:
        spec = props.get(name)
        resolved_key = name
        if not isinstance(spec, dict):
            # Data source schemas may use UUID keys; match by spec["name"]
            for mk, ms in props.items():
                if isinstance(ms, dict) and str(ms.get("name", "")).strip() == name:
                    spec = ms
                    resolved_key = mk
                    break
        if not isinstance(spec, dict):
            log.warning("  %s: MISSING from schema (checked keys and name attrs)", name)
            continue
        if resolved_key != name:
            log.info("  %s: resolved via name attr on key=%r", name, resolved_key)
        ptype = spec.get("type")
        extra = ""
        if ptype in ("select", "multi_select", "status"):
            opts = (spec.get(ptype) or {}).get("options") or []
            names = [o.get("name") for o in opts if o.get("name")]
            extra = f" options={names[:15]!r}" + (
                f" (+{len(names) - 15} more)" if len(names) > 15 else ""
            )
        log.info("  %s: type=%s%s", name, ptype, extra)

    return props, ds_id


def _snapshot_page_props(
    log: logging.Logger,
    token: str,
    notion_version: str,
    page_id: str,
) -> None:
    """Log all page properties. Notion often uses UUID map keys, not display names."""
    h = _headers(token, notion_version)
    r = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=h, timeout=60)
    r.raise_for_status()
    props = r.json().get("properties") or {}
    interest = {
        "Name",
        "Title",
        "Status",
        "Priority",
        "Issue Type",
        "Project",
        "Pipeline Release",
        "Submitted By",
        "Attachments",
    }

    def _one(map_key: str, v: dict) -> None:
        t = v.get("type", "?")
        if t == "title":
            ta = v.get("title") or []
            text = (ta[0].get("plain_text") if ta else "")[:120]
            log.info("  %r: title %r", map_key, text)
        elif t in ("select", "status"):
            log.info(
                "  %r: %s name=%r",
                map_key,
                t,
                (v.get(t) or {}).get("name"),
            )
        elif t == "multi_select":
            log.info(
                "  %r: multi_select %r",
                map_key,
                [x.get("name") for x in (v.get("multi_select") or [])],
            )
        elif t == "people":
            pe = v.get("people") or []
            log.info("  %r: people n=%d", map_key, len(pe))
        elif t == "files":
            fi = v.get("files") or []
            log.info("  %r: files n=%d", map_key, len(fi))
        else:
            log.info("  %r: type=%s", map_key, t)

    # Exact key match (older DBs with human-readable map keys)
    for label in sorted(interest):
        if label in props and isinstance(props[label], dict):
            _one(label, props[label])

    # Every property (covers UUID map keys from data_sources schema)
    logged_keys = {k for k in interest if k in props}
    extra = [k for k in sorted(props.keys()) if k not in logged_keys]
    if extra:
        log.info("  --- remaining property map_keys (%d) ---", len(extra))
    for map_key in extra:
        val = props.get(map_key)
        if isinstance(val, dict):
            _one(map_key, val)
        else:
            log.info("  %r: (non-dict %s)", map_key, type(val).__name__)


def _get_page_properties(
    token: str, notion_version: str, page_id: str
) -> dict:
    h = _headers(token, notion_version)
    r = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}", headers=h, timeout=60
    )
    r.raise_for_status()
    return r.json().get("properties") or {}


def _option_names_from_page_property(val: dict) -> list[str]:
    """Select/status/multi_select option display names from GET /pages property value."""
    if not isinstance(val, dict):
        return []
    t = val.get("type")
    if t == "select":
        n = (val.get("select") or {}).get("name")
        return [str(n)] if n is not None and str(n).strip() else []
    if t == "status":
        n = (val.get("status") or {}).get("name")
        return [str(n)] if n is not None and str(n).strip() else []
    if t == "multi_select":
        return [
            str(x.get("name"))
            for x in (val.get("multi_select") or [])
            if x.get("name") is not None and str(x.get("name")).strip()
        ]
    return []


def _norm_opt(s: str) -> str:
    return (s or "").strip().lower()


def _assert_page_metadata(
    log: logging.Logger,
    svc: Any,
    token: str,
    notion_version: str,
    page_id: str,
    *,
    issue_type: str,
    project: str,
    pipeline: str,
) -> int:
    """Return 0 if all expected metadata matches GET /pages; else 4 with errors logged."""
    db_props = svc._get_database_properties()
    page_props = _get_page_properties(token, notion_version, page_id)
    errors: list[str] = []

    itk = svc._notion_property_key(
        db_props, "Issue Type", "Issue Type (AI)", "Issue Type AI"
    )
    want_it = (issue_type or "").strip()
    if want_it:
        if not itk:
            errors.append("schema: no Issue Type column resolved (check data source / names)")
        else:
            got = _option_names_from_page_property(page_props.get(itk) or {})
            if not any(_norm_opt(x) == _norm_opt(want_it) for x in got):
                errors.append(
                    f"Issue Type: expected option {want_it!r}, got {got!r} (map_key={itk!r})"
                )

    prk = svc._notion_property_key(db_props, "Project", "Project(s)", "Projects")
    want_pr = (project or "").strip()
    if want_pr:
        if want_pr.lower() == "all releases":
            want_pr = "Studio"
        if not prk:
            errors.append("schema: no Project column resolved")
        else:
            got = _option_names_from_page_property(page_props.get(prk) or {})
            if not any(_norm_opt(x) == _norm_opt(want_pr) for x in got):
                errors.append(
                    f"Project: expected option {want_pr!r} among values, got {got!r} "
                    f"(map_key={prk!r})"
                )

    plk = svc._notion_property_key(db_props, "Pipeline Release", "Pipeline release")
    want_pl = (pipeline or "").strip()
    if want_pl:
        if not plk:
            errors.append("schema: no Pipeline Release column resolved")
        else:
            got = _option_names_from_page_property(page_props.get(plk) or {})
            if not any(_norm_opt(x) == _norm_opt(want_pl) for x in got):
                errors.append(
                    f"Pipeline Release: expected option {want_pl!r}, got {got!r} "
                    f"(map_key={plk!r})"
                )

    if errors:
        for e in errors:
            log.error("ASSERT failed: %s", e)
        return 4
    log.info(
        "ASSERT ok: Issue Type=%r Project=%r Pipeline Release=%r match GET /pages",
        want_it or "(not checked)",
        want_pr or "(not checked)",
        want_pl or "(not checked)",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect Notion DB schema and optionally create a test row to verify properties",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create a test page via NotionService.submit_issue and verify fields via GET",
    )
    parser.add_argument(
        "--title-prefix",
        default="[Debugly props test]",
        help="Title prefix when --create (timestamp appended)",
    )
    parser.add_argument(
        "--issue-type",
        default="Bug",
        help="Issue Type select name for --create",
    )
    parser.add_argument(
        "--project",
        default="Studio",
        help="Project multi_select option for --create (must exist in schema)",
    )
    parser.add_argument(
        "--pipeline",
        default="production",
        help="Pipeline Release select name for --create",
    )
    parser.add_argument(
        "--dump-built-json",
        action="store_true",
        help="With --create, print JSON of properties dict built before POST (no secrets)",
    )
    parser.add_argument(
        "--assert-properties",
        action="store_true",
        help="With --create: after GET page, exit 4 if Issue Type / Project / Pipeline "
        "do not match --issue-type / --project / --pipeline (uses same schema resolution "
        "as NotionService)",
    )
    parser.add_argument(
        "--dump-schema",
        action="store_true",
        help="Print the full raw properties schema JSON (from data_source or database) "
        "for comparison with server-side _build_properties logs",
    )
    args = parser.parse_args()

    if args.assert_properties and not args.create:
        print("--assert-properties requires --create", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    log = logging.getLogger("test_notion_properties")

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
        log.error("NOTION_API_KEY missing")
        return 1
    if not database_id:
        log.error("NOTION_DB_ID missing or invalid")
        return 2

    from notion_service import NotionService  # noqa: E402

    svc = NotionService(
        token=token,
        database_id=database_id,
        data_source_id_hint=ds_hint,
    )
    nv = svc.notion_version
    log.info("Database %s... Notion-Version %s", database_id[:8], nv)

    schema_props, ds_id = _print_schema(log, token, database_id, nv)

    if args.dump_schema:
        log.info(
            "Raw schema source: %s",
            f"data_source {ds_id[:8]}..." if ds_id else "database",
        )
        log.info("Schema property count: %d", len(schema_props))
        for map_key in sorted(schema_props.keys(), key=str):
            spec = schema_props[map_key]
            if isinstance(spec, dict):
                log.info(
                    "  key=%r  name=%r  type=%s",
                    map_key,
                    spec.get("name"),
                    spec.get("type"),
                )
        log.info(
            "Full schema JSON:\n%s",
            json.dumps(schema_props, indent=2, default=str)[:20000],
        )

    if not args.create:
        log.info("Done (schema only). Pass --create to submit a test issue and verify properties.")
        return 0

    title = f"{args.title_prefix} {time.strftime('%Y-%m-%d %H:%M:%S')}"
    if args.dump_built_json:
        built = svc._build_properties(
            title=title,
            user_message="scripts/test_notion_properties.py — safe to delete.",
            _tags=[],
            collected_data={},
            assignee_id="",
            title_property_override=None,
            issue_type=args.issue_type,
            project=args.project,
            pipeline_release=args.pipeline,
        )
        log.info("Built property keys: %s", list(built.keys()))
        log.info("Built properties JSON:\n%s", json.dumps(built, indent=2)[:12000])

    log.info("submit_issue (no attachments)...")
    result = svc.submit_issue(
        title=title,
        user_message="Automated property test. Safe to delete.",
        collected_data={},
        tags=[],
        attachments_zip_b64=None,
        assignee_id="",
        async_attachments=False,
        blocks=None,
        title_property=None,
        issue_type=args.issue_type,
        project=args.project,
        pipeline_release=args.pipeline,
    )
    page_id = result.get("page_id") or ""
    if not page_id:
        log.error("submit_issue failed: %r", result)
        return 3
    log.info("Created %s url=%s", page_id, result.get("url"))
    log.info("GET page property check:")
    _snapshot_page_props(log, token, nv, page_id)
    if args.assert_properties:
        rc = _assert_page_metadata(
            log,
            svc,
            token,
            nv,
            page_id,
            issue_type=args.issue_type,
            project=args.project,
            pipeline=args.pipeline,
        )
        if rc != 0:
            return rc
    else:
        log.info(
            "Pass --assert-properties to fail if Issue Type / Project / Pipeline mismatch. "
            "If they are null here but you passed --assert-properties, fix schema/options "
            "or redeploy AYON server addon to match this repo."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
