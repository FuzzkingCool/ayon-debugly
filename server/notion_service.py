import base64
import html as _html
import io
import threading
import zipfile
from typing import Any, Dict, Optional

import requests

# Use nxtools logging if available, otherwise use standard logging
try:
    from nxtools import logging as log
except ImportError:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    log = logging.getLogger(__name__)


def _notion_ids_equal(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return str(a).replace("-", "").lower() == str(b).replace("-", "").lower()


# Notion File Upload API: single_part for <= 20 MiB; multi_part + complete above that.
# See https://developers.notion.com/guides/data-apis/sending-larger-files
NOTION_SINGLE_PART_MAX_BYTES = 20 * 1024 * 1024
NOTION_MULTIPART_CHUNK_BYTES = 10 * 1024 * 1024
NOTION_MULTIPART_MAX_PARTS = 1000


def _notion_json_headers(token: str, notion_version: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": notion_version,
    }


def _notion_send_headers(token: str, notion_version: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version,
    }


def _log_notion_http_error(operation: str, response: "requests.Response") -> None:
    log.error(
        "Notion %s failed: status=%s body=%s",
        operation,
        response.status_code,
        response.text,
    )


def _notion_raise_for_status(operation: str, response: "requests.Response") -> None:
    """Raise RuntimeError with full Notion response body (403/400 diagnostics)."""
    if response.status_code < 400:
        return
    _log_notion_http_error(operation, response)
    body = (response.text or "").strip()
    if len(body) > 2500:
        body = body[:2500] + "…"
    raise RuntimeError(f"{operation}: HTTP {response.status_code} {body}")


def upload_file_bytes_to_notion(
    *,
    token: str,
    notion_version: str,
    file_name: str,
    content_type: str,
    file_bytes: bytes,
    base_url: str = "https://api.notion.com/v1",
    upload_timeout: int = 600,
) -> str:
    """
    Upload bytes to Notion using the File Upload API.

    Uses single_part for total size <= NOTION_SINGLE_PART_MAX_BYTES; otherwise
    multi_part with NOTION_MULTIPART_CHUNK_BYTES chunks, then complete.
    Logs full error response bodies for diagnostics.
    """
    base_url = (base_url or "https://api.notion.com/v1").rstrip("/")
    file_size = len(file_bytes)
    log.debug("Notion upload: %s (%s bytes) content_type=%s", file_name, file_size, content_type)

    if file_size > NOTION_SINGLE_PART_MAX_BYTES:
        return _upload_file_bytes_multipart(
            token=token,
            notion_version=notion_version,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
            base_url=base_url,
            upload_timeout=upload_timeout,
        )
    return _upload_file_bytes_single_part(
        token=token,
        notion_version=notion_version,
        file_name=file_name,
        content_type=content_type,
        file_bytes=file_bytes,
        base_url=base_url,
        upload_timeout=upload_timeout,
    )


def _upload_file_bytes_single_part(
    *,
    token: str,
    notion_version: str,
    file_name: str,
    content_type: str,
    file_bytes: bytes,
    base_url: str,
    upload_timeout: int,
) -> str:
    file_size = len(file_bytes)
    # Omit explicit mode: default is single_part per Notion OpenAPI / small-file guide.
    create_payload = {
        "filename": file_name,
        "content_type": content_type,
    }
    try:
        resp = requests.post(
            f"{base_url}/file_uploads",
            headers=_notion_json_headers(token, notion_version),
            json=create_payload,
            timeout=(30, upload_timeout),
        )
        _notion_raise_for_status("POST /file_uploads (single_part) create", resp)
        info = resp.json()
        file_upload_id = info["id"]
        upload_url = info.get("upload_url") or (
            f"{base_url}/file_uploads/{file_upload_id}/send"
        )
        log.debug(
            "Notion single_part: created upload %s... url_host=%s",
            file_upload_id[:8],
            upload_url.split("/")[2] if upload_url and "/" in upload_url else "?",
        )
    except Exception as e:
        log.error("Notion single_part: create failed for %s: %s", file_name, e)
        raise

    import time as _time

    last_exc: Optional[Exception] = None
    for send_attempt in range(3):
        if send_attempt > 0:
            backoff = 2.0 * send_attempt
            log.warning(
                "Notion single_part: retrying send for %s (attempt %s/3) after %.1fs backoff",
                file_name,
                send_attempt + 1,
                backoff,
            )
            _time.sleep(backoff)
            # Re-create the file_upload object — previous one may be tainted after 403
            try:
                resp = requests.post(
                    f"{base_url}/file_uploads",
                    headers=_notion_json_headers(token, notion_version),
                    json=create_payload,
                    timeout=(30, upload_timeout),
                )
                _notion_raise_for_status("POST /file_uploads (single_part) re-create", resp)
                info = resp.json()
                file_upload_id = info["id"]
                upload_url = info.get("upload_url") or (
                    f"{base_url}/file_uploads/{file_upload_id}/send"
                )
                log.debug(
                    "Notion single_part: re-created upload %s... for retry",
                    file_upload_id[:8],
                )
            except Exception as e:
                log.error("Notion single_part: re-create failed for %s: %s", file_name, e)
                raise

        try:
            log.debug(
                "Notion single_part: sending %s bytes timeout=%ss (attempt %s/3)",
                file_size,
                upload_timeout,
                send_attempt + 1,
            )
            files = {"file": (file_name, file_bytes, content_type)}
            resp2 = requests.post(
                upload_url,
                headers=_notion_send_headers(token, notion_version),
                files=files,
                timeout=(30, upload_timeout),
            )
            if resp2.status_code == 403 and send_attempt < 2:
                body = (resp2.text or "")[:500]
                log.warning(
                    "Notion single_part: 403 on send for %s (attempt %s/3): %s",
                    file_name,
                    send_attempt + 1,
                    body,
                )
                last_exc = RuntimeError(
                    f"file send (single_part): HTTP 403 {body}"
                )
                continue
            _notion_raise_for_status("file send (single_part)", resp2)
            sent = resp2.json() if resp2.content else {}
            st = sent.get("status")
            if st and st != "uploaded":
                log.warning(
                    "Notion file upload status not 'uploaded' for %s: %r snapshot=%s",
                    file_name,
                    st,
                    {k: sent.get(k) for k in ("id", "status", "filename") if k in sent},
                )
            log.debug("Notion single_part: done %s", file_name)
            return file_upload_id
        except requests.exceptions.Timeout as e:
            log.error("Notion single_part: upload timeout for %s: %s", file_name, e)
            raise Exception(f"File upload timeout for {file_name}") from e
        except Exception as e:
            if send_attempt < 2 and "403" in str(e):
                last_exc = e
                continue
            log.error("Notion single_part: send failed for %s: %s", file_name, e)
            raise

    log.error("Notion single_part: all send attempts exhausted for %s", file_name)
    raise last_exc or RuntimeError(f"File upload send failed for {file_name}")


def _upload_file_bytes_multipart(
    *,
    token: str,
    notion_version: str,
    file_name: str,
    content_type: str,
    file_bytes: bytes,
    base_url: str,
    upload_timeout: int,
) -> str:
    file_size = len(file_bytes)
    chunk = NOTION_MULTIPART_CHUNK_BYTES
    number_of_parts = (file_size + chunk - 1) // chunk if file_size else 1
    if number_of_parts > NOTION_MULTIPART_MAX_PARTS:
        raise ValueError(
            f"File {file_name!r} needs {number_of_parts} parts; "
            f"Notion allows at most {NOTION_MULTIPART_MAX_PARTS}"
        )

    create_payload: dict[str, Any] = {
        "mode": "multi_part",
        "number_of_parts": number_of_parts,
        "filename": file_name,
        "content_type": content_type,
    }
    try:
        resp = requests.post(
            f"{base_url}/file_uploads",
            headers=_notion_json_headers(token, notion_version),
            json=create_payload,
            timeout=(30, upload_timeout),
        )
        _notion_raise_for_status("POST /file_uploads (multi_part) create", resp)
        info = resp.json()
        file_upload_id = info["id"]
        upload_url = info.get("upload_url") or (
            f"{base_url}/file_uploads/{file_upload_id}/send"
        )
        complete_url = info.get("complete_url") or (
            f"{base_url}/file_uploads/{file_upload_id}/complete"
        )
        log.debug(
            "Notion multi_part: created upload %s... parts=%s upload_host=%s",
            file_upload_id[:8],
            number_of_parts,
            upload_url.split("/")[2] if upload_url and "/" in upload_url else "?",
        )
    except Exception as e:
        log.error("Notion multi_part: create failed for %s: %s", file_name, e)
        raise

    try:
        for part_index in range(number_of_parts):
            start = part_index * chunk
            end = min(start + chunk, file_size)
            part_bytes = file_bytes[start:end]
            part_no = part_index + 1
            log.debug(
                "Notion multi_part: sending part %s/%s (%s bytes)",
                part_no,
                number_of_parts,
                len(part_bytes),
            )
            resp2 = requests.post(
                upload_url,
                headers=_notion_send_headers(token, notion_version),
                files={"file": (file_name, part_bytes, content_type)},
                data={"part_number": str(part_no)},
                timeout=(30, upload_timeout),
            )
            _notion_raise_for_status(
                f"file send part {part_no}/{number_of_parts} (multi_part)",
                resp2,
            )

        log.debug("Notion multi_part: completing upload %s...", file_upload_id[:8])
        resp3 = requests.post(
            complete_url,
            headers=_notion_json_headers(token, notion_version),
            json={"file_upload_id": file_upload_id},
            timeout=(30, upload_timeout),
        )
        _notion_raise_for_status("POST file_uploads/.../complete (multi_part)", resp3)
        done = resp3.json() if resp3.content else {}
        st = done.get("status")
        if st and st != "uploaded":
            log.warning(
                "Notion multi_part complete: unexpected status for %s: %r",
                file_name,
                st,
            )
        log.debug("Notion multi_part: done %s", file_name)
        return file_upload_id
    except requests.exceptions.Timeout as e:
        log.error("Notion multi_part: timeout for %s: %s", file_name, e)
        raise Exception(f"File upload timeout for {file_name}") from e
    except Exception as e:
        log.error("Notion multi_part: failed for %s: %s", file_name, e)
        raise


class NotionService:
    def __init__(
        self,
        token: str,
        database_id: str,
        data_source_id_hint: Optional[str] = None,
    ):
        if not token:
            raise ValueError("Notion API token is required")
        if not database_id:
            raise ValueError("Database ID is required")

        self.token = token
        self.database_id = database_id
        self._data_source_id_hint = (data_source_id_hint or "").strip() or None
        # Notion file upload + page property examples use 2026-03-11; keep in sync
        # with https://developers.notion.com/guides/data-apis/uploading-small-files
        self.notion_version = "2026-03-11"
        self.base_url = "https://api.notion.com/v1"
        self._data_source_id = None
        self.max_file_upload_bytes: Optional[int] = None

        log.debug(
            f"NotionService initialized with database_id: {database_id[:8]}..., version: {self.notion_version}"
        )
        if self._data_source_id_hint:
            log.debug(
                "NotionService data_source_id_hint: %s...",
                self._data_source_id_hint[:8],
            )
        log.debug(f"Token length: {len(token) if token else 0}")

        self._fetch_workspace_limits()
        log.debug(f"Base URL: {self.base_url}")

        # Validate database ID format (UUID with or without dashes)
        clean_db_id = database_id.replace("-", "")
        if len(clean_db_id) != 32 or not all(
            c in "0123456789abcdefABCDEF" for c in clean_db_id
        ):
            log.warning(f"Database ID format may be invalid: {database_id}")
            log.warning("Expected format: 32 hex characters (with or without dashes)")

        log.debug("Using Notion-Version %s (data sources + typed property payloads)", self.notion_version)

    def _fetch_workspace_limits(self) -> None:
        """Fetch workspace limits from Notion to know the max upload size."""
        try:
            resp = requests.get(
                f"{self.base_url}/workspace",
                headers=self._headers(),
                timeout=(10, 30),
            )
            if resp.status_code == 200:
                data = resp.json()
                limits = data.get("workspace_limits") or {}
                self.max_file_upload_bytes = limits.get("max_file_upload_size_in_bytes")
                if self.max_file_upload_bytes is not None:
                    mib = self.max_file_upload_bytes / (1024 * 1024)
                    log.info(
                        "Notion workspace max_file_upload_size: %s bytes (%.1f MiB)",
                        self.max_file_upload_bytes,
                        mib,
                    )
                else:
                    log.warning("Notion GET /workspace returned no max_file_upload_size_in_bytes")
            else:
                log.warning(
                    "Notion GET /workspace returned HTTP %s (non-fatal); "
                    "cannot pre-check upload size limits",
                    resp.status_code,
                )
        except Exception as e:
            log.warning("Notion GET /workspace failed (non-fatal): %s", e)

    def test_connection(self) -> dict[str, Any]:
        """Test the Notion API connection and database access."""
        log.debug("Testing Notion API connection...")

        # First test basic network connectivity
        try:
            log.debug("Testing basic network connectivity to api.notion.com...")
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(15)  # TCP probe only; long hangs are misleading for a "test"
            result = sock.connect_ex(("api.notion.com", 443))
            sock.close()

            if result != 0:
                return {
                    "success": False,
                    "error": f"Cannot connect to api.notion.com:443 (network error: {result}). Check firewall/proxy settings.",
                }
            log.debug("✓ Basic network connectivity to api.notion.com:443 successful")
        except Exception as e:
            return {
                "success": False,
                "error": f"Network connectivity test failed: {str(e)}",
            }

        try:
            # Test basic API access
            url = f"{self.base_url}/users/me"
            headers = self._headers()

            log.debug("Testing Notion API authentication...")
            log.debug("Testing user endpoint with connect=15s read=60s...")
            resp = requests.get(
                url,
                headers=headers,
                timeout=(15, 60),
            )
            log.debug(f"User endpoint response: {resp.status_code}")

            if resp.status_code == 401:
                return {
                    "success": False,
                    "error": "Authentication failed - invalid API token",
                }
            elif resp.status_code != 200:
                log.error(f"API response text: {resp.text}")
                return {
                    "success": False,
                    "error": f"API access failed: {resp.status_code} - {resp.text}",
                }

            user_data = resp.json()
            log.debug(f"✓ Connected as: {user_data.get('name', 'Unknown user')}")

            # Test database access with data source discovery
            try:
                log.debug("Testing database access...")
                data_source_id = self._get_data_source_id()
                if data_source_id:
                    log.debug(
                        f"✓ Successfully discovered data source ID: {data_source_id[:8]}..."
                    )
                    # Test database properties access
                    properties = self._get_database_properties()
                    log.debug(
                        f"✓ Database accessible with {len(properties)} properties"
                    )
                    return {
                        "success": True,
                        "user": user_data.get("name", "Unknown"),
                        "data_source_id": data_source_id[:8] + "...",
                        "database_properties": len(properties),
                        "api_version": f"{self.notion_version} (data source)",
                    }
                else:
                    log.warning("No data source found, testing database fallback...")
                    # Test database properties access
                    properties = self._get_database_properties()
                    log.debug(
                        f"✓ Database accessible with {len(properties)} properties"
                    )
                    return {
                        "success": True,
                        "user": user_data.get("name", "Unknown"),
                        "database_properties": len(properties),
                        "api_version": f"{self.notion_version} (database fallback)",
                    }
            except Exception as e:
                log.error(f"Database access failed: {e}")
                return {"success": False, "error": f"Database access failed: {str(e)}"}

        except requests.exceptions.Timeout as e:
            log.error(f"Request timeout: {e}")
            return {
                "success": False,
                "error": "Request timeout - try increasing timeout values or check network connectivity",
            }
        except requests.exceptions.ConnectionError as e:
            log.error(f"Connection error: {e}")
            return {
                "success": False,
                "error": f"Connection error: {str(e)}. Check proxy settings or firewall.",
            }
        except Exception as e:
            log.error(f"Connection test failed: {e}")
            return {"success": False, "error": f"Connection failed: {str(e)}"}

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }
        log.debug(f"Generated headers with Notion-Version: {self.notion_version}")
        return headers

    @staticmethod
    def _headers_for_log(headers: dict[str, str]) -> dict[str, str]:
        """Safe copy of request headers for logging (never log raw tokens)."""
        h = dict(headers)
        if h.get("Authorization"):
            h["Authorization"] = "Bearer ***REDACTED***"
        return h

    def _log_page_properties_snapshot(self, page_id: str, phase: str = "") -> None:
        """GET /pages/{id} and log property types + short values (debug verification)."""
        if not page_id:
            return
        url = f"{self.base_url}/pages/{page_id}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=(30, 120))
            if r.status_code != 200:
                log.warning(
                    "Notion GET /pages snapshot (%s): status=%s body=%s",
                    phase,
                    r.status_code,
                    r.text[:800],
                )
                return
            body = r.json()
            props = body.get("properties") or {}
            parts: list[str] = []
            for key, val in props.items():
                if not isinstance(val, dict):
                    parts.append(f"{key!r}:?")
                    continue
                ptype = val.get("type", "?")
                extra = ""
                if ptype == "title":
                    ta = val.get("title") or []
                    if ta and isinstance(ta[0], dict):
                        tx = (ta[0].get("plain_text") or "")[:80]
                        extra = f" text={tx!r}"
                elif ptype in ("select", "status"):
                    sub = val.get(ptype) or {}
                    extra = f" name={sub.get('name')!r}"
                elif ptype == "multi_select":
                    ms = val.get("multi_select") or []
                    extra = f" n={len(ms)}"
                elif ptype == "people":
                    pe = val.get("people") or []
                    extra = f" n={len(pe)}"
                elif ptype == "files":
                    fi = val.get("files") or []
                    extra = f" n={len(fi)}"
                parts.append(f"{key!r}:{ptype}{extra}")
            log.info(
                "Notion page property snapshot (%s): %d props — %s",
                phase,
                len(props),
                " | ".join(parts[:25]) + (" ..." if len(parts) > 25 else ""),
            )
        except Exception as e:
            log.warning("Notion page snapshot (%s) failed: %s", phase, e)

    def _get_data_source_id(self) -> Optional[str]:
        """
        Get the data source ID for the database.
        Required for multi-source databases (Notion API 2025-09-03+).
        See: https://developers.notion.com/docs/upgrade-guide-2025-09-03
        """
        if self._data_source_id is not None:
            log.debug(f"Using cached data_source_id: {self._data_source_id[:8]}...")
            return self._data_source_id

        log.debug(f"Discovering data source ID for database: {self.database_id[:8]}...")
        url = f"{self.base_url}/databases/{self.database_id}"
        headers = self._headers()

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            log.debug(f"Database API response status: {resp.status_code}")

            if resp.status_code == 404:
                log.error(f"Database not found: {self.database_id}")
                return None

            if resp.status_code == 401:
                log.error("Authentication failed - check Notion API token")
                return None

            if resp.status_code != 200:
                log.error(f"Failed to get database info. Status: {resp.status_code}")
                log.error(f"Response text: {resp.text}")
                return None

            data = resp.json()
            log.debug(f"Database response keys: {list(data.keys())}")
            log.debug(f"Full database response: {data}")

            # Check for data_sources field (2025-09-03 API)
            if "data_sources" in data:
                data_sources = data.get("data_sources", [])
                log.debug(f"Found {len(data_sources)} data sources in database")
                log.debug(f"Data sources: {data_sources}")

                if not data_sources:
                    log.error("No data sources found in database response")
                    log.debug(f"Database response: {data}")
                    return None

                selected_source = None
                hint = self._data_source_id_hint
                if hint:
                    for ds in data_sources:
                        ds_id = ds.get("id")
                        if ds_id and _notion_ids_equal(ds_id, hint):
                            selected_source = ds
                            log.info(
                                "Notion: using data_source from URL ?v= hint "
                                "(name=%r id=%s...)",
                                ds.get("name", ""),
                                str(ds_id).replace("-", "")[:8],
                            )
                            break
                    if selected_source is None:
                        log.warning(
                            "Notion: data_source_id_hint %s... not in this database's "
                            "data_sources (%d listed); falling back to first source",
                            hint.replace("-", "")[:8],
                            len(data_sources),
                        )
                if selected_source is None:
                    selected_source = data_sources[0]
                self._data_source_id = selected_source["id"]
                source_name = selected_source.get("name", "Unknown")

                log.debug(
                    f"✓ Selected data source: '{source_name}' (ID: {self._data_source_id[:8]}...)"
                )
                return self._data_source_id
            else:
                log.warning("No 'data_sources' field found in database response")
                log.warning(
                    "This database may not support 2025-09-03 API - falling back to database_id"
                )
                log.debug(f"Database response: {data}")
                # For databases without data sources, we'll use database_id directly
                return None

        except Exception as e:
            log.error(f"Error fetching data source ID: {e}")
            log.debug(f"Exception details: {type(e).__name__}: {str(e)}")
            return None

    def _get_database_properties(self) -> dict[str, Any]:
        """
        Load property schema for ``POST /v1/pages`` ``properties``.

        Notion API ``2025-09-03``: multi-source databases require
        ``parent.type = data_source_id`` on create; schema must come from the
        **same** ``GET /v1/data_sources/{data_source_id}`` as that parent.
        See: https://developers.notion.com/docs/upgrade-guide-2025-09-03

        If the database has no ``data_sources``, fall back to
        ``GET /v1/databases/{database_id}`` (legacy single-table).
        """
        log.debug(f"Fetching database properties for: {self.database_id[:8]}...")

        try:
            data_source_id = self._get_data_source_id()
            if data_source_id:
                ds_url = f"{self.base_url}/data_sources/{data_source_id}"
                log.debug(
                    f"Getting properties from data source: {data_source_id[:8]}..."
                )
                ds_resp = requests.get(
                    ds_url, headers=self._headers(), timeout=(30, 600)
                )
                ds_resp.raise_for_status()
                ds_data = ds_resp.json()
                ds_properties = ds_data.get("properties") or {}
                log.debug(f"Got {len(ds_properties)} properties from data source")
                if not ds_properties:
                    raise Exception(
                        "Notion data source returned no properties (empty schema). "
                        "Check integration capabilities and that the database is "
                        "accessible with Notion-Version 2025-09-03."
                    )
                log.info(
                    "Notion schema: loaded %d properties from GET /data_sources/{id} "
                    "(matches data_source_id page parent; id=%s...)",
                    len(ds_properties),
                    str(data_source_id).replace("-", "")[:8],
                )
                return ds_properties

            url = f"{self.base_url}/databases/{self.database_id}"
            log.debug(
                f"Getting properties from database endpoint: {self.database_id[:8]}..."
            )
            resp = requests.get(url, headers=self._headers(), timeout=(30, 600))
            resp.raise_for_status()
            data = resp.json()
            properties = data.get("properties") or {}
            log.info(
                "Notion schema: loaded %d properties from GET /databases/{id} "
                "(no data source or empty data-source schema)",
                len(properties),
            )
            log.debug(f"Got {len(properties)} properties from database")
            if not properties:
                raise Exception(
                    "Could not load Notion property schema: empty from database "
                    "and data source"
                )
            return properties
        except Exception as e:
            log.error(f"Failed to get properties: {e}")
            raise Exception(f"Could not access database properties: {e}")

    def submit_issue(
        self,
        title: str,
        user_message: str,
        collected_data: dict[str, Any],
        tags: list[str],
        attachments_zip_b64: Optional[str],
        assignee_id: str,
        idempotency_key: Optional[str] = None,
        async_attachments: bool = True,
        rich_text: Optional[list[dict[str, Any]]] = None,
        heading: str = "",
        blocks: Optional[list[dict[str, Any]]] = None,
        title_property: Optional[str] = None,
        issue_type: Optional[str] = None,
        project: Optional[str] = None,
        pipeline_release: Optional[str] = None,
    ) -> dict[str, str]:
        log.debug(f"Starting submit_issue with title: '{title[:50]}...'")
        log.debug(f"User message length: {len(user_message) if user_message else 0}")
        log.debug(
            f"Collected data keys: {list(collected_data.keys()) if collected_data else []}"
        )
        log.debug(f"Tags: {tags}")
        log.debug(f"Assignee ID (settings): {'set' if (assignee_id or '').strip() else 'empty'}")
        log.debug(f"Issue type: {issue_type}, project: {project}, pipeline: {pipeline_release}")
        log.debug(f"Has attachments: {bool(attachments_zip_b64)}")
        log.debug(f"Has blocks: {bool(blocks)}")
        log.debug(f"Title property: {title_property}")

        log.debug("Building page properties...")
        properties = self._build_properties(
            title,
            user_message,
            tags,
            collected_data,
            assignee_id,
            title_property,
            issue_type=issue_type,
            project=project,
            pipeline_release=pipeline_release,
        )
        self._log_built_properties_summary(properties)
        self._log_built_property_values_info(properties)
        log.info(
            "Notion pages.create: built %d properties; if Issue Type/Project/Pipeline "
            "are missing here, the server addon build is outdated or inputs were empty.",
            len(properties),
        )

        # Prefer prebuilt blocks from client
        if blocks and isinstance(blocks, list) and len(blocks) > 0:
            log.debug(f"Using {len(blocks)} client-provided blocks")
            children = blocks
        else:
            log.debug("Building children from user message")
            children = self._build_children(
                user_message, rich_text=rich_text, heading=heading
            )
            log.debug(f"Built {len(children)} children blocks")

        # 2025-09-03: create page with data_source_id parent when the DB exposes
        # data_sources (required for multi-source DBs). Schema was loaded from the
        # same source in _get_database_properties. Fallback: database_id.
        data_source_id = self._get_data_source_id()
        if data_source_id:
            parent = {
                "type": "data_source_id",
                "data_source_id": data_source_id,
            }
            log.info(
                "Notion POST /pages: parent type=data_source_id id=%s... "
                "(required for API 2025-09-03 multi-source databases)",
                str(data_source_id).replace("-", "")[:8],
            )
            log.debug(
                f"Using data_source_id for page creation: {data_source_id[:8]}..."
            )
        else:
            parent = {
                "type": "database_id",
                "database_id": self.database_id,
            }
            log.info(
                "Notion POST /pages: parent type=database_id id=%s... "
                "(no data_sources on database response)",
                str(self.database_id).replace("-", "")[:8],
            )
            log.debug(f"Using database_id for page creation: {self.database_id[:8]}...")
        payload = {
            "parent": parent,
            "properties": properties,
            "icon": {"type": "emoji", "emoji": "❓"},
        }
        log.debug(
            "Notion POST /pages: parent=%s built_keys=%s props_count=%s icon=%s",
            self._summarize_parent(payload["parent"]),
            list(payload["properties"].keys()),
            len(payload["properties"]),
            payload.get("icon"),
        )
        log.debug(f"Children will be added after page creation: {len(children)} blocks")

        # Debug the exact request being made
        log.debug(f"Making Notion API request to: {self.base_url}/pages")
        log.debug("Request headers: %s", self._headers_for_log(self._headers()))
        log.debug(f"Request payload type: {type(payload)}")
        log.debug(f"Request payload size: {len(str(payload))} characters")

        headers = self._headers().copy()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
            log.debug(f"Added idempotency key: {idempotency_key[:8]}...")

        # 2025-09-03 API: Use standard pages endpoint with database_id parent
        url = f"{self.base_url}/pages"
        log.debug(f"Making POST request to pages endpoint: {url}")
        log.debug("Request headers: %s", self._headers_for_log(headers))
        log.debug(f"Request payload size: {len(str(payload))} characters")

        # More tolerant timeouts and a single retry on transient network errors
        resp = None
        for attempt in range(2):
            try:
                log.debug(f"Page creation attempt {attempt + 1}/2")
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=(30, 600),  # 30s connect, 10min read for large payloads
                )
                log.debug(f"Page creation response status: {resp.status_code}")
                log.debug(f"Page creation response headers: {dict(resp.headers)}")

                if resp.status_code >= 400:
                    log.error(f"Page creation failed with status {resp.status_code}")
                    log.error(f"Response text: {resp.text}")
                    log.error(f"Request URL: {url}")
                    log.error("Request headers: %s", self._headers_for_log(headers))
                    log.error(f"Request payload: {payload}")

                    # Try to parse error response for more details
                    try:
                        error_data = resp.json()
                        log.error(f"Error response JSON: {error_data}")
                    except:
                        log.error(f"Error response is not JSON: {resp.text}")

                    # Provide specific error messages for common API issues
                    if resp.status_code == 400:
                        error_text = resp.text.lower()
                        log.error(f"400 Error details: {error_text}")

                        if "data_source_id" in error_text:
                            log.error(
                                "Data source ID error - trying database_id fallback"
                            )
                            # Try fallback to database_id if data_source_id failed
                            if payload["parent"]["type"] == "data_source_id":
                                log.debug(
                                    "Retrying with database_id instead of data_source_id"
                                )
                                payload["parent"] = {
                                    "type": "database_id",
                                    "database_id": self.database_id,
                                }
                                continue
                        elif "parent" in error_text:
                            log.error("Parent type error - check database permissions")
                        elif "properties" in error_text:
                            log.error("Properties error - check database schema")
                        elif "invalid" in error_text:
                            log.error(
                                "Invalid request format - check API version compatibility"
                            )

                    # Instead of just raising, preserve the detailed error information
                    try:
                        error_data = resp.json()
                        detailed_error = f"Status {resp.status_code}: {error_data}"
                    except:
                        detailed_error = f"Status {resp.status_code}: {resp.text}"

                    # Raise with detailed error information
                    raise Exception(f"Notion API request failed: {detailed_error}")

                log.debug("Page creation successful")
                break
            except requests.exceptions.RequestException as e:
                log.error(f"Request exception on attempt {attempt + 1}: {e}")
                if attempt == 1:
                    raise
                # brief backoff
                import time

                log.debug("Retrying after 1 second...")
                time.sleep(1.0)
            except Exception as e:
                log.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt == 1:
                    raise
                import time

                time.sleep(1.0)

        try:
            data = resp.json()
            log.debug(f"Page creation response data keys: {list(data.keys())}")
        except Exception as e:
            log.error(f"Failed to parse JSON response: {e}")
            log.error(f"Raw response text: {resp.text}")
            raise

        page_id = data.get("id", "")
        url = data.get("url", "")
        log.debug(f"Successfully created page with ID: {page_id[:8]}...")
        log.debug(f"Page URL: {url}")
        self._log_page_properties_snapshot(page_id, phase="after_create")

        # Add children blocks after page creation
        if children and len(children) > 0:
            log.debug(f"Adding {len(children)} children blocks to page...")
            try:
                self._add_children_to_page(page_id, children)
                log.debug("Successfully added children blocks to page")
            except Exception as e:
                log.warning(f"Failed to add children blocks: {e}")
                # Don't fail the whole submission for this

        # Always upload attachments separately after page creation to avoid timeouts
        if attachments_zip_b64 and page_id:
            log.debug("Starting asynchronous attachment upload process...")
            if async_attachments:
                # Start attachment upload in background thread
                t = threading.Thread(
                    target=self._safe_attach_wrapper,
                    args=(attachments_zip_b64, page_id),
                    daemon=True,
                )
                t.start()
                log.debug("Background attachment upload started")
            else:
                # Upload attachments synchronously (for testing/debugging)
                log.debug("Starting synchronous attachment upload...")
                try:
                    self._attach_zip_to_page(attachments_zip_b64, page_id)
                    log.debug("Synchronous attachment upload completed")
                except Exception as e:
                    log.warning(f"Synchronous attachment upload failed: {e}")

        return {"url": url, "page_id": page_id}

    def _add_children_to_page(self, page_id: str, children: list[dict[str, Any]]):
        """Add children blocks to a Notion page after creation."""
        if not children:
            return

        log.debug(f"Adding {len(children)} children to page {page_id[:8]}...")

        # Notion API requires children to be added via the blocks endpoint
        url = f"{self.base_url}/blocks/{page_id}/children"
        headers = self._headers()

        # Notion API 2026-03-11: use ``position`` (``end`` = append; default if omitted).
        payload = {"position": {"type": "end"}, "children": children}

        try:
            resp = requests.patch(url, headers=headers, json=payload, timeout=(30, 600))
            resp.raise_for_status()
            log.debug(f"Successfully added {len(children)} children blocks")
        except Exception as e:
            log.error(f"Failed to add children blocks: {e}")
            raise

    def _notion_property_key(
        self, db_props: dict[str, Any], *candidates: str
    ) -> Optional[str]:
        """Resolve Notion schema map key for a property.

        ``GET /v1/databases/{id}`` and ``GET /v1/data_sources/{id}`` return
        ``properties`` as a map; keys are often display names but may be property
        IDs. Each value includes ``name`` and ``type``. Match candidates against
        map keys first, then against each spec's ``name``.
        """
        for name in candidates:
            if name and name in db_props:
                return name
        cand_norm = [str(c).strip() for c in candidates if c and str(c).strip()]
        if not cand_norm:
            return None
        for map_key, spec in db_props.items():
            if not isinstance(spec, dict):
                continue
            prop_name = str(spec.get("name") or "").strip()
            if not prop_name:
                continue
            if prop_name in cand_norm:
                return str(map_key)
        return None

    @staticmethod
    def _log_database_properties_sample(
        db_props: dict[str, Any], limit: int = 15
    ) -> None:
        """DEBUG: map_key vs spec name/id/type to diagnose UUID-keyed schemas."""
        items = list(db_props.items())
        for map_key, spec in items[:limit]:
            if not isinstance(spec, dict):
                log.debug(
                    "Notion schema sample: map_key=%r spec_non_dict=%s",
                    map_key,
                    type(spec).__name__,
                )
                continue
            log.debug(
                "Notion schema sample: map_key=%r name=%r id=%r type=%r",
                map_key,
                spec.get("name"),
                spec.get("id"),
                spec.get("type"),
            )
        if len(items) > limit:
            log.debug(
                "Notion schema sample: ... %d more properties omitted",
                len(items) - limit,
            )

    @staticmethod
    def _log_built_properties_summary(properties: dict[str, Any]) -> None:
        """DEBUG: keys and value shape only (no full text / PII)."""
        keys = list(properties.keys())
        log.debug("Notion built property keys: %s", keys)
        parts: list[str] = []
        for k, v in properties.items():
            if isinstance(v, dict) and v:
                part_keys = [x for x in v.keys() if x != "type"]
                parts.append(f"{k!r}:[{','.join(part_keys)}]")
            else:
                parts.append(f"{k!r}:[?]")
        log.debug("Notion built property shapes: %s", " | ".join(parts))

    @staticmethod
    def _log_built_property_values_info(properties: dict[str, Any]) -> None:
        """INFO: human-readable summary of option values sent on pages.create (no PII)."""
        parts: list[str] = []
        for k, v in properties.items():
            if not isinstance(v, dict):
                continue
            t = v.get("type")
            if t is None:
                if "title" in v:
                    t = "title"
                elif "status" in v:
                    t = "status"
                elif "select" in v:
                    t = "select"
                elif "multi_select" in v:
                    t = "multi_select"
                elif "people" in v:
                    t = "people"
                elif "files" in v:
                    t = "files"
            if t == "title":
                parts.append(f"{k}:title")
            elif t == "status":
                nm = (v.get("status") or {}).get("name")
                parts.append(f"{k}:status={nm!r}")
            elif t == "select":
                nm = (v.get("select") or {}).get("name")
                parts.append(f"{k}:select={nm!r}")
            elif t == "multi_select":
                names = [(x or {}).get("name") for x in (v.get("multi_select") or [])]
                parts.append(f"{k}:multi_select={names!r}")
            elif t == "people":
                parts.append(f"{k}:people n={len(v.get('people') or [])}")
            elif t == "files":
                parts.append(f"{k}:files n={len(v.get('files') or [])}")
            else:
                parts.append(f"{k}:{t}")
        log.info(
            "Notion pages.create payload summary (%d props): %s",
            len(properties),
            " | ".join(parts) if parts else "(empty)",
        )

    @staticmethod
    def _summarize_parent(parent: dict[str, Any]) -> str:
        ptype = parent.get("type", "?")
        if ptype == "data_source_id":
            rid = parent.get("data_source_id") or ""
            s = str(rid).replace("-", "")
            tail = f"{s[:8]}..." if s else "?"
            return f"type=data_source_id id={tail}"
        if ptype == "database_id":
            rid = parent.get("database_id") or ""
            s = str(rid).replace("-", "")
            tail = f"{s[:8]}..." if s else "?"
            return f"type=database_id id={tail}"
        if ptype == "page_id":
            rid = parent.get("page_id") or ""
            s = str(rid).replace("-", "")
            tail = f"{s[:8]}..." if s else "?"
            return f"type=page_id id={tail}"
        return str(parent)

    @staticmethod
    def _select_or_status_option_names(prop: dict[str, Any]) -> list[str]:
        """Option display names for Notion `select`, `multi_select`, or `status` schema."""
        ptype = prop.get("type")
        if ptype == "select":
            opts = prop.get("select", {}).get("options", [])
            return [o.get("name") for o in opts if o.get("name")]
        if ptype == "multi_select":
            opts = prop.get("multi_select", {}).get("options", [])
            return [o.get("name") for o in opts if o.get("name")]
        if ptype == "status":
            opts = prop.get("status", {}).get("options", [])
            return [o.get("name") for o in opts if o.get("name")]
        return []

    @staticmethod
    def _resolve_select_option_name(
        allowed: list[str],
        requested: str,
        field_label: str,
    ) -> Optional[str]:
        """Map client/payload string to a Notion option name (exact, then case-insensitive)."""
        if not requested:
            return None
        req = requested.strip()
        if not req:
            return None
        if not allowed:
            log.warning(
                "Notion %s: no options in schema; cannot set %r",
                field_label,
                requested,
            )
            return None
        if req in allowed:
            return req
        req_lower = req.lower()
        for n in allowed:
            if n.lower() == req_lower:
                return n
        preview = allowed[:20]
        more = len(allowed) - len(preview)
        suffix = f" ... (+{more} more)" if more > 0 else ""
        log.warning(
            "Notion %s: no option matching %r; allowed (sample): %s%s",
            field_label,
            requested,
            preview,
            suffix,
        )
        return None

    def _set_select_by_name(
        self,
        properties: dict[str, Any],
        db_props: dict[str, Any],
        prop_key: str,
        option_name: Optional[str],
        *,
        field_label: Optional[str] = None,
    ) -> None:
        if not option_name or not prop_key or prop_key not in db_props:
            return
        prop = db_props[prop_key]
        ptype = prop.get("type")
        name = option_name.strip()
        if not name:
            return
        label = field_label or prop_key
        if ptype not in ("select", "multi_select", "status"):
            log.warning(
                "Notion %s: property type is %r (not select/multi_select/status); skipping",
                label,
                ptype,
            )
            return
        allowed = self._select_or_status_option_names(prop)
        # Data source schema often omits option names; without a fallback we set nothing.
        if not allowed:
            log.info(
                "Notion %s: schema has no option list for type=%r; sending %r as-is",
                label,
                ptype,
                name,
            )
            resolved = name
        else:
            resolved = self._resolve_select_option_name(allowed, name, label)
            if not resolved:
                return
        # POST/PATCH page: use only the value key (no top-level "type"); see
        # https://developers.notion.com/reference/property-value-object
        if ptype == "select":
            properties[prop_key] = {"select": {"name": resolved}}
        elif ptype == "multi_select":
            properties[prop_key] = {"multi_select": [{"name": resolved}]}
        elif ptype == "status":
            properties[prop_key] = {"status": {"name": resolved}}

    @staticmethod
    def _option_name_case_insensitive(names: list[str], target: str) -> Optional[str]:
        """Return the schema’s canonical option string if any name matches target (case-insensitive)."""
        if not names or not target:
            return None
        tl = target.strip().lower()
        if not tl:
            return None
        for n in names:
            if n and str(n).strip().lower() == tl:
                return str(n)
        return None

    def _default_status_name(self, db_props: dict[str, Any]) -> Optional[str]:
        key = self._notion_property_key(db_props, "Status")
        if not key:
            return None
        prop = db_props[key]
        ptype = prop.get("type")
        if ptype not in ("select", "status"):
            return None
        names = self._select_or_status_option_names(prop)
        if not names:
            # Schema may omit options; _set_select_by_name will pass the string through.
            return "Ready To Start"
        for preferred in ("Ready To Start", "Backlog"):
            hit = self._option_name_case_insensitive(names, preferred)
            if hit:
                return hit
        return names[0]

    def _default_priority_name(self, db_props: dict[str, Any]) -> Optional[str]:
        key = self._notion_property_key(db_props, "Priority")
        if not key:
            return None
        prop = db_props[key]
        ptype = prop.get("type")
        if ptype not in ("select", "status"):
            return None
        names = self._select_or_status_option_names(prop)
        if not names:
            # Schema may omit options; _set_select_by_name will pass the string through.
            return "P3"
        for n in names:
            if n.upper() == "P3":
                return n
        return names[0]

    def _log_notion_schema_resolution(self, db_props: dict[str, Any]) -> None:
        """Log schema keys and how logical fields map to Notion property keys/types."""
        keys = sorted(db_props.keys())
        log.info(
            "Notion database schema: %d properties with keys: %s",
            len(keys),
            keys,
        )
        title_k = next(
            (k for k, v in db_props.items() if v.get("type") == "title"),
            None,
        )
        rows: list[tuple[str, Optional[str]]] = [
            ("title(first)", title_k),
            ("Status", self._notion_property_key(db_props, "Status")),
            ("Priority", self._notion_property_key(db_props, "Priority")),
            (
                "Issue Type",
                self._notion_property_key(
                    db_props,
                    "Issue Type",
                    "Issue Type (AI)",
                    "Issue Type AI",
                ),
            ),
            (
                "Project",
                self._notion_property_key(
                    db_props, "Project", "Project(s)", "Projects"
                ),
            ),
            (
                "Pipeline Release",
                self._notion_property_key(
                    db_props, "Pipeline Release", "Pipeline release"
                ),
            ),
            (
                "Submitted By",
                self._notion_property_key(
                    db_props, "Submitted By", "Submitted by"
                ),
            ),
        ]
        parts: list[str] = []
        for label, k in rows:
            if k:
                parts.append(f"{label}->{k!r}({db_props[k].get('type')})")
            else:
                parts.append(f"{label}->MISSING")
        parts.append("Brief (AI)->skipped(not submitted by Debugly)")
        parts.append("Tags (AI)->skipped(not submitted by Debugly)")
        parts.append("Assign->skipped(not set by Debugly)")
        log.info("Notion field resolution: %s", " | ".join(parts))

    def _build_properties(
        self,
        title: str,
        user_message: str,
        _tags: list[str],
        collected_data: dict[str, Any],
        assignee_id: str,
        title_property_override: Optional[str] = None,
        issue_type: Optional[str] = None,
        project: Optional[str] = None,
        pipeline_release: Optional[str] = None,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        _ = assignee_id  # Notion "Assign" not set; keep arg for submit_issue API
        # Always fetch schema to validate title property key
        db_props = self._get_database_properties()
        self._log_database_properties_sample(db_props)
        self._log_notion_schema_resolution(db_props)

        # Title
        # Decide title property: prefer override if it exists and is a title; else find first 'title' type; else fallback "Title"
        title_key = None
        if title_property_override:
            resolved_title = self._notion_property_key(
                db_props,
                title_property_override,
                # Common synonyms when settings say "Title" but Notion column is "Name"
                "Name",
                "Issue title",
            )
            if resolved_title and db_props.get(resolved_title, {}).get("type") == "title":
                title_key = resolved_title
        if not title_key:
            title_key = next(
                (k for k, v in db_props.items() if v.get("type") == "title"), None
            )
        if not title_key:
            title_key = "Title"
        properties[title_key] = {
            "title": [
                {
                    "type": "text",
                    "text": {"content": title[:2000]},
                }
            ],
        }

        # Status (select) — Ready To Start, else Backlog, else first option
        sk = self._notion_property_key(db_props, "Status")
        if sk:
            default_s = self._default_status_name(db_props)
            if default_s:
                self._set_select_by_name(
                    properties, db_props, sk, default_s, field_label="Status"
                )

        # Priority (select or status) — default P3 when present in schema
        pk = self._notion_property_key(db_props, "Priority")
        if pk:
            default_p = self._default_priority_name(db_props)
            if default_p:
                self._set_select_by_name(
                    properties, db_props, pk, default_p, field_label="Priority"
                )

        # Issue Type — primary Notion column "Issue Type"; legacy AI-named columns last.
        itk = self._notion_property_key(
            db_props,
            "Issue Type",
            "Issue Type (AI)",
            "Issue Type AI",
        )
        if itk and issue_type:
            self._set_select_by_name(
                properties, db_props, itk, issue_type, field_label="Issue Type"
            )

        # Project — renamed column "Project"; legacy "Project(s)" / "Projects"
        prk = self._notion_property_key(
            db_props, "Project", "Project(s)", "Projects"
        )
        proj_val = (project or "").strip()
        if proj_val.lower() == "all releases":
            proj_val = "Studio"
        if prk and proj_val:
            self._set_select_by_name(
                properties, db_props, prk, proj_val, field_label="Project"
            )

        # Pipeline Release — select, multi_select, or status
        plk = self._notion_property_key(
            db_props, "Pipeline Release", "Pipeline release"
        )
        if plk and pipeline_release:
            self._set_select_by_name(
                properties,
                db_props,
                plk,
                pipeline_release,
                field_label="Pipeline Release",
            )

        # Brief (AI) / Tags (AI) — not written by Debugly (Notion owns those columns).

        # Submitted By — people
        sb_key = self._notion_property_key(
            db_props, "Submitted By", "Submitted by"
        )
        if sb_key:
            sprop = db_props.get(sb_key, {})
            if sprop.get("type") == "people":
                user_id = self._get_current_user_id(collected_data)
                if user_id:
                    properties[sb_key] = {
                        "people": [{"object": "user", "id": user_id}],
                    }

        log.info(
            "Notion submit: resolved schema map keys — title=%r status=%r priority=%r "
            "issue_type=%r project=%r pipeline=%r submitted_by=%r (assign skipped)",
            title_key,
            self._notion_property_key(db_props, "Status"),
            self._notion_property_key(db_props, "Priority"),
            self._notion_property_key(
                db_props,
                "Issue Type",
                "Issue Type (AI)",
                "Issue Type AI",
            ),
            self._notion_property_key(
                db_props, "Project", "Project(s)", "Projects"
            ),
            self._notion_property_key(
                db_props, "Pipeline Release", "Pipeline release"
            ),
            self._notion_property_key(db_props, "Submitted By", "Submitted by"),
        )

        # Structured diagnostic: input values vs built properties
        log.info(
            "Notion _build_properties inputs: issue_type=%r project=%r "
            "pipeline_release=%r title_override=%r",
            issue_type,
            project,
            pipeline_release,
            title_property_override,
        )
        built_summary: dict[str, str] = {}
        for prop_key, prop_val in properties.items():
            if isinstance(prop_val, dict):
                if "title" in prop_val:
                    built_summary[prop_key] = "title(set)"
                elif "select" in prop_val:
                    built_summary[prop_key] = f"select={prop_val['select'].get('name')!r}"
                elif "multi_select" in prop_val:
                    names = [o.get("name") for o in prop_val.get("multi_select", [])]
                    built_summary[prop_key] = f"multi_select={names!r}"
                elif "status" in prop_val:
                    built_summary[prop_key] = f"status={prop_val['status'].get('name')!r}"
                elif "people" in prop_val:
                    ids = [p.get("id", "?")[:8] for p in prop_val.get("people", [])]
                    built_summary[prop_key] = f"people={ids!r}"
                elif "files" in prop_val:
                    built_summary[prop_key] = f"files({len(prop_val['files'])})"
                else:
                    built_summary[prop_key] = f"other({list(prop_val.keys())})"
        log.info(
            "Notion _build_properties result (%d keys): %s",
            len(properties),
            built_summary,
        )

        # Regression diagnostics: value provided but property not in pages.create payload
        if (issue_type or "").strip() and itk and itk not in properties:
            log.warning(
                "Notion submit: Issue Type %r not set on page (schema key=%r; "
                "check option name vs Notion select options)",
                issue_type,
                itk,
            )
        if proj_val and prk and prk not in properties:
            log.warning(
                "Notion submit: Project %r not set on page (schema key=%r; "
                "check option name vs Notion select options)",
                proj_val,
                prk,
            )
        if (pipeline_release or "").strip() and plk and plk not in properties:
            log.warning(
                "Notion submit: Pipeline release %r not set on page (schema key=%r; "
                "check option name vs Notion select options)",
                pipeline_release,
                plk,
            )
        if not itk and (issue_type or "").strip():
            log.warning(
                "Notion submit: Issue Type %r not set — no matching schema property "
                "(expected name like 'Issue Type')",
                issue_type,
            )
        if not prk and proj_val:
            log.warning(
                "Notion submit: Project %r not set — no matching schema property "
                "(expected 'Project' / 'Project(s)' / 'Projects')",
                proj_val,
            )
        if not plk and (pipeline_release or "").strip():
            log.warning(
                "Notion submit: Pipeline release %r not set — no matching schema property",
                pipeline_release,
            )

        return properties

    @staticmethod
    def _collected_user_dict(
        collected_data: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Resolve the user info dict from collector payload (key user or User).

        CollectorUser returns a dict with key 'user' merged into collected_data,
        so the blob is typically at collected_data['user'] and already contains
        ayon_email. Do not treat the inner info['user'] OS login string as a
        nested user dict.
        """
        if not collected_data:
            return None
        blob = collected_data.get("User")
        if blob is None:
            blob = collected_data.get("user")
        if not isinstance(blob, dict):
            return None
        if blob.get("ayon_email") is not None or blob.get("ayon_username") is not None:
            return blob
        inner = blob.get("user")
        if isinstance(inner, dict) and (
            inner.get("ayon_email") is not None
            or inner.get("ayon_username") is not None
        ):
            return inner
        return blob

    @staticmethod
    def _ayon_email_usable(email: Optional[str]) -> bool:
        if email is None:
            return False
        s = str(email).strip()
        if not s:
            return False
        return s.lower() != "unknown"

    def _get_current_user_id(self, collected_data: dict[str, Any]) -> Optional[str]:
        """Resolve Notion person id from AYON user email in collected data."""
        try:
            user_blob = self._collected_user_dict(collected_data)
            user_email = (
                (user_blob or {}).get("ayon_email") if user_blob else None
            )
            if not self._ayon_email_usable(user_email):
                if not user_blob:
                    log.warning(
                        "No user blob in collected data — cannot resolve Submitted By"
                    )
                else:
                    log.warning(
                        "No usable ayon_email in collected data — cannot resolve "
                        "Submitted By"
                    )
                return None

            headers = self._headers()
            response = requests.get(
                f"{self.base_url}/users", headers=headers, timeout=600
            )

            if response.status_code != 200:
                log.warning(
                    "Failed to list users from Notion API: %s",
                    response.status_code,
                )
                return None

            users_data = response.json()
            users = users_data.get("results", [])
            log.debug("Found %s users in Notion workspace", len(users))

            log.debug("Looking for Notion user with email: %s", user_email)
            for user in users:
                if user.get("type") != "person":
                    continue
                user_id = user.get("id")
                user_name = user.get("name", "Unknown")
                person_data = user.get("person", {})
                person_email = person_data.get("email", "")
                if person_email.lower() == str(user_email).lower():
                    log.info(
                        "Found matching user: %s (ID: %s..., email: %s)",
                        user_name,
                        user_id[:8] if user_id else "",
                        person_email,
                    )
                    return user_id

            log.warning("No Notion user found with email: %s", user_email)
            return None
        except Exception as e:
            log.warning("Failed to get current user ID from Notion API: %s", e)
            return None

    def _build_children(
        self,
        user_message: str,
        rich_text: Optional[list[dict[str, Any]]] = None,
        heading: str = "",
    ) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        if user_message or rich_text:
            text_input = user_message or ""
            if "<" in text_input and ">" in text_input:
                text_input = self._html_to_markdown(text_input)
            cleaned = self._clean_user_message(text_input)
            blocks = self._markdown_to_blocks(cleaned)
            if not blocks:
                rt = self._parse_markdown_to_rich_text(cleaned)
                blocks = [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": rt},
                    }
                ]
            children.extend(blocks)
        return children

    def _clean_user_message(self, message: str) -> str:
        """Normalize editor output before markdown parsing.

        - Strip <style>...</style> blocks
        - Remove CSS rules and stray selector lines (e.g. "p,", "li.unchecked::")
        - Collapse extra blank lines
        - Unescape HTML entities (&amp; → &)
        """
        if not message:
            return message

        import re

        text = message

        # Remove any <style> blocks entirely
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)

        # Remove inline CSS one-liners like  p, li { ... }
        text = re.sub(r"(?m)^\s*[^<{\n]{1,60}\{[^}]*\}\s*$", "", text)

        # Remove common leftover selector-only lines the editor sometimes leaves
        text = re.sub(r"(?m)^\s*(p,?\s*$)", "", text)
        text = re.sub(r"(?m)^\s*(hr\s*$)", "", text)
        text = re.sub(r"(?m)^\s*li\.(?:unchecked|checked)::?[^\s]*\s*$", "", text)

        # Collapse 3+ newlines to at most 2
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

        # Unescape HTML entities (e.g., &amp; → &)
        text = _html.unescape(text)

        return text.strip()

    def _html_to_markdown(self, html_text: str) -> str:
        """Best-effort convert small subset of HTML (as produced by our editor)
        into markdown that our block parser understands.

        Handles: h1/h2/h3, hr, b/strong, i/em, br, p, a href.
        """
        import re

        text = html_text

        # Normalize line breaks first
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

        # Headings
        text = re.sub(r"<h1[^>]*>([\s\S]*?)</h1>", r"# \1\n", text, flags=re.IGNORECASE)
        text = re.sub(
            r"<h2[^>]*>([\s\S]*?)</h2>", r"## \1\n", text, flags=re.IGNORECASE
        )
        text = re.sub(
            r"<h3[^>]*>([\s\S]*?)</h3>", r"### \1\n", text, flags=re.IGNORECASE
        )

        # Horizontal rule
        text = re.sub(r"<hr[^>]*>", "\n---\n", text, flags=re.IGNORECASE)

        # Bold/italic
        text = re.sub(
            r"<(?:b|strong)>([\s\S]*?)</(?:b|strong)>",
            r"**\1**",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"<(?:i|em)>([\s\S]*?)</(?:i|em)>", r"*\1*", text, flags=re.IGNORECASE
        )

        # Links
        def _a_to_md(m: re.Match) -> str:
            label = m.group(2) or m.group(1) or ""
            href = m.group(1) or ""
            return f"[{label}]({href})"

        text = re.sub(
            r"<a[^>]*href=\"([^\"]+)\"[^>]*>([\s\S]*?)</a>",
            _a_to_md,
            text,
            flags=re.IGNORECASE,
        )

        # Paragraphs → ensure newline boundaries
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)

        # Strip any remaining tags (defensive)
        text = re.sub(r"<[^>]+>", "", text)

        return text.strip()

    def _parse_markdown_to_rich_text(self, markdown_text: str) -> list[dict[str, Any]]:
        import re

        rich_text_blocks: list[dict[str, Any]] = []
        link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
        matches = list(re.finditer(link_pattern, markdown_text))
        if not matches:
            return [{"type": "text", "text": {"content": markdown_text}}]
        last_end = 0
        for match in matches:
            if match.start() > last_end:
                plain_text = markdown_text[last_end : match.start()]
                if plain_text:
                    rich_text_blocks.append(
                        {"type": "text", "text": {"content": plain_text}}
                    )
            link_text = match.group(1)
            link_url = match.group(2)
            if not link_url.startswith(("http://", "https://")):
                link_url = "https://" + link_url
            rich_text_blocks.append(
                {
                    "type": "text",
                    "text": {"content": link_text, "link": {"url": link_url}},
                }
            )
            last_end = match.end()
        if last_end < len(markdown_text):
            plain_text = markdown_text[last_end:]
            if plain_text:
                rich_text_blocks.append(
                    {"type": "text", "text": {"content": plain_text}}
                )
        return rich_text_blocks

    def _markdown_to_blocks(self, text: str) -> list[dict[str, Any]]:
        import re

        blocks: list[dict[str, Any]] = []

        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if not line:
                i += 1
                continue

            # Headings
            if line.startswith("### "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[4:]}}
                            ]
                        },
                    }
                )
                i += 1
                continue
            if line.startswith("## "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[3:]}}
                            ]
                        },
                    }
                )
                i += 1
                continue
            if line.startswith("# "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_1",
                        "heading_1": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[2:]}}
                            ]
                        },
                    }
                )
                i += 1
                continue

            # Divider
            if re.fullmatch(r"\s*---\s*", line):
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
            if line.lstrip().startswith("- "):
                while i < len(lines) and lines[i].lstrip().startswith("- "):
                    item_text = lines[i].lstrip()[2:]
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
            if re.match(r"\s*\d+\.\s+", line):
                while i < len(lines) and re.match(r"\s*\d+\.\s+", lines[i]):
                    item_text = re.sub(r"^\s*\d+\.\s+", "", lines[i])
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
            para_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                para_lines.append(lines[i])
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

    def _attach_zip_to_page(self, attachments_zip_b64: str, page_id: str):
        """
        Extract and upload files from ZIP to Notion page.
        Process files one by one to avoid memory issues with large attachments.
        """
        log.debug(f"Starting attachment upload for page {page_id[:8]}...")

        try:
            raw = base64.b64decode(attachments_zip_b64)
            log.debug(f"Decoded ZIP size: {len(raw)} bytes")
        except Exception as e:
            log.error(f"Failed to decode ZIP data: {e}")
            return

        try:
            with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
                uploaded_files: list[dict[str, Any]] = []
                file_list = zf.infolist()

                # Filter files to only include meaningful attachments
                relevant_files = [
                    zi
                    for zi in file_list
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
                    f"Found {len(relevant_files)} files to upload (out of {len(file_list)} total)"
                )

                def guess_content_type(name: str) -> str:
                    name_l = name.lower()
                    content_types = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".pdf": "application/pdf",
                        ".txt": "text/plain",
                        ".log": "text/plain",
                        ".md": "text/markdown",
                        ".csv": "text/csv",
                        ".json": "application/json",
                    }
                    for ext, ct in content_types.items():
                        if name_l.endswith(ext):
                            return ct
                    return "text/plain"

                # Process files one by one
                for i, zi in enumerate(relevant_files):
                    try:
                        log.debug(
                            f"Processing file {i + 1}/{len(relevant_files)}: {zi.filename}"
                        )

                        # Check file size (Notion has limits)
                        if zi.file_size > 100 * 1024 * 1024:  # 100MB limit
                            log.warning(
                                f"Skipping large file {zi.filename} ({zi.file_size} bytes)"
                            )
                            continue

                        file_bytes = zf.read(zi)
                        base_name = zi.filename.split("/")[-1]

                        # Rename .log / .json to .txt for Notion (avoid JSON MIME 403s)
                        low = base_name.lower()
                        if low.endswith(".log"):
                            display_name = base_name[:-4] + ".txt"
                        elif low.endswith(".json"):
                            display_name = base_name[:-5] + ".txt"
                        else:
                            display_name = base_name

                        content_type = guess_content_type(display_name)

                        log.debug(
                            f"Uploading {display_name} ({len(file_bytes)} bytes, {content_type})"
                        )
                        file_id = self._upload_file_bytes(
                            display_name, content_type, file_bytes
                        )

                        uploaded_files.append(
                            {
                                "type": "file_upload",
                                "file_upload": {"id": file_id},
                                "name": display_name,
                            }
                        )

                        log.debug(
                            f"Successfully uploaded {display_name} with ID: {file_id[:8]}..."
                        )

                    except Exception as e:
                        log.warning(f"Failed to upload {zi.filename}: {e}")
                        continue

                # Update page with all uploaded files at once
                if uploaded_files:
                    log.debug(
                        f"Updating page with {len(uploaded_files)} uploaded files..."
                    )
                    self._update_page_attachments(page_id, uploaded_files)
                    log.debug("Successfully updated page with attachments")
                else:
                    log.warning("No files were successfully uploaded")

        except zipfile.BadZipFile as e:
            log.error(f"Invalid ZIP file: {e}")
        except Exception as e:
            log.error(f"Error processing ZIP file: {e}")
            import traceback

            log.error(f"Traceback: {traceback.format_exc()}")

    def _upload_file_bytes(
        self, file_name: str, content_type: str, file_bytes: bytes
    ) -> str:
        """Upload file bytes via shared Notion File Upload helper (single- or multi-part)."""
        return upload_file_bytes_to_notion(
            token=self.token,
            notion_version=self.notion_version,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
            base_url=self.base_url,
            upload_timeout=600,
        )

    def _add_file_block_to_page(self, page_id: str, file_id: str, filename: str):
        """Add a file block to a Notion page."""
        try:
            headers = self._headers()

            # Create a file block
            block_data = {
                "position": {"type": "end"},
                "children": [
                    {
                        "object": "block",
                        "type": "file",
                        "file": {"type": "file_upload", "file_upload": {"id": file_id}},
                    }
                ],
            }

            response = requests.patch(
                f"{self.base_url}/blocks/{page_id}/children",
                headers=headers,
                json=block_data,
                timeout=(30, 600),  # 30s connect, 10min read
            )

            if response.status_code != 200:
                log.warning(
                    f"Failed to add file block for {filename}: {response.status_code} - {response.text}"
                )
            else:
                log.debug(f"Successfully added file block for {filename}")

        except Exception as e:
            log.error(f"Failed to add file block for {filename}: {e}")

    def _update_page_attachments(
        self, page_id: str, uploaded_files: list[dict[str, Any]]
    ):
        """Update page with attachment files by appending to existing attachments."""
        log.debug(
            f"Updating page {page_id[:8]}... with {len(uploaded_files)} new attachments"
        )

        try:
            # Get existing attachments
            existing_files = self._get_existing_attachments(page_id)
            log.debug(f"Found {len(existing_files)} existing attachments")

            # Combine existing files with new files
            all_files = existing_files + uploaded_files
            log.debug(f"Total files after adding new ones: {len(all_files)}")

        except Exception as e:
            log.warning(
                f"Failed to get existing attachments, using only new files: {e}"
            )
            all_files = uploaded_files

        # PATCH page: files value is just "files" array (see property-value-object).
        payload = {
            "properties": {
                "Attachments": {"files": all_files},
            }
        }
        log.debug(
            "Notion PATCH /pages attachments: count=%s sample_keys=%s",
            len(all_files),
            list(all_files[0].keys()) if all_files else [],
        )

        try:
            resp = requests.patch(
                f"{self.base_url}/pages/{page_id}",
                headers=self._headers(),
                json=payload,
                timeout=(30, 600),
            )
            if resp.status_code >= 400:
                log.error(
                    "Notion PATCH attachments failed: status=%s body=%s",
                    resp.status_code,
                    resp.text[:2000],
                )
            resp.raise_for_status()
            log.debug(
                f"Successfully updated page with {len(all_files)} total attachments"
            )

        except Exception as e:
            log.error(f"Failed to update page attachments: {e}")
            raise

    def _get_existing_attachments(self, page_id: str) -> list[dict[str, Any]]:
        """Get existing attachments from a page."""
        try:
            headers = self._headers()
            response = requests.get(
                f"{self.base_url}/pages/{page_id}/properties/Attachments",
                headers=headers,
                timeout=(30, 120),
            )
            if response.status_code == 200:
                data = response.json()
                files = data.get("files", [])
                log.debug(f"Retrieved {len(files)} existing attachments")
                return files
            else:
                log.warning(
                    f"Failed to get existing attachments: {response.status_code}"
                )
                return []
        except Exception as e:
            log.warning(f"Failed to get existing attachments: {e}")
            return []

    def _safe_attach_wrapper(self, attachments_zip_b64: str, page_id: str) -> None:
        """
        Safe wrapper for attachment upload that doesn't fail the main process.
        Runs in background thread.
        """
        try:
            log.debug(
                f"Background attachment upload starting for page {page_id[:8]}..."
            )
            self._attach_zip_to_page(attachments_zip_b64, page_id)
            log.debug(
                f"Background attachment upload completed for page {page_id[:8]}..."
            )
        except Exception as e:
            # Background failures are non-fatal but should be logged
            log.error(
                f"Background attachment upload failed for page {page_id[:8]}...: {e}"
            )
            import traceback

            log.error(f"Background upload traceback: {traceback.format_exc()}")
            # Don't raise - this runs in background thread
