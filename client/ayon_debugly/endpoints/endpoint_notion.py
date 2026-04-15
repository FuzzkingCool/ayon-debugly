# -*- coding: utf-8 -*-
import base64
import math
import os
import random
import time
from typing import Any, Dict, List, Optional

import ayon_api
import requests

from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.endpoints.endpoint_base import EndpointBase
from ayon_debugly.logger import log
from ayon_debugly.version import __version__

# Chunked upload to AYON (each chunk is base64 JSON; keep under gateway limits).
# Ops: reverse-proxy client_max_body_size and timeouts must allow at least one chunk POST.
UPLOAD_CHUNK_THRESHOLD_BYTES = 8 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
_POST_RETRY_MAX = 3
_POST_RETRY_STATUSES = frozenset({500, 502, 503, 504})
# Delay between successive Notion file uploads (reduces burst 403 / rate limits).
NOTION_INTER_UPLOAD_DELAY_SEC = 0.85


def _attachment_display_name_from_zip_base(base_name: str) -> str:
    """Notion-friendly names: .log / .json → .txt (avoid application/json 403s)."""
    low = base_name.lower()
    if low.endswith(".log"):
        return base_name[:-4] + ".txt"
    if low.endswith(".json"):
        return base_name[:-5] + ".txt"
    return base_name


class EndpointNotion(EndpointBase):
    def __init__(self):
        self.notion_token = None
        self.database_id = None
        self.notion_version = "2026-03-11"  # Match server NotionService / Notion docs
        self.base_url = "https://api.notion.com/v1"
        super().__init__()

    def initialize(self, settings=None):
        """Initialize the Notion endpoint with required credentials and database ID"""
        import ayon_api

        from ayon_debugly.version import __version__

        try:
            # Use provided settings or fetch from API
            if settings is None:
                log.debug(
                    f"Notion endpoint: Requesting settings for version: {__version__}"
                )
                settings = ayon_api.get_addon_settings("debugly", __version__)
                log.debug("Notion endpoint: Got versioned settings successfully")
            log.debug(f"Notion endpoint: Loaded settings type: {type(settings)}")
            log.debug(
                f"Notion endpoint: Settings keys: {list(settings.keys()) if isinstance(settings, dict) else 'Not a dict'}"
            )

            # Debug: Log the full settings structure for notion
            if isinstance(settings, dict) and "endpoints" in settings:
                log.debug(
                    f"Notion endpoint: Full endpoints structure: {settings['endpoints']}"
                )
                if "notion" in settings["endpoints"]:
                    log.debug(
                        f"Notion endpoint: Full notion structure: {settings['endpoints']['notion']}"
                    )
                    if "notion" in settings["endpoints"]["notion"]:
                        log.debug(
                            f"Notion endpoint: Full notion config: {settings['endpoints']['notion']['notion']}"
                        )

                        # Debug the actual database_id value we're getting
                        notion_config = settings["endpoints"]["notion"]["notion"]
                        db_id = notion_config.get("database_id", "NOT_FOUND")
                        log.debug(
                            f"Notion endpoint: Raw database_id from settings: '{db_id}' (type: {type(db_id)}, length: {len(str(db_id))})"
                        )
                        # Check each field individually
                        notion_config = settings["endpoints"]["notion"]["notion"]
                        log.debug(
                            f"Notion endpoint: database_id from direct access: '{notion_config.get('database_id', 'NOT_FOUND')}'"
                        )
                        log.debug(
                            f"Notion endpoint: api_key from direct access: '{notion_config.get('api_key', 'NOT_FOUND')}'"
                        )
                        log.debug(
                            f"Notion endpoint: assignee_id from direct access: '{notion_config.get('assignee_id', 'NOT_FOUND')}'"
                        )
                        log.debug(
                            f"Notion endpoint: All keys in notion config: {list(notion_config.keys())}"
                        )
                        log.debug(
                            f"Notion endpoint: All values in notion config: {list(notion_config.values())}"
                        )

            # Handle multiple possible settings structures
            notion_settings = None
            notion_config = None

            # Try endpoints.notion structure first
            if hasattr(settings, "endpoints") and hasattr(settings.endpoints, "notion"):
                notion_settings = settings.endpoints.notion
                if notion_settings.enabled:
                    notion_config = notion_settings.notion
            elif isinstance(settings, dict):
                # Try endpoints.notion structure
                if "endpoints" in settings and "notion" in settings["endpoints"]:
                    notion_settings = settings["endpoints"]["notion"]
                    if notion_settings.get("enabled", False):
                        notion_config = notion_settings.get("notion", {})
                # Try direct notion structure (as provided by user)
                elif "notion" in settings:
                    notion_settings = settings["notion"]
                    if notion_settings.get("enabled", False):
                        notion_config = notion_settings.get("notion", {})

            if not notion_settings or not notion_config:
                raise ValueError("Notion endpoint configuration not found in settings")

            # Extract configuration values
            if hasattr(notion_config, "api_key"):
                api_key_secret = notion_config.api_key
                self.database_id = notion_config.database_id
                self.assignee_id = getattr(notion_config, "assignee_id", "") or ""
            else:
                api_key_secret = notion_config.get("api_key")
                self.database_id = notion_config.get("database_id")
                self.assignee_id = notion_config.get("assignee_id", "")

            log.debug(f"Notion endpoint: Extracted database_id: '{self.database_id}'")
            log.debug(f"Notion endpoint: Extracted api_key_secret: '{api_key_secret}'")
            log.debug(f"Notion endpoint: Extracted assignee_id: '{self.assignee_id}'")
            log.debug(f"Notion endpoint: Database ID type: {type(self.database_id)}")
            log.debug(
                f"Notion endpoint: Database ID length: {len(self.database_id) if self.database_id else 0}"
            )

            # Get the actual API key from the secret
            # if api_key_secret:
            #     try:
            #         secret_data = ayon_api.get_secret(api_key_secret)
            #         self.notion_token = secret_data.get("value")
            #     except Exception as e:
            #         raise ValueError(f"Failed to retrieve Notion API key from secret '{api_key_secret}': {e}")
            # else:
            #     raise ValueError("Notion API key secret name is required in settings")

            # if not self.notion_token:
            #     raise ValueError("Notion API key is required in settings")

            # Client no longer resolves secrets; server will use them. Database ID is managed on server.
            if not self.database_id:
                log.warning(
                    "Notion database ID is not set; server will validate settings."
                )
            else:
                # Keep ?v=<data_source_id> for submit payload: server prefers request
                # database_id over settings; stripping the hint made ds_hint None and
                # broke multi-source DB schema / property resolution.
                raw_db = str(self.database_id).strip()
                base, sep, qs = raw_db.partition("?")
                suffix = f"{sep}{qs}" if sep else ""
                db_core = base.strip()
                log.debug("Notion endpoint: Raw database_id from settings (len=%s)", len(raw_db))
                if len(db_core) == 32 and "-" not in db_core:
                    db_core = (
                        f"{db_core[:8]}-{db_core[8:12]}-{db_core[12:16]}-"
                        f"{db_core[16:20]}-{db_core[20:]}"
                    )
                    log.debug(
                        "Notion endpoint: Normalized compact DB UUID; preserving query: %s",
                        bool(suffix),
                    )
                self.database_id = db_core + suffix

            log.debug(
                f"Notion endpoint: Initialized with database_id: {self.database_id[:20]}..."
            )
            log.debug(
                "Notion endpoint: API key will be retrieved by server from secret store"
            )

            # Skip client-side schema validation; handled by server

        except Exception as e:
            log.error(f"Notion endpoint initialization failed: {e}")
            raise ValueError(f"Failed to initialize Notion endpoint: {e}")

    @staticmethod
    def _rest_response_to_dict(resp: Any) -> Optional[dict]:
        if resp is None:
            return None
        data = getattr(resp, "data", None)
        if isinstance(data, dict):
            return data
        json_fn = getattr(resp, "json", None)
        if callable(json_fn):
            try:
                out = json_fn()
                return out if isinstance(out, dict) else None
            except Exception:
                pass
        text_val = getattr(resp, "text", None)
        if isinstance(text_val, str) and text_val.strip():
            try:
                import json as _json

                out = _json.loads(text_val)
                return out if isinstance(out, dict) else None
            except Exception:
                return None
        if isinstance(resp, dict):
            return resp
        return None

    def _log_addon_post_shape(
        self, label: str, resp: Any, parsed: Optional[dict]
    ) -> None:
        sc = int(getattr(resp, "status_code", 0) or 0)
        if isinstance(parsed, dict) and ("success" in parsed or "error" in parsed):
            return
        snippet = ""
        try:
            t = getattr(resp, "text", None)
            if isinstance(t, str) and t.strip():
                snippet = t.strip()[:500]
        except Exception:
            pass
        log.warning(
            "Notion endpoint: %s unexpected response status=%s parsed=%s text_head=%r",
            label,
            sc,
            type(parsed).__name__,
            snippet,
        )

    def _post_debugly_addon(self, endpoint: str, **payload: Any) -> Any:
        """POST with retries on transient AYON / gateway errors (versioned route only)."""
        last_resp = None
        for attempt in range(_POST_RETRY_MAX):
            resp = ayon_api.post(endpoint, **payload)
            last_resp = resp
            sc = int(getattr(resp, "status_code", 0) or 0)
            if sc == 200 or sc not in _POST_RETRY_STATUSES:
                return resp
            log.warning(
                "Notion endpoint: %s returned HTTP %s (attempt %s/%s), retrying...",
                endpoint,
                sc,
                attempt + 1,
                _POST_RETRY_MAX,
            )
            time.sleep(0.4 * (2**attempt) + random.random() * 0.15)
        return last_resp

    def _post_debugly_notion_route(self, tail: str, **payload: Any) -> Any:
        """POST the versioned addon path, then the unversioned path on 404/405.

        Some gateways or older AYON builds expose addon POST routes only on the
        unversioned path; 405 Method Not Allowed has been observed on versioned URLs.
        """
        t = (tail or "").lstrip("/")
        primary = f"/addons/debugly/{__version__}/{t}"
        resp = self._post_debugly_addon(primary, **payload)
        sc = int(getattr(resp, "status_code", 0) or 0)
        if sc in (404, 405):
            log.warning(
                "Notion endpoint: %s returned HTTP %s, retrying unversioned /addons/debugly/%s",
                primary,
                sc,
                t,
            )
            resp = self._post_debugly_addon(f"/addons/debugly/{t}", **payload)
        return resp

    def _upload_bytes_chunked_to_server(
        self, page_id: str, filename: str, file_bytes: bytes
    ) -> dict:
        """Upload large files via upload_begin / upload_chunk / upload_complete."""
        n = max(1, math.ceil(len(file_bytes) / float(UPLOAD_CHUNK_BYTES)))

        r0 = self._post_debugly_notion_route(
            "notion/upload_begin",
            page_id=page_id,
            filename=filename,
            file_size=len(file_bytes),
            total_chunks=n,
        )
        d0 = self._rest_response_to_dict(r0)
        self._log_addon_post_shape("upload_begin", r0, d0)
        if not isinstance(d0, dict) or not d0.get("success") or not d0.get("upload_id"):
            err = (d0 or {}).get("error") if isinstance(d0, dict) else "invalid begin response"
            return {"error": err or "upload_begin failed"}

        uid = d0["upload_id"]
        for i in range(n):
            start = i * UPLOAD_CHUNK_BYTES
            chunk = file_bytes[start : start + UPLOAD_CHUNK_BYTES]
            b64 = base64.b64encode(chunk).decode("ascii")
            r1 = self._post_debugly_notion_route(
                "notion/upload_chunk",
                upload_id=uid,
                chunk_index=i,
                chunk_b64=b64,
            )
            d1 = self._rest_response_to_dict(r1)
            self._log_addon_post_shape(f"upload_chunk[{i}]", r1, d1)
            if not isinstance(d1, dict) or not d1.get("success"):
                err = (d1 or {}).get("error") if isinstance(d1, dict) else "chunk failed"
                return {"error": err or f"upload_chunk {i} failed"}

        r2 = self._post_debugly_notion_route("notion/upload_complete", upload_id=uid)
        d2 = self._rest_response_to_dict(r2)
        self._log_addon_post_shape("upload_complete", r2, d2)
        if not isinstance(d2, dict):
            return {"error": "invalid complete response"}
        if d2.get("success") and d2.get("file_id"):
            return {
                "success": True,
                "file_id": d2["file_id"],
                "filename": d2.get("filename", filename),
            }
        return {"error": d2.get("error", "upload_complete failed")}

    def _append_upload_failures_note(
        self,
        page_id: str,
        failures: List[str],
        archive_note: Optional[str] = None,
    ) -> None:
        if not failures and not (archive_note or "").strip():
            return
        try:
            r = self._post_debugly_notion_route(
                "notion/append_upload_failures",
                page_id=page_id,
                failures=list(failures)[:80],
                archive_note=(archive_note or "").strip() or None,
            )
            d = self._rest_response_to_dict(r)
            self._log_addon_post_shape("append_upload_failures", r, d)
            if isinstance(d, dict) and d.get("success"):
                log.debug("Notion endpoint: Appended upload failure note to page")
            else:
                err = (d or {}).get("error") if isinstance(d, dict) else None
                sc = int(getattr(r, "status_code", 0) or 0)
                head = ""
                try:
                    tx = getattr(r, "text", None)
                    if isinstance(tx, str):
                        head = tx.strip()[:800]
                except Exception:
                    pass
                log.warning(
                    "Notion endpoint: append_upload_failures failed status=%s err=%s text_head=%r",
                    sc,
                    err,
                    head,
                )
        except Exception as e:
            log.warning("Notion endpoint: append_upload_failures failed: %s", e)

    def submit(self, issue: DebuglyIssue, progress_callback=None):
        """
        Submit an issue to the Notion database

        Args:
            issue: DebuglyIssue object containing all issue data

        Returns:
            dict: url, page_id, attachments_ok, attachment counts/failures
        """
        import ayon_api

        from ayon_debugly.version import __version__

        log.debug(
            f"Notion endpoint: Starting submission for issue '{issue.title[:50]}...'"
        )
        log.debug("Notion endpoint: Step 1/3 - Creating Issue in Notion...")
        if progress_callback:
            progress_callback("Creating Issue Page in Notion...", 0, 100)
        log.debug(
            f"Notion endpoint: Issue details - title: '{issue.title}', message length: {len(issue.user_message) if issue.user_message else 0}"
        )
        log.debug(
            f"Notion endpoint: Collected data keys: {list(issue.collected_data.keys()) if issue.collected_data else []}"
        )
        log.debug(
            f"Notion endpoint: Database ID: {self.database_id[:8] if self.database_id else 'None'}..."
        )
        log.debug(f"Notion endpoint: Notion version: {self.notion_version}")

        # Prepare optional tags
        tags = []
        if hasattr(issue, "tags") and issue.tags:
            tags = [str(t).strip() for t in issue.tags if t and str(t).strip()]
        log.debug(f"Notion endpoint: Prepared tags: {tags}")

        # Bundle attachments/logs into a ZIP and base64 encode
        attachments_zip_b64 = None
        try:
            log.debug("Notion endpoint: Creating attachments ZIP...")
            zip_path = issue.to_zip()
            if zip_path and os.path.exists(zip_path):
                log.debug(f"Notion endpoint: ZIP created at: {zip_path}")
                with open(zip_path, "rb") as f:
                    attachments_zip_b64 = base64.b64encode(f.read()).decode("utf-8")
                log.debug(
                    f"Notion endpoint: ZIP encoded, size: {len(attachments_zip_b64)} chars"
                )
            else:
                log.debug("Notion endpoint: No ZIP file created")
        except Exception as e:
            log.warning(f"Notion endpoint: Failed to bundle attachments: {e}")

        # First payload: Create issue WITHOUT attachments for fast response
        payload = {
            "title": issue.title,
            "user_message": issue.user_message or "",
            "collected_data": issue.collected_data or {},
            "tags": tags or [],
            # NO attachments_zip_b64 - this will be sent separately
            # Omit title_property: Notion DBs often use "Name" (or UUID keys) for the
            # title column; server resolves the first title-type property from schema.
        }
        if getattr(issue, "issue_type", None):
            payload["issue_type"] = str(issue.issue_type).strip()
        if getattr(issue, "project", None):
            payload["project"] = str(issue.project).strip()
        if getattr(issue, "pipeline_release", None):
            payload["pipeline_release"] = str(issue.pipeline_release).strip()

        log.debug(f"Notion endpoint: Base payload keys: {list(payload.keys())}")
        log.debug(f"Notion endpoint: Payload title: '{payload['title']}'")
        log.debug(
            f"Notion endpoint: Payload user_message length: {len(payload['user_message'])}"
        )
        log.debug(
            f"Notion endpoint: Payload collected_data keys: {list(payload['collected_data'].keys()) if payload['collected_data'] else []}"
        )
        log.debug(f"Notion endpoint: Payload tags: {payload['tags']}")
        log.debug(
            "Notion endpoint: Payload has attachments: False (will be sent separately)"
        )
        log.debug(
            "Notion endpoint: Payload title_property: %r",
            payload.get("title_property"),
        )
        # Build Notion blocks on the client for exact WYSIWYG fidelity
        try:
            blocks = self._markdown_to_blocks(issue.user_message or "")
            if isinstance(blocks, list) and blocks:
                payload["blocks"] = blocks
        except Exception:
            pass
        # Pass database_id/assignee_id to server for robustness
        # Always send database_id if we have it, even if it's not set in self.database_id
        if hasattr(self, "database_id") and self.database_id:
            payload["database_id"] = self.database_id
            log.debug(f"Notion endpoint: Sending database_id to server: {self.database_id[:8]}...")
        else:
            log.warning("Notion endpoint: No database_id available to send to server")

        log.debug(f"Notion endpoint: Final payload size: {len(str(payload))} chars")
        log.debug(
            "Notion endpoint: Pre-submit metadata issue_type=%r project=%r "
            "pipeline_release=%r has_blocks=%s",
            payload.get("issue_type"),
            payload.get("project"),
            payload.get("pipeline_release"),
            bool(payload.get("blocks")),
        )
        log.info(
            "Notion endpoint: POST notion/submit metadata (snake_case; server logs should match): "
            "issue_type=%r project=%r pipeline_release=%r database_id_sent=%r",
            payload.get("issue_type"),
            payload.get("project"),
            payload.get("pipeline_release"),
            bool(payload.get("database_id")),
        )

        log.debug("Notion endpoint: Calling notion/submit (versioned with 404/405 fallback)...")
        resp = self._post_debugly_notion_route("notion/submit", **payload)
        log.debug(f"Notion endpoint: Submit response type: {type(resp)}")
        if hasattr(resp, "status_code"):
            log.debug(f"Notion endpoint: Submit status: {resp.status_code}")

        # ayon_api.post can return a response-like or data dict depending on version
        result = None
        log.debug("Notion endpoint: Processing server response...")
        log.debug(f"Notion endpoint: Response type: {type(resp)}")
        log.debug(
            f"Notion endpoint: Response attributes: {dir(resp) if hasattr(resp, '__dict__') else 'No attributes'}"
        )

        # Try to normalize different ayon_api.post return types
        if hasattr(resp, "status_code"):
            # HTTP-like response
            status = getattr(resp, "status_code", 0) or 0
            log.debug(f"Notion endpoint: HTTP response status: {status}")

            if status and int(status) >= 400:
                # Try to surface server error text for debugging
                text_val = getattr(resp, "text", "")
                detail = getattr(resp, "detail", None)
                log.error(
                    f"Notion endpoint: Server error - status: {status}, detail: {detail}, text: {text_val}"
                )
                raise Exception(detail or text_val or status)

            # Prefer .data if present
            result = getattr(resp, "data", None)
            log.debug(f"Notion endpoint: Response .data: {type(result)} - {result}")

            if not isinstance(result, dict):
                # Try .json() if available
                json_call = getattr(resp, "json", None)
                if callable(json_call):
                    try:
                        result = json_call()
                        log.debug(
                            f"Notion endpoint: Parsed JSON from .json(): {type(result)} - {result}"
                        )
                    except Exception as e:
                        log.debug(f"Notion endpoint: .json() failed: {e}")
                        result = None
            if not isinstance(result, dict):
                # Try parsing .text
                text_val = getattr(resp, "text", None)
                log.debug(
                    f"Notion endpoint: Response .text: {type(text_val)} - {text_val[:200] if text_val else 'None'}..."
                )
                if isinstance(text_val, str) and text_val.strip():
                    try:
                        import json as _json

                        result = _json.loads(text_val)
                        log.debug(
                            f"Notion endpoint: Parsed JSON from .text: {type(result)} - {result}"
                        )
                    except Exception as e:
                        log.debug(
                            f"Notion endpoint: JSON parsing from .text failed: {e}"
                        )
                        result = None
        else:
            # Some ayon_api versions return dict directly
            result = resp
            log.debug(
                f"Notion endpoint: Direct dict response: {type(result)} - {result}"
            )

        if not isinstance(result, dict):
            # Log raw response for diagnostics
            log.error("Notion endpoint: Failed to parse server response as dict")
            log.error(f"Notion endpoint: Response type: {type(result)}")
            log.error(f"Notion endpoint: Response value: {result}")
            try:
                log.error(
                    f"Notion endpoint: Raw server response: {getattr(resp, 'text', str(resp))}"
                )
            except Exception as e:
                log.error(f"Notion endpoint: Could not get raw response: {e}")
            raise Exception("Unexpected response from server when submitting to Notion")

        log.debug(
            f"Notion endpoint: Successfully parsed response: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}"
        )

        # Check for server-side errors first
        if isinstance(result, dict) and "error" in result:
            error_msg = result["error"]
            log.error(f"Notion endpoint: Server returned error: {error_msg}")
            raise Exception(f"Server error: {error_msg}")

        page_url = result.get("url", "")
        page_id = result.get("page_id", "")
        log.debug(
            f"Notion endpoint: Server created page - URL: {page_url}, ID: {page_id[:8] if page_id else 'None'}..."
        )
        log.debug("Notion endpoint: Step 2/3 - Page created successfully!")
        if progress_callback:
            progress_callback("Page created successfully!", 33, 100)

        attachments_ok = True
        attachment_failures: List[str] = []
        attachments_uploaded = 0
        attachments_failed = 0

        # Step 2: Upload attachments individually if we have them and page creation succeeded
        if attachments_zip_b64 and page_id:
            log.debug(
                "Notion endpoint: Step 3/3 - Starting individual attachment uploads..."
            )
            if progress_callback:
                progress_callback("Starting file uploads...", 50, 100)
            try:
                up_out = self._upload_attachments_individually(
                    attachments_zip_b64, page_id, progress_callback
                )
                if not isinstance(up_out, tuple) or len(up_out) != 2:
                    log.error(
                        "Notion endpoint: _upload_attachments_individually must return "
                        "(uploaded_files, failure_lines); got %s",
                        type(up_out).__name__,
                    )
                    raise TypeError(
                        "_upload_attachments_individually must return a 2-tuple"
                    )
                uploaded_files, upload_failures = up_out
                attachments_uploaded = len(uploaded_files)
                attachment_failures = list(upload_failures)
                attachments_failed = len(attachment_failures)
                log.debug(
                    f"Notion endpoint: Collected {len(uploaded_files)} uploaded files for finalization"
                )
                if uploaded_files:
                    log.debug(
                        f"Notion endpoint: Finalizing {len(uploaded_files)} attachments to page {page_id[:8]}..."
                    )
                    self._finalize_attachments(page_id, uploaded_files)
                else:
                    log.warning(
                        "Notion endpoint: No files were successfully uploaded for finalization"
                    )
                if upload_failures:
                    attachments_ok = False
                    self._append_upload_failures_note(
                        page_id,
                        upload_failures,
                        "If the studio uses Debugly Shared Folder, the full ZIP for this report was saved there.",
                    )
                    log.warning(
                        "Notion endpoint: Attachments incomplete: uploaded=%s failed=%s "
                        "(see failure note on page and logs for details)",
                        attachments_uploaded,
                        attachments_failed,
                    )
                    if progress_callback:
                        progress_callback(
                            f"Uploaded {attachments_uploaded} file(s); "
                            f"{attachments_failed} failed (see Notion page note)",
                            95,
                            100,
                        )
                else:
                    log.debug("Notion endpoint: All listed attachments uploaded successfully")
                    log.debug(
                        "Notion endpoint: Step 3/3 - Complete! All files uploaded."
                    )
                    if progress_callback:
                        progress_callback("All files uploaded successfully!", 100, 100)
            except Exception as e:
                attachments_ok = False
                log.warning(f"Notion endpoint: Attachment phase failed: {e}")
                # Don't fail the whole submission - page was created successfully

        return {
            "url": page_url,
            "page_id": page_id,
            "attachments_ok": attachments_ok,
            "attachments_uploaded": attachments_uploaded,
            "attachments_failed": attachments_failed,
            "attachment_failures": attachment_failures,
        }

    def _upload_attachments_batch(self, attachments_zip_b64: str, page_id: str, progress_callback=None):
        """
        Upload all attachments in one batch to the server.
        The server will handle the proper Notion API file upload process.
        """
        import base64
        import io
        import zipfile

        log.debug("Notion endpoint: Extracting files from ZIP for batch upload...")

        try:
            # Decode the base64 ZIP
            raw_zip = base64.b64decode(attachments_zip_b64)

            with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as zf:
                # Get list of relevant files including system report
                relevant_files = [
                    zi
                    for zi in zf.infolist()
                    if not zi.is_dir()
                    and (
                        zi.filename.startswith("attachments/")
                        or zi.filename.startswith("screenshot/")
                        or zi.filename.startswith("logs/")
                        or zi.filename == "collected_data.json"
                        or zi.filename == "issue.json"
                    )
                ]

                log.debug(
                    f"Notion endpoint: Found {len(relevant_files)} files to upload in batch"
                )

                relevant_files.sort(key=lambda zi: zi.file_size)

                # Prepare files data for batch upload
                files_data = []
                for i, zi in enumerate(relevant_files):
                    try:
                        # Skip very large files
                        if zi.file_size > 100 * 1024 * 1024:  # 100MB limit
                            log.warning(
                                f"Notion endpoint: Skipping large file {zi.filename} ({zi.file_size} bytes)"
                            )
                            continue

                        # Read file data
                        file_bytes = zf.read(zi)
                        file_b64 = base64.b64encode(file_bytes).decode("utf-8")

                        base_name = zi.filename.split("/")[-1]
                        display_name = _attachment_display_name_from_zip_base(base_name)

                        files_data.append({
                            "filename": display_name,
                            "file_b64": file_b64,
                            "file_size": zi.file_size
                        })

                        # Emit progress update
                        progress = (i + 1) / len(relevant_files) * 50  # 50% for preparation
                        if progress_callback:
                            total_progress = 50 + progress  # 50% + preparation progress
                            progress_callback(f"Preparing {display_name}...", int(total_progress), 100)

                    except Exception as e:
                        log.warning(
                            f"Notion endpoint: Failed to prepare {zi.filename}: {e}"
                        )
                        continue

                # Upload all files in one batch
                if files_data:
                    log.debug(f"Notion endpoint: Uploading {len(files_data)} files in batch...")
                    if progress_callback:
                        progress_callback("Uploading files to Notion...", 75, 100)
                    
                    payload = {
                        "page_id": page_id,
                        "files": files_data
                    }

                    resp = self._post_debugly_notion_route(
                        "notion/upload_attachments", **payload
                    )
                    if hasattr(resp, "status_code") and resp.status_code != 200:
                        raise Exception(
                            f"Server returned status {resp.status_code}"
                        )
                    result = self._rest_response_to_dict(resp) or {}
                    if result.get("success"):
                        log.debug(
                            f"Notion endpoint: Successfully uploaded {result.get('uploaded_count', 0)} files"
                        )
                    else:
                        log.warning(
                            f"Notion endpoint: Batch upload failed: {result.get('error', 'Unknown error')}"
                        )

        except Exception as e:
            log.error(
                f"Notion endpoint: Failed to process ZIP for batch upload: {e}"
            )
            raise

    def _upload_attachments_individually(
        self, attachments_zip_b64: str, page_id: str, progress_callback=None
    ):
        """
        Upload attachments one by one to avoid timeouts.

        Returns:
            (uploaded_file_objs, failure_lines) failure_lines are human-readable for Notion note.
        """
        import base64
        import io
        import zipfile

        log.debug("Notion endpoint: Extracting files from ZIP for individual upload...")
        uploaded_files: List[dict] = []
        failure_lines: List[str] = []

        try:
            # Decode the base64 ZIP
            raw_zip = base64.b64decode(attachments_zip_b64)

            with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as zf:
                # Get list of relevant files including system report
                relevant_files = [
                    zi
                    for zi in zf.infolist()
                    if not zi.is_dir()
                    and (
                        zi.filename.startswith("attachments/")
                        or zi.filename.startswith("screenshot/")
                        or zi.filename.startswith("logs/")
                        or zi.filename == "collected_data.json"
                        or zi.filename == "issue.json"
                    )
                ]

                log.debug(
                    f"Notion endpoint: Found {len(relevant_files)} files to upload individually"
                )

                relevant_files.sort(key=lambda zi: zi.file_size)

                if relevant_files:
                    log.debug(
                        "Notion endpoint: Waiting 2s before first upload "
                        "(Notion API cooldown after page creation)"
                    )
                    time.sleep(2)

                for i, zi in enumerate(relevant_files):
                    try:
                        if i > 0:
                            time.sleep(NOTION_INTER_UPLOAD_DELAY_SEC)
                        # Skip very large files
                        if zi.file_size > 100 * 1024 * 1024:  # 100MB limit
                            log.warning(
                                f"Notion endpoint: Skipping large file {zi.filename} ({zi.file_size} bytes)"
                            )
                            dn_skip = _attachment_display_name_from_zip_base(
                                zi.filename.split("/")[-1]
                            )
                            failure_lines.append(
                                f"{dn_skip}: skipped (exceeds 100MB server limit)"
                            )
                            continue

                        # Read file data
                        file_bytes = zf.read(zi)
                        file_b64 = base64.b64encode(file_bytes).decode("utf-8")

                        base_name = zi.filename.split("/")[-1]
                        display_name = _attachment_display_name_from_zip_base(base_name)

                        log.debug(
                            f"Notion endpoint: Uploading file {i + 1}/{len(relevant_files)}: {display_name}"
                        )

                        result = self._upload_single_attachment(
                            page_id, display_name, file_b64, zi.file_size
                        )

                        if result and result.get("success"):
                            file_obj = {
                                "type": "file_upload",
                                "file_upload": {"id": result["file_id"]},
                                "name": display_name,
                            }
                            uploaded_files.append(file_obj)
                            log.debug(
                                f"Notion endpoint: Added {display_name} to finalization list with ID: {result['file_id'][:8]}..."
                            )
                        else:
                            err = (
                                (result or {}).get("error", "unknown")
                                if isinstance(result, dict)
                                else "unknown"
                            )
                            nd = (
                                (result or {}).get("notion_detail")
                                if isinstance(result, dict)
                                else None
                            )
                            if nd:
                                err = f"{err} | {nd}"
                            failure_lines.append(f"{display_name}: {err}")
                            log.warning(
                                f"Notion endpoint: Upload result for {display_name} was not successful: {result}"
                            )

                        # Emit progress update
                        progress = (i + 1) / len(relevant_files) * 100
                        log.debug(
                            f"Notion endpoint: Upload progress: {progress:.1f}% ({i + 1}/{len(relevant_files)})"
                        )
                        if progress_callback:
                            # Map file upload progress to 50-100% of total progress
                            total_progress = 50 + (progress * 0.5)  # 50% + (file_progress * 0.5)
                            progress_callback(f"Uploading {display_name}...", int(total_progress), 100)

                    except Exception as e:
                        bn = _attachment_display_name_from_zip_base(
                            zi.filename.split("/")[-1]
                        )
                        failure_lines.append(f"{bn}: {e}")
                        log.warning(
                            f"Notion endpoint: Failed to upload {zi.filename}: {e}"
                        )

        except Exception as e:
            log.error(
                f"Notion endpoint: Failed to process ZIP for individual uploads: {e}"
            )
            raise

        return uploaded_files, failure_lines

    def _finalize_attachments(self, page_id: str, uploaded_files: list):
        """Finalize attachments by updating the Notion page with all uploaded files."""
        if not uploaded_files:
            log.debug("Notion endpoint: No files to finalize")
            return
        
        log.debug(f"Notion endpoint: Finalizing {len(uploaded_files)} attachments...")

        try:
            payload = {
                "page_id": page_id,
                "files": uploaded_files,
            }
            resp = self._post_debugly_notion_route(
                "notion/finalize_attachments", **payload
            )
            if hasattr(resp, "status_code") and resp.status_code != 200:
                raise Exception(f"Server returned status {resp.status_code}")
            result = self._rest_response_to_dict(resp) or {}
            if result.get("success"):
                log.debug(
                    f"Notion endpoint: Successfully finalized {result.get('finalized_count', len(uploaded_files))} attachments"
                )
            else:
                log.warning(
                    f"Notion endpoint: Finalization failed: {result.get('error', 'Unknown error')}"
                )

        except Exception as e:
            log.error(f"Notion endpoint: Failed to finalize attachments: {e}")
            raise

    def _upload_single_attachment(
        self, page_id: str, filename: str, file_b64: str, file_size: int
    ):
        """
        Upload one file: small payloads use single JSON post; large use chunked session.
        Retries transient AYON HTTP errors and Notion rate-limit (429) responses.
        """
        try:
            raw = base64.b64decode(file_b64 or "", validate=False)
        except Exception as e:
            return {"error": f"invalid base64: {e}"}

        if len(raw) != int(file_size):
            log.warning(
                "Notion endpoint: decoded size %s != declared file_size %s for %s",
                len(raw),
                file_size,
                filename,
            )

        def _do_small_upload() -> dict:
            payload = {
                "page_id": page_id,
                "filename": filename,
                "file_b64": base64.b64encode(raw).decode("ascii"),
                "file_size": len(raw),
            }
            resp = self._post_debugly_notion_route(
                "notion/upload_attachment", **payload
            )
            if hasattr(resp, "status_code") and resp.status_code != 200:
                detail = ""
                try:
                    if getattr(resp, "text", None):
                        detail = (resp.text or "")[:2500]
                    elif hasattr(resp, "data") and resp.data is not None:
                        detail = str(resp.data)[:2500]
                except Exception:
                    detail = ""
                return {
                    "error": f"Server returned status {resp.status_code}",
                    "notion_detail": detail,
                }
            result = self._rest_response_to_dict(resp)
            return result if isinstance(result, dict) else {"error": "invalid response"}

        use_chunked = len(raw) > UPLOAD_CHUNK_THRESHOLD_BYTES

        last_server_error = ""

        for rate_try in range(3):
            if use_chunked:
                out = self._upload_bytes_chunked_to_server(page_id, filename, raw)
            else:
                out = _do_small_upload()

            if out.get("success"):
                log.debug(
                    "Notion endpoint: Successfully uploaded %s file_id=%s...",
                    filename,
                    (out.get("file_id") or "")[:8],
                )
                return out

            err = str(out.get("error") or "")
            nd = str(out.get("notion_detail") or "").strip()
            if nd:
                last_server_error = f"{err} | {nd}" if err else nd
            elif err:
                last_server_error = err

            # Chunked route returned 405 (routes not deployed) — fall back to
            # direct upload_attachment which lets the server handle multi-part.
            if use_chunked and ("405" in err or "upload_begin failed" in err):
                if len(raw) > 5 * 1024 * 1024:
                    log.warning(
                        "Notion endpoint: chunked routes unavailable and %s is "
                        "%.1f MiB — too large for direct fallback; restart AYON "
                        "server to enable chunked upload routes",
                        filename,
                        len(raw) / (1024 * 1024),
                    )
                    return {
                        "error": (
                            f"File too large ({len(raw) / (1024 * 1024):.1f} MiB) "
                            f"for direct upload; chunked routes unavailable (405). "
                            f"Restart the AYON server to enable chunked uploads."
                        )
                    }
                log.warning(
                    "Notion endpoint: chunked upload_begin unavailable for %s "
                    "(405/not deployed); falling back to direct upload_attachment",
                    filename,
                )
                use_chunked = False
                out = _do_small_upload()
                if out.get("success"):
                    log.debug(
                        "Notion endpoint: Successfully uploaded %s via fallback file_id=%s...",
                        filename,
                        (out.get("file_id") or "")[:8],
                    )
                    return out
                err = str(out.get("error") or "")
                nd_fb = str(out.get("notion_detail") or "").strip()
                if nd_fb:
                    last_server_error = f"{err} | {nd_fb}" if err else nd_fb
                elif err:
                    last_server_error = err

            if "429" in err or "rate" in err.lower() or "403" in err:
                wait_s = 1.5 * (2**rate_try) + random.random() * 0.3
                log.warning(
                    "Notion endpoint: %s on %s, sleeping %.1fs (try %s/3); last_error=%s",
                    "403 forbidden" if "403" in err else "rate limited",
                    filename,
                    wait_s,
                    rate_try + 1,
                    last_server_error[:1200] if last_server_error else err,
                )
                time.sleep(wait_s)
                continue

            if out.get("error"):
                log.warning(
                    "Notion endpoint: Server reported upload error for %s: %s",
                    filename,
                    last_server_error or out.get("error"),
                )
            return out

        log.warning(
            "Notion endpoint: upload retries exhausted for %s; last_error=%s",
            filename,
            (last_server_error or "")[:2000],
        )
        return {
            "error": "upload retries exhausted (rate limit / 403)",
            "notion_detail": (last_server_error or "")[:2500],
        }

    def _build_properties(self, issue: DebuglyIssue) -> Dict[str, Any]:
        """
        Build the properties object for the Notion page based on the database schema

        Args:
            issue: DebuglyIssue object

        Returns:
            Dict containing the page properties
        """
        properties = {}

        # Use cached database properties if available, otherwise fetch them
        if not hasattr(self, "_database_properties"):
            headers = {
                "Authorization": f"Bearer {self.notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": self.notion_version,
            }

            try:
                response = requests.get(
                    f"{self.base_url}/databases/{self.database_id}",
                    headers=headers,
                    timeout=240,
                )

                if response.status_code != 200:
                    log.warning(
                        "Notion endpoint: Could not retrieve database schema, using default properties"
                    )
                    self._database_properties = {}
                else:
                    database_info = response.json()
                    self._database_properties = database_info.get("properties", {})
            except Exception as e:
                log.warning(
                    f"Notion endpoint: Could not retrieve database schema: {e}, using default properties"
                )
                self._database_properties = {}

        database_properties = self._database_properties

        log.debug(
            f"Notion endpoint: Building properties with database properties: {list(database_properties.keys()) if database_properties else 'None'}"
        )

        # Log the full database schema for debugging
        log.debug(f"Notion endpoint: Full database schema: {database_properties}")

        # Title (required field) - always include
        if "Title" in database_properties:
            properties["Title"] = {
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": issue.title[:2000]  # Notion title limit
                        },
                    }
                ]
            }
        else:
            # Fallback to Name if Title doesn't exist
            if "Name" in database_properties:
                properties["Name"] = {
                    "title": [{"type": "text", "text": {"content": issue.title[:2000]}}]
                }
            else:
                # If neither Title nor Name exists, use the first title property
                title_props = [
                    k
                    for k, v in database_properties.items()
                    if v.get("type") == "title"
                ]
                if title_props:
                    properties[title_props[0]] = {
                        "title": [
                            {"type": "text", "text": {"content": issue.title[:2000]}}
                        ]
                    }
                else:
                    # If no title property found, log warning and use a default
                    log.warning(
                        "Notion endpoint: No title property found in database, using 'Title' as fallback"
                    )
                    properties["Title"] = {
                        "title": [
                            {"type": "text", "text": {"content": issue.title[:2000]}}
                        ]
                    }

        # Tags (multi-select)
        if "Tags" in database_properties and hasattr(issue, "tags") and issue.tags:
            properties["Tags"] = {
                "multi_select": [
                    {"name": tag.strip()} for tag in issue.tags if tag.strip()
                ]
            }

        # Short Description (rich_text) - Skip this field as it's not needed
        # if "Short Description" in database_properties and issue.user_message:
        #     properties["Short Description"] = {
        #         "rich_text": [
        #             {
        #                 "type": "text",
        #                 "text": {
        #                     "content": issue.user_message[:2000]  # Notion text limit
        #                 }
        #             }
        #         ]
        #     }

        # Status (select) - try to find a valid status option
        if "Status" in database_properties:
            status_prop = database_properties["Status"]
            if status_prop.get("type") == "select":
                # Get available options from the database schema
                status_options = status_prop.get("select", {}).get("options", [])
                if status_options:
                    # Try to find "Backlog" as the default status
                    default_status = None
                    for option in status_options:
                        option_name = option.get("name", "")
                        if option_name == "Backlog":
                            default_status = option["name"]
                            break

                    # If no suitable status found, use the first available option
                    if not default_status and status_options:
                        default_status = status_options[0]["name"]

                    if default_status:
                        properties["Status"] = {"select": {"name": default_status}}
                        log.debug(f"Notion endpoint: Using status: {default_status}")
                    else:
                        log.warning(
                            "Notion endpoint: No valid status options found, skipping Status property"
                        )
                else:
                    log.warning(
                        "Notion endpoint: Status property has no options defined, skipping Status property"
                    )
            else:
                log.warning(
                    f"Notion endpoint: Status property is not a select type (found: {status_prop.get('type')}), skipping Status property"
                )
        else:
            log.debug(
                "Notion endpoint: Status property not found in database schema, skipping Status property"
            )

        # Priority (select) - try to find a valid priority option
        if "Priority" in database_properties:
            priority_prop = database_properties["Priority"]
            if priority_prop.get("type") == "select":
                # Get available options from the database schema
                priority_options = priority_prop.get("select", {}).get("options", [])
                if priority_options:
                    # Try to find a suitable default priority
                    default_priority = None
                    for option in priority_options:
                        option_name = option.get("name", "").lower()
                        if any(
                            keyword in option_name
                            for keyword in ["P0", "P1", "P2", "P3"]
                        ):
                            default_priority = option["name"]
                            break

                    # If no suitable priority found, use the first available option
                    if not default_priority and priority_options:
                        default_priority = priority_options[0]["name"]

                    if default_priority:
                        properties["Priority"] = {"select": {"name": default_priority}}
                        log.debug(
                            f"Notion endpoint: Using priority: {default_priority}"
                        )
                    else:
                        log.warning(
                            "Notion endpoint: No valid priority options found, skipping Priority property"
                        )
                else:
                    log.warning(
                        "Notion endpoint: Priority property has no options defined, skipping Priority property"
                    )
            else:
                log.warning(
                    f"Notion endpoint: Priority property is not a select type (found: {priority_prop.get('type')}), skipping Priority property"
                )
        else:
            log.debug(
                "Notion endpoint: Priority property not found in database schema, skipping Priority property"
            )

        # Assign (people) - can be set via settings
        if "Assign" in database_properties and self.assignee_id:
            properties["Assign"] = {"people": [{"id": self.assignee_id}]}

        # Submitted By (people) - set to the current user's Ayon full name
        if "Submitted By" in database_properties:
            log.debug("Notion endpoint: Processing Submitted By field")
            log.debug(
                f"Notion endpoint: Submitted By field schema: {database_properties['Submitted By']}"
            )
        else:
            # Check for similar field names
            similar_fields = [
                key
                for key in database_properties.keys()
                if "submitted" in key.lower() or "by" in key.lower()
            ]
            log.debug(
                f"Notion endpoint: Submitted By field not found. Similar fields: {similar_fields}"
            )
            log.debug(
                f"Notion endpoint: All database properties: {list(database_properties.keys())}"
            )

        if "Submitted By" in database_properties:
            # First, list all users in the workspace for debugging
            log.debug("Notion endpoint: Listing all users in workspace...")
            all_users = self._list_all_users()

            # Log all available users for debugging
            if all_users:
                log.debug(
                    f"Notion endpoint: Found {len(all_users)} users in workspace:"
                )
                for i, user in enumerate(all_users):
                    user_id = user.get("id", "No ID")
                    user_name = user.get("name", "No name")
                    user_type = user.get("type", "No type")
                    user_email = user.get("person", {}).get("email", "No email")
                    log.debug(
                        f"Notion endpoint: User {i + 1}: ID='{user_id}', Name='{user_name}', Type='{user_type}', Email='{user_email}'"
                    )
            else:
                log.warning("Notion endpoint: No users found in workspace")

            # Get user's Ayon full name from collected data
            user_full_name = None
            user_email = None
            user_username = None

            if hasattr(issue, "collected_data") and issue.collected_data:
                # Try to find user data with case-insensitive search
                user_data = None
                for key in issue.collected_data.keys():
                    if key.lower() == "user":
                        user_data = issue.collected_data[key]
                        break

                if not user_data:
                    log.debug(
                        f"Notion endpoint: No user data found in collected_data. Available keys: {list(issue.collected_data.keys())}"
                    )
                    user_data = {}
                else:
                    log.debug(
                        f"Notion endpoint: User data from collected_data: {user_data}"
                    )

                # The user data is nested - extract from the inner 'user' key
                if isinstance(user_data, dict) and "user" in user_data:
                    user_data = user_data["user"]
                    log.debug(
                        f"Notion endpoint: Extracted nested user data: {user_data}"
                    )

                user_full_name = user_data.get("ayon_full_name")
                user_email = user_data.get("ayon_email")
                user_username = user_data.get("ayon_username")

                log.debug(
                    f"Notion endpoint: Extracted user info - Full Name: '{user_full_name}', Email: '{user_email}', Username: '{user_username}'"
                )
            else:
                log.debug("Notion endpoint: No collected_data found in issue")

            # Use email directly - it's unique and we have it
            if user_email and user_email != "unknown":
                log.debug(
                    f"Notion endpoint: Searching for user by email: '{user_email}'"
                )

                # Search in the workspace users list directly instead of using the search API
                user_id = None
                for user in all_users:
                    user_email_in_workspace = user.get("person", {}).get("email", "")
                    if user_email_in_workspace == user_email:
                        user_id = user.get("id")
                        log.debug(
                            f"Notion endpoint: Found user by email '{user_email}' with ID: {user_id}"
                        )
                        break

                if not user_id:
                    log.warning(
                        f"Notion endpoint: User with email '{user_email}' not found in Notion workspace"
                    )
            else:
                log.warning("Notion endpoint: No valid email found in user data")
                user_id = None

            if user_id:
                # Get the full user object from the search results
                user_object = None
                for user in all_users:
                    if user.get("id") == user_id:
                        user_object = user
                        break

                # Try the canonical Notion API approach for people fields
                # According to the API docs, we should use just the ID
                submitted_by_value = {"people": [{"id": user_id}]}
                properties["Submitted By"] = submitted_by_value
                log.debug(
                    f"Notion endpoint: Set Submitted By to user: {user_email} (ID: {user_id})"
                )
                log.debug(
                    f"Notion endpoint: Submitted By property value: {submitted_by_value}"
                )
                log.debug(
                    f"Notion endpoint: User details - Name: '{user_email}', ID: '{user_id}'"
                )

                # Also log the full user object for debugging
                if user_object:
                    log.debug(f"Notion endpoint: Full user object: {user_object}")

                    # Try alternative format as backup (some integrations require full object)
                    alternative_value = {
                        "people": [
                            {
                                "object": "user",
                                "id": user_id,
                                "type": "person",
                                "name": user_object.get("name", user_email),
                            }
                        ]
                    }
                    log.debug(
                        f"Notion endpoint: Alternative Submitted By value: {alternative_value}"
                    )
            else:
                log.warning(
                    f"Notion endpoint: Could not find user with email '{user_email}' in Notion workspace"
                )
                log.debug(f"Notion endpoint: Available users in workspace: {all_users}")
        else:
            log.debug(
                "Notion endpoint: Submitted By field not found in database schema"
            )

        # Attachments (files) - we'll handle this after page creation
        if "Attachments" in database_properties:
            log.debug("Notion endpoint: Attachments field found in database schema")
        else:
            log.debug("Notion endpoint: Attachments field not found in database schema")

        # Created Time (date) - will be automatically set by Notion

        log.debug(f"Notion endpoint: Final properties: {properties}")

        # Log each property being set for debugging
        for prop_name, prop_value in properties.items():
            log.debug(f"Notion endpoint: Setting property '{prop_name}': {prop_value}")

        # Specifically log the Submitted By property if it exists
        if "Submitted By" in properties:
            log.debug(
                f"Notion endpoint: Submitted By property is set to: {properties['Submitted By']}"
            )
        else:
            log.debug(
                "Notion endpoint: Submitted By property is NOT set in final properties"
            )

        return properties

    def _clean_user_message(self, message: str) -> str:
        """
        Clean the user message to remove CSS and other unwanted content

        Args:
            message: Raw user message

        Returns:
            Cleaned message
        """
        if not message:
            return message

        # Remove CSS blocks
        import re

        # Remove CSS blocks that start with p, li { and end with }
        css_pattern = r"p,\s*li\s*\{[^}]*\}\s*hr\s*\{[^}]*\}\s*li\.unchecked::marker\s*\{[^}]*\}\s*li\.checked::marker\s*\{[^}]*\}"
        cleaned = re.sub(css_pattern, "", message, flags=re.DOTALL)

        # Remove any remaining CSS-like content
        css_like_pattern = r"[a-z-]+\s*\{[^}]*\}"
        cleaned = re.sub(css_like_pattern, "", cleaned, flags=re.DOTALL)

        # Clean up extra whitespace
        cleaned = re.sub(
            r"\n\s*\n\s*\n", "\n\n", cleaned
        )  # Remove excessive line breaks
        cleaned = cleaned.strip()

        log.debug(
            f"Notion endpoint: Cleaned message from {len(message)} to {len(cleaned)} characters"
        )

        return cleaned

    def _parse_markdown_to_rich_text(self, markdown_text: str) -> List[Dict[str, Any]]:
        """
        Parse markdown text and convert to Notion rich text format

        Args:
            markdown_text: Markdown text to parse

        Returns:
            List of rich text objects for Notion
        """
        import re

        tokens: List[Dict[str, Any]] = []
        text = markdown_text
        # Parse links first to keep them intact
        link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
        last = 0
        for m in re.finditer(link_pattern, text):
            before = text[last : m.start()]
            if before:
                tokens.extend(self._tokenize_annotations(before))
            label = m.group(1)
            url = m.group(2)
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            tokens.append(
                {
                    "type": "text",
                    "text": {"content": label, "link": {"url": url}},
                    "annotations": {},
                }
            )
            last = m.end()
        tail = text[last:]
        if tail:
            tokens.extend(self._tokenize_annotations(tail))

        # If no links were found, still parse annotations across the whole text
        if last == 0 and (not tokens):
            tokens.extend(self._tokenize_annotations(text))

        # Convert tokens to Notion rich_text objects
        if not tokens:
            return [{"type": "text", "text": {"content": markdown_text}}]
        out: List[Dict[str, Any]] = []
        for t in tokens:
            obj = {"type": "text", "text": t["text"]}
            anns = t.get("annotations") or {}
            if anns:
                obj["annotations"] = anns
            out.append(obj)
        return out

    def _tokenize_annotations(self, segment: str) -> List[Dict[str, Any]]:
        """Tokenize bold (**..**), underline (<U>..</U>), strikethrough (~~..~~).
        Returns list of {text: {content}, annotations:{...}} tokens.
        """
        import re

        tokens: List[Dict[str, Any]] = []
        s = segment
        while s:
            b = re.search(r"\*\*([^*]+)\*\*", s)
            u = re.search(r"<U>([\s\S]*?)</U>", s)
            st = re.search(r"~~([^~]+)~~", s)
            matches = (
                [(m.start(), "b", m) for m in [b] if m]
                + [(m.start(), "u", m) for m in [u] if m]
                + [(m.start(), "s", m) for m in [st] if m]
            )
            if not matches:
                if s:
                    tokens.append(
                        {"type": "text", "text": {"content": s}, "annotations": {}}
                    )
                break
            matches.sort(key=lambda t: t[0])
            idx, tag, m = matches[0]
            if idx > 0:
                tokens.append(
                    {"type": "text", "text": {"content": s[:idx]}, "annotations": {}}
                )
            content = m.group(1)
            anns = (
                {"bold": True}
                if tag == "b"
                else ({"underline": True} if tag == "u" else {"strikethrough": True})
            )
            tokens.append(
                {"type": "text", "text": {"content": content}, "annotations": anns}
            )
            s = s[m.end() :]
        return tokens

    def _markdown_to_blocks(self, text: str) -> List[Dict[str, Any]]:
        """Convert a small markdown subset into Notion blocks.

        Supports: #/##/###, --- (divider), > quote, - bullets, 1. numbered, paragraphs with links.
        """
        import re

        blocks: List[Dict[str, Any]] = []
        if not text:
            return blocks

        lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            stripped = line.lstrip()
            if not line:
                i += 1
                continue

            # Headings
            if stripped.startswith("### "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": self._parse_markdown_to_rich_text(
                                stripped[4:]
                            ),
                        },
                    }
                )
                i += 1
                continue
            if stripped.startswith("## "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": self._parse_markdown_to_rich_text(
                                stripped[3:]
                            ),
                        },
                    }
                )
                i += 1
                continue
            if stripped.startswith("# "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_1",
                        "heading_1": {
                            "rich_text": self._parse_markdown_to_rich_text(
                                stripped[2:]
                            ),
                        },
                    }
                )
                i += 1
                continue

            # Divider
            if re.fullmatch(r"\s*---\s*", stripped):
                blocks.append({"object": "block", "type": "divider", "divider": {}})
                i += 1
                continue

            # Quote
            if line.lstrip().startswith("> "):
                quote_text = line.lstrip()[2:]
                blocks.append(
                    {
                        "object": "block",
                        "type": "quote",
                        "quote": {
                            "rich_text": self._parse_markdown_to_rich_text(quote_text)
                        },
                    }
                )
                i += 1
                continue

            # Bulleted list
            if stripped.startswith("- "):
                while i < len(lines) and lines[i].lstrip().startswith("- "):
                    item_text = lines[i].lstrip()[2:]
                    if not item_text.strip():
                        i += 1
                        continue
                    blocks.append(
                        {
                            "object": "block",
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": self._parse_markdown_to_rich_text(
                                    item_text
                                )
                            },
                        }
                    )
                    i += 1
                continue

            # Numbered list
            if re.match(r"\s*\d+\.\s*", stripped):
                while i < len(lines) and re.match(r"\s*\d+\.\s*", lines[i].lstrip()):
                    item_text = re.sub(r"^\s*\d+\.\s*", "", lines[i].lstrip())
                    if not item_text.strip():
                        i += 1
                        continue
                    blocks.append(
                        {
                            "object": "block",
                            "type": "numbered_list_item",
                            "numbered_list_item": {
                                "rich_text": self._parse_markdown_to_rich_text(
                                    item_text
                                )
                            },
                        }
                    )
                    i += 1
                continue

            # Paragraph - collect until blank line
            para_lines = [stripped]
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                para_lines.append(lines[i].lstrip())
                i += 1
            para_text = "\n".join(para_lines)
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": self._parse_markdown_to_rich_text(para_text)
                    },
                }
            )

        return blocks

    def _build_content_blocks(self, issue: DebuglyIssue) -> List[Dict[str, Any]]:
        """
        Build the content blocks for the Notion page

        Args:
            issue: DebuglyIssue object

        Returns:
            List of block objects
        """
        blocks = []

        # Add detailed description
        if issue.user_message:
            # Log the user message content for debugging
            log.debug(
                f"Notion endpoint: User message content: {issue.user_message[:200]}..."
            )

            # Clean the user message to remove any CSS or unwanted content
            cleaned_message = self._clean_user_message(issue.user_message)

            # Add the cleaned user message as a paragraph with markdown parsing
            rich_text_blocks = self._parse_markdown_to_rich_text(cleaned_message)
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": rich_text_blocks},
                }
            )

        # Add collected data
        if issue.collected_data:
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [
                            {"type": "text", "text": {"content": "Collected Data"}}
                        ]
                    },
                }
            )

            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "System information, environment variables, and collected data are available in the attached JSON file."
                                },
                            }
                        ]
                    },
                }
            )

        # Note: Attachments are handled separately via the Attachments field in the database
        # Note: Timestamp is automatically handled by Notion's Created Time field

        return blocks

    def _upload_attachments_to_page(self, issue: DebuglyIssue, page_id: str):
        """
        Upload all attachments and add them to the Attachments field

        Args:
            issue: DebuglyIssue object
            page_id: ID of the Notion page to upload files to
        """
        # Check if Attachments field exists in database schema
        if (
            not hasattr(self, "_database_properties")
            or "Attachments" not in self._database_properties
        ):
            log.debug(
                "Notion endpoint: No Attachments field found, skipping file upload"
            )
            return

        all_attachments = self.get_safe_attachments(issue)

        if not all_attachments:
            return

        log.debug(
            f"Notion endpoint: Uploading {len(all_attachments)} attachments to page {page_id}"
        )

        uploaded_files = []
        for attachment_path in all_attachments:
            try:
                if os.path.exists(attachment_path):
                    # Upload the file and get the ID
                    file_id = self.upload_file(attachment_path, page_id)
                    log.debug(
                        f"Notion endpoint: Successfully uploaded {os.path.basename(attachment_path)}: {file_id}"
                    )

                    # Ensure .log files are displayed with .txt extension in Notion
                    base_name = os.path.basename(attachment_path)
                    name_root, name_ext = os.path.splitext(base_name)
                    display_name = (
                        f"{name_root}.txt" if name_ext.lower() == ".log" else base_name
                    )

                    # Add to the list of uploaded files using file_upload type
                    uploaded_files.append(
                        {
                            "type": "file_upload",
                            "file_upload": {"id": file_id},
                            "name": display_name,
                        }
                    )
                else:
                    log.warning(
                        f"Notion endpoint: Attachment file not found: {attachment_path}"
                    )
            except Exception as e:
                log.warning(f"Notion endpoint: Failed to upload {attachment_path}: {e}")

        # Update the page with the uploaded files in the Attachments field
        if uploaded_files:
            self._update_page_attachments(page_id, uploaded_files)

    def _update_page_attachments(self, page_id: str, uploaded_files: list):
        """
        Update the page's Attachments field with the uploaded files

        Args:
            page_id: ID of the Notion page
            uploaded_files: List of file objects to add to the Attachments field
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

        data = {"properties": {"Attachments": {"files": uploaded_files}}}

        response = requests.patch(
            f"{self.base_url}/pages/{page_id}", headers=headers, json=data
        )

        if response.status_code != 200:
            log.warning(
                f"Notion endpoint: Failed to update Attachments field: {response.status_code} - {response.text}"
            )
        else:
            log.debug(
                f"Notion endpoint: Successfully updated Attachments field with {len(uploaded_files)} files"
            )

    def _add_file_block_to_page(self, page_id: str, file_url: str, file_name: str):
        """
        Add a file block to a Notion page

        Args:
            page_id: ID of the Notion page
            file_url: URL of the uploaded file
            file_name: Name of the file
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

        # Create a file block (Notion API 2026-03-11: use position, not deprecated after)
        block_data = {
            "position": {"type": "end"},
            "children": [
                {
                    "object": "block",
                    "type": "file",
                    "file": {"type": "external", "external": {"url": file_url}},
                }
            ],
        }

        response = requests.patch(
            f"{self.base_url}/blocks/{page_id}/children",
            headers=headers,
            json=block_data,
        )

        if response.status_code != 200:
            log.warning(
                f"Notion endpoint: Failed to add file block for {file_name}: {response.status_code} - {response.text}"
            )
        else:
            log.debug(f"Notion endpoint: Successfully added file block for {file_name}")

    def _validate_database_schema(self):
        """
        Validate that the database exists and has the required properties
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

        try:
            response = requests.get(
                f"{self.base_url}/databases/{self.database_id}",
                headers=headers,
                timeout=240,
            )

            if response.status_code != 200:
                log.warning(
                    f"Notion endpoint: Failed to retrieve database schema - {response.status_code}: {response.text}"
                )
                return

            database_info = response.json()
            properties = database_info.get("properties", {})

            # Cache the database properties for later use
            self._database_properties = properties

            log.debug(
                f"Notion endpoint: Database properties: {list(properties.keys())}"
            )

            # Check for required properties
            required_properties = ["Title"]
            missing_properties = []

            for prop in required_properties:
                if prop not in properties:
                    missing_properties.append(prop)

            if missing_properties:
                log.warning(
                    f"Notion endpoint: Missing required properties: {missing_properties}"
                )

            # Log all available properties for debugging
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get("type", "unknown")
                log.debug(
                    f"Notion endpoint: Property '{prop_name}' is of type '{prop_type}'"
                )

        except Exception as e:
            log.warning(f"Notion endpoint: Database validation failed: {e}")
            return

    def upload_file(self, file_path: str, page_id: str) -> str:
        """
        Upload a file to Notion using the Direct Upload method (3-step process)

        Args:
            file_path: Path to the file to upload
            page_id: ID of the Notion page to attach the file to

        Returns:
            str: ID of the uploaded file
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Get file info
        file_name = os.path.basename(file_path)
        file_extension = os.path.splitext(file_name)[1].lower()

        # Rename .log files to .txt for Notion compatibility
        if file_extension == ".log":
            file_name = file_name.replace(".log", ".txt")
            file_extension = ".txt"

        # Determine content type based on file extension
        content_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".json": "application/json",
        }

        content_type = content_type_map.get(file_extension, "text/plain")

        # Step 1: Create a File Upload object
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

        create_data = {"filename": file_name, "content_type": content_type}

        response = requests.post(
            f"{self.base_url}/file_uploads", headers=headers, json=create_data
        )

        if response.status_code != 200:
            log.error(
                f"Notion endpoint: Failed to create file upload - {response.status_code}: {response.text}"
            )
            raise Exception(
                f"Failed to create file upload: {response.status_code} - {response.text}"
            )

        upload_info = response.json()
        file_upload_id = upload_info["id"]
        upload_url = upload_info["upload_url"]

        log.debug(
            f"Notion endpoint: Created file upload {file_upload_id} for {file_name}"
        )

        # Step 2: Upload file contents
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, content_type)}

            file_response = requests.post(
                upload_url,
                headers={
                    "Authorization": f"Bearer {self.notion_token}",
                    "Notion-Version": self.notion_version,
                },
                files=files,
            )

        if file_response.status_code != 200:
            log.error(
                f"Notion endpoint: Failed to upload file content - {file_response.status_code}: {file_response.text}"
            )
            raise Exception(
                f"Failed to upload file content: {file_response.status_code}"
            )

        log.debug(
            f"Notion endpoint: Successfully uploaded file content for {file_name}"
        )

        return file_upload_id

    def _get_or_create_user_id(self, search_term: str) -> str:
        """
        Get a user ID for the given search term in Notion

        Args:
            search_term: The search term (name, email, or username)

        Returns:
            str: The user ID, or None if not found
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

        try:
            log.debug(f"Notion endpoint: Searching for user with term: '{search_term}'")

            # First, try to search for existing users
            search_url = f"{self.base_url}/users/search"
            search_data = {
                "query": search_term,
                "filter": {"value": "person", "property": "object"},
            }

            log.debug(
                f"Notion endpoint: Searching for user with query: '{search_term}'"
            )
            log.debug(f"Notion endpoint: Search URL: {search_url}")
            log.debug(f"Notion endpoint: Search data: {search_data}")

            response = requests.post(
                search_url, headers=headers, json=search_data, timeout=240
            )

            if response.status_code == 200:
                users = response.json().get("results", [])
                log.debug(
                    f"Notion endpoint: Found {len(users)} users in search results"
                )

                # Log all found users for debugging
                for i, user in enumerate(users):
                    user_name = user.get("name", "Unknown")
                    user_email = user.get("person", {}).get("email", "No email")
                    user_id = user.get("id", "No ID")
                    log.debug(
                        f"Notion endpoint: User {i + 1}: Name='{user_name}', Email='{user_email}', ID='{user_id}'"
                    )

                # Look for exact name match first
                for user in users:
                    user_name = user.get("name", "")
                    if user_name == search_term:
                        user_id = user.get("id")
                        log.debug(
                            f"Notion endpoint: Found exact name match '{search_term}' with ID: {user_id}"
                        )

                        # Validate the user ID format
                        if user_id and len(user_id) == 36 and user_id.count("-") == 4:
                            log.debug(
                                f"Notion endpoint: User ID '{user_id}' appears to be a valid UUID"
                            )
                        else:
                            log.warning(
                                f"Notion endpoint: User ID '{user_id}' may not be a valid UUID"
                            )

                        # Also validate that the user is of type "person"
                        user_type = user.get("type", "")
                        if user_type == "person":
                            log.debug(
                                f"Notion endpoint: User '{search_term}' is a person type user"
                            )
                        else:
                            log.warning(
                                f"Notion endpoint: User '{search_term}' is not a person type (type: {user_type})"
                            )

                        return user_id

                # Look for exact email match
                for user in users:
                    user_email = user.get("person", {}).get("email", "")
                    if user_email == search_term:
                        user_id = user.get("id")
                        log.debug(
                            f"Notion endpoint: Found exact email match '{search_term}' with ID: {user_id}"
                        )
                        return user_id

                log.debug(
                    f"Notion endpoint: No matching user found for '{search_term}'"
                )
            else:
                log.warning(
                    f"Notion endpoint: User search failed with status {response.status_code}: {response.text}"
                )

            # If no user found, we cannot create users via API
            # Notion doesn't allow creating users through the API
            log.warning(
                f"Notion endpoint: User '{search_term}' not found in workspace. Users must be manually added to the workspace."
            )
            return None

        except Exception as e:
            log.warning(
                f"Notion endpoint: Error searching for user '{search_term}': {e}"
            )
            return None

    def _list_all_users(self):
        """
        List all users in the Notion workspace for debugging purposes
        """
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

        try:
            # Get all users in the workspace
            response = requests.get(
                f"{self.base_url}/users", headers=headers, timeout=240
            )

            if response.status_code == 200:
                users = response.json().get("results", [])
                log.debug(
                    f"Notion endpoint: Found {len(users)} total users in workspace"
                )

                for i, user in enumerate(users):
                    user_name = user.get("name", "Unknown")
                    user_email = user.get("person", {}).get("email", "No email")
                    user_id = user.get("id", "No ID")
                    user_type = user.get("type", "Unknown")
                    log.debug(
                        f"Notion endpoint: User {i + 1}: Name='{user_name}', Email='{user_email}', ID='{user_id}', Type='{user_type}'"
                    )

                return users
            else:
                log.warning(
                    f"Notion endpoint: Failed to list users - {response.status_code}: {response.text}"
                )
                return []

        except Exception as e:
            log.warning(f"Notion endpoint: Error listing users: {e}")
            return []

    def get_success_info(self, result):
        """
        Get Notion-specific success information to display to the user

        Args:
            result: The result returned by the submit method (dict with url and page_id)

        Returns:
            dict: Dictionary containing success information
        """
        if isinstance(result, dict) and "url" in result:
            ok = result.get("attachments_ok", True)
            up = int(result.get("attachments_uploaded") or 0)
            fail = int(result.get("attachments_failed") or 0)
            if ok is False:
                if fail > 0:
                    total = up + fail
                    msg = (
                        f"Notion page created, but only {up} of {total} attachment(s) "
                        f"uploaded ({fail} failed). Open the page for details or check logs."
                    )
                else:
                    msg = (
                        "Notion page created, but the attachment phase did not finish. "
                        "See client logs."
                    )
            else:
                msg = "Issue successfully created in Notion database"
            return {
                "title": "Notion",
                "message": msg,
                "url": result["url"],
                "file_path": None,
                "can_open": True,
            }
        else:
            # Fallback for old format
            return {
                "title": "Notion",
                "message": "Issue successfully created in Notion database",
                "url": result if isinstance(result, str) else None,
                "file_path": None,
                "can_open": True,
            }
