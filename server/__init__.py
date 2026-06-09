import asyncio
import hashlib
from typing import Any, Optional

from nxtools import logging as log

# log.info("Debugly server addon module loading...")

try:
    from ayon_server.addons import BaseServerAddon
    from ayon_server.api.dependencies import CurrentUser
    from ayon_server.api.responses import EmptyResponse
    from ayon_server.exceptions import (
        BadRequestException,
        ForbiddenException,
        NotFoundException,
    )
    from ayon_server.secrets import Secrets
    from ayon_server.settings import BaseSettingsModel
    from ayon_server.types import Field, OPModel
    from pydantic import root_validator
    from starlette.responses import Response
    # log.info("AYON server modules imported successfully")
except Exception as e:
    log.error(f"Failed to import AYON server modules: {e}")
    raise

# Add error handling for imports
try:
    from . import issue_reports
    from .notion_service import NotionService
    from .settings import DEFAULT_DEBUGLY_SETTINGS, DebuglySettings

    # log.info("Debugly server modules imported successfully")
except Exception as e:
    log.error(f"Failed to import server modules: {e}")
    raise


# Keep in sync with NotionService and https://developers.notion.com/reference/versioning
NOTION_API_VERSION = "2026-03-11"


def _normalize_notion_uuid(value: str) -> str:
    """Return dashed lowercase UUID, or '' if not 32 hex (ignores existing dashes)."""
    s = (value or "").strip()
    if not s:
        return ""
    s = s.split("?", 1)[0].split("&", 1)[0].strip()
    s = s.replace("-", "").lower()
    if len(s) != 32 or not all(c in "0123456789abcdef" for c in s):
        return ""
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"


def _parse_notion_database_and_data_source_hint(
    raw: str,
) -> tuple[str, Optional[str]]:
    """Parse pasted Notion DB URL: ``<db_uuid>?v=<data_source_or_view_uuid>``.

    The ``v=`` segment is treated as a **preferred data_source_id** when it
    appears in ``GET /v1/databases/{id}`` → ``data_sources`` (common when
    copying from the browser). If it does not match any source, the first
    source is still used and a warning is logged.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", None
    base = raw.split("?", 1)[0].split("&", 1)[0]
    ds_hint: Optional[str] = None
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


def _coerce_notion_submit_camel_case(data: Any) -> Any:
    """Map camelCase JSON keys to snake_case so metadata survives gateways / older clients."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    for snake, camel in (
        ("issue_type", "issueType"),
        ("pipeline_release", "pipelineRelease"),
        ("database_id", "databaseId"),
        ("user_message", "userMessage"),
        ("title_property", "titleProperty"),
        ("attachments_zip_b64", "attachmentsZipB64"),
        ("collected_data", "collectedData"),
    ):
        if out.get(snake) is None and camel in out:
            out[snake] = out[camel]
    return out


class NotionSubmitRequest(OPModel):
    title: str = Field("", title="Title")
    user_message: Optional[str] = Field(None, title="User message")
    collected_data: dict[str, Any] = Field(default_factory=dict, title="Collected data")
    tags: list[str] | None = Field(default=None, title="Tags")
    attachments_zip_b64: Optional[str] = Field(
        default=None,
        title="Attachments ZIP (base64)",
        description="Base64-encoded ZIP produced by DebuglyIssue.to_zip()",
    )
    database_id: Optional[str] = Field(None, title="Database ID (optional override)")
    issue_type: Optional[str] = Field(None, title="Issue Type (Notion select name)")
    project: Optional[str] = Field(
        None,
        title="Project(s)",
        description="Single Notion select option: AYON project name or 'all releases'",
    )
    pipeline_release: Optional[str] = Field(
        None,
        title="Pipeline release",
        description="Notion Pipeline release select option name",
    )
    rich_text: Optional[list[dict[str, Any]]] = Field(
        None, title="Pre-parsed rich_text for Notion body"
    )
    heading: Optional[str] = Field(None, title="Heading text for description block")
    blocks: Optional[list[dict[str, Any]]] = Field(
        None, title="Prebuilt Notion blocks for body (preferred)"
    )
    title_property: Optional[str] = Field(
        None, title="Override Notion title property key (skip schema fetch)"
    )

    @root_validator(pre=True)
    def _normalize_aliases(cls, values: Any) -> Any:
        # ayon-backend uses Pydantic v1 (see ynput/ayon-backend pyproject.toml).
        return _coerce_notion_submit_camel_case(values)


class NotionAttachBundleRequest(OPModel):
    page_id: str = Field("", title="Notion page ID from notion/submit")
    attachments_zip_b64: str = Field(
        "",
        title="Attachments ZIP (base64)",
        description="Base64-encoded report ZIP produced by DebuglyIssue.to_zip()",
    )
    database_id: Optional[str] = Field(
        None, title="Database ID override (same as notion/submit)"
    )

    @root_validator(pre=True)
    def _normalize_aliases(cls, values: Any) -> Any:
        # ayon-backend uses Pydantic v1; tolerate camelCase from gateways/clients.
        if not isinstance(values, dict):
            return values
        out = dict(values)
        for snake, camel in (
            ("page_id", "pageId"),
            ("attachments_zip_b64", "attachmentsZipB64"),
            ("database_id", "databaseId"),
        ):
            if out.get(snake) is None and camel in out:
                out[snake] = out[camel]
        return out


class NotionAppendNoteRequest(OPModel):
    page_id: str = Field("", title="Notion page ID")
    message: str = Field("", title="Failure or status note to append on the page")
    database_id: Optional[str] = Field(
        None, title="Database ID override (same as notion/submit)"
    )


class Debugly(BaseServerAddon):
    settings_model = DebuglySettings
    frontend_scopes = {"settings": {}}

    async def get_default_settings(self):
        # log.info("Debugly server addon get_default_settings called")
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_DEBUGLY_SETTINGS)

    def initialize(self):
        # log.info("Debugly server addon initialize() called")
        try:
            self.add_endpoint("/test", self.test_endpoint, method="GET")
            self.add_endpoint("/notion/test", self.notion_test, method="GET")
            self.add_endpoint(
                "/notion/connectivity", self.notion_connectivity_test, method="GET"
            )
            self.add_endpoint(
                "/notion/capabilities",
                self.notion_capabilities,
                method="GET",
            )
            self.add_endpoint("/notion/submit", self.notion_submit, method="POST")
            self.add_endpoint(
                "/notion/attach_bundle",
                self.notion_attach_bundle,
                method="POST",
            )
            self.add_endpoint(
                "/notion/append_note",
                self.notion_append_note,
                method="POST",
            )
            self.add_endpoint("/issues", self.debugly_list_issues, method="GET")
            self.add_endpoint(
                "/issues/{zip_basename}/attachment/{attachment_name}",
                self.debugly_issue_attachment,
                method="GET",
            )
            # log.info("Debugly server addon initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize Debugly server addon: {e}")
            raise

    async def debugly_list_issues(self, user: CurrentUser) -> list[dict[str, Any]]:
        if not user.is_manager:
            raise ForbiddenException("Only managers can view Debugly issue reports")
        settings: BaseSettingsModel = await self.get_studio_settings()
        root, err = issue_reports.resolve_reports_dir(settings)
        if err or not root:
            if err:
                log.warning(f"debugly_list_issues: {err}")
            return []
        return await asyncio.to_thread(issue_reports.list_issues, root)

    async def debugly_issue_attachment(
        self,
        user: CurrentUser,
        zip_basename: str,
        attachment_name: str,
    ) -> Response:
        if not user.is_manager:
            raise ForbiddenException("Only managers can download Debugly issue attachments")
        settings: BaseSettingsModel = await self.get_studio_settings()
        root, err = issue_reports.resolve_reports_dir(settings)
        if err or not root:
            raise BadRequestException(
                "Shared folder is disabled or not configured for this server OS"
            )
        zip_path = issue_reports.zip_path_under_root(root, zip_basename)
        if zip_path is None:
            raise NotFoundException("Issue archive not found")

        def _read() -> tuple[bytes, str, str]:
            found = issue_reports.read_zip_member(zip_path, attachment_name)
            if not found:
                raise FileNotFoundError()
            body, ctype = found
            return body, ctype, attachment_name

        try:
            body, ctype, fname = await asyncio.to_thread(_read)
        except FileNotFoundError:
            raise NotFoundException("Attachment not found in archive")
        return Response(
            content=body,
            media_type=ctype,
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
            },
        )

    async def test_endpoint(self):
        """Simple test endpoint to verify the addon is working"""
        log.debug("Test endpoint called")
        return {"status": "ok", "message": "Debugly server addon is working"}

    async def notion_test(self):
        """Test Notion API connection and configuration"""
        log.debug("Notion test endpoint called")
        try:
            settings: BaseSettingsModel = await self.get_studio_settings()
            notion_cfg = settings.endpoints.notion.notion

            # Get credentials
            secret_name = notion_cfg.api_key
            token = await Secrets.get(secret_name)
            if not token:
                return {"success": False, "error": f"Secret '{secret_name}' not found"}

            raw_db = (notion_cfg.database_id or "").strip()
            database_id, ds_hint = _parse_notion_database_and_data_source_hint(
                raw_db
            )
            if not database_id:
                return {"success": False, "error": "No database ID configured"}

            # Test connection
            service = NotionService(
                token=token,
                database_id=database_id,
                data_source_id_hint=ds_hint,
            )
            result = service.test_connection()

            log.debug(f"Notion test result: {result}")
            return result

        except Exception as e:
            log.error(f"Notion test failed: {e}")
            return {"success": False, "error": str(e)}

    async def notion_connectivity_test(self):
        """Test basic network connectivity to Notion API without authentication"""
        log.debug("Notion connectivity test endpoint called")
        try:
            import socket

            import requests

            # Test socket connectivity
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                result = sock.connect_ex(("api.notion.com", 443))
                sock.close()

                if result != 0:
                    return {
                        "success": False,
                        "error": f"Socket connection failed: {result}",
                        "test": "socket",
                    }

                socket_success = True
                socket_error = None
            except Exception as e:
                socket_success = False
                socket_error = str(e)

            # Test HTTP request
            try:
                resp = requests.get(
                    "https://api.notion.com/v1/users/me",
                    headers={
                        "Authorization": "Bearer test",
                        "Notion-Version": NOTION_API_VERSION,
                    },
                    timeout=(10, 60),
                )
                http_success = True
                http_status = resp.status_code
                http_error = None
            except Exception as e:
                http_success = False
                http_status = None
                http_error = str(e)

            return {
                "success": socket_success and http_success,
                "socket_test": {
                    "success": socket_success,
                    "error": socket_error if not socket_success else None,
                },
                "http_test": {
                    "success": http_success,
                    "status_code": http_status,
                    "error": http_error if not http_success else None,
                },
            }

        except Exception as e:
            log.error(f"Connectivity test failed: {e}")
            return {"success": False, "error": str(e)}

    async def notion_submit(self, payload: NotionSubmitRequest):
        """Create a Notion page using server-side credentials.

        Returns dict with url and page_id.
        """
        try:
            log.debug(
                f"Debugly Notion: Starting notion_submit with title: '{payload.title[:50]}...'"
            )
        except Exception as e:
            log.error(f"Debugly Notion: Failed to initialize logging: {e}")
            return {"error": f"Failed to initialize logging: {str(e)}"}
        try:
            log.debug(f"Debugly Notion: Payload keys: {list(payload.__dict__.keys())}")
            log.debug(f"Debugly Notion: Title: '{payload.title}'")
            log.debug(
                f"Debugly Notion: User message length: {len(payload.user_message) if payload.user_message else 0}"
            )
            log.debug(
                f"Debugly Notion: Collected data keys: {list(payload.collected_data.keys()) if payload.collected_data else []}"
            )
            log.debug(f"Debugly Notion: Tags: {payload.tags}")
            req_db_preview = (
                (payload.database_id or "").strip()
                if hasattr(payload, "database_id")
                else ""
            )
            meta_it = getattr(payload, "issue_type", None)
            meta_pr = getattr(payload, "project", None)
            meta_pl = getattr(payload, "pipeline_release", None)
            log.debug(
                f"Debugly Notion: issue_type={meta_it!r} project={meta_pr!r} "
                f"pipeline_release={meta_pl!r}"
            )
            # Single INFO line for parity checks vs client + scripts/test_notion_properties.py
            log.info(
                "Debugly Notion: POST /notion/submit parsed → NotionService "
                "(compare to client INFO and pages.create payload summary): "
                "issue_type=%r project=%r pipeline_release=%r "
                "database_id_in_body=%r blocks=%s",
                meta_it,
                meta_pr,
                meta_pl,
                bool(req_db_preview),
                bool(getattr(payload, "blocks", None)),
            )
            log.debug(
                f"Debugly Notion: Has attachments: {bool(payload.attachments_zip_b64)}"
            )
            log.debug(f"Debugly Notion: Has blocks: {bool(payload.blocks)}")
            log.debug(f"Debugly Notion: Rich text: {bool(payload.rich_text)}")
            log.debug(f"Debugly Notion: Heading: '{payload.heading}'")
            log.debug(f"Debugly Notion: Title property: {payload.title_property}")

            settings: BaseSettingsModel = await self.get_studio_settings()
            notion_cfg = settings.endpoints.notion.notion
            log.debug(
                f"Debugly Notion: Settings loaded, notion config keys: {list(notion_cfg.__dict__.keys())}"
            )

            req_dbid = (
                (payload.database_id or "").strip()
                if hasattr(payload, "database_id")
                else ""
            )
            log.debug(
                "Debugly Notion: req_dbid set=%s cfg_dbid set=%s",
                bool(req_dbid),
                bool((notion_cfg.database_id or "").strip()),
            )
            try:
                service, err = await self._notion_service_from_settings(
                    settings,
                    database_id_override=req_dbid or None,
                )
                if service is None:
                    log.error("Debugly Notion: %s", err)
                    if err == "Notion API token not configured":
                        return {
                            "error": "Notion API key secret is not set or not accessible on server"
                        }
                    return {"error": err or "Notion database ID is required in settings"}
                log.debug("Debugly Notion: NotionService created successfully")
            except Exception as e:
                log.error(f"Debugly Notion: Failed to create NotionService: {e}")
                log.error(f"Debugly Notion: Exception type: {type(e)}")
                import traceback

                log.error(f"Debugly Notion: Traceback: {traceback.format_exc()}")
                return {"error": f"Failed to create NotionService: {str(e)}"}

            submit_issue_type = (payload.issue_type or "").strip() or None
            submit_project = (payload.project or "").strip() or None
            submit_pipeline = (payload.pipeline_release or "").strip() or None

            # Build a stable idempotency key to prevent duplicate page creation on retries
            idem_src = (
                f"{payload.title}|{payload.user_message or ''}|"
                f"{','.join(payload.tags or [])}|{submit_issue_type or ''}|"
                f"{submit_project or ''}|{submit_pipeline or ''}"
            )
            idempotency_key = hashlib.sha256(idem_src.encode("utf-8")).hexdigest()
            log.debug(
                f"Debugly Notion: Generated idempotency key: {idempotency_key[:8]}..."
            )

            assignee_id = (getattr(notion_cfg, "assignee_id", None) or "").strip()
            log.debug(
                f"Debugly Notion: Assignee from settings only: "
                f"{'set' if assignee_id else 'empty'}"
            )

            # Create page without attachments - client transfers ZIP via bundle_* routes
            log.debug("Debugly Notion: Creating page without attachments...")
            log.info(
                "Debugly Notion: calling NotionService.submit_issue with "
                "issue_type=%r project=%r pipeline_release=%r "
                "(empty → omitted on Notion row; must match test_notion_properties.py inputs)",
                submit_issue_type,
                submit_project,
                submit_pipeline,
            )
            try:
                result = service.submit_issue(
                    title=payload.title,
                    user_message=payload.user_message or "",
                    collected_data=payload.collected_data or {},
                    tags=payload.tags or [],
                    attachments_zip_b64=None,  # No attachments - handled by separate endpoint
                    assignee_id=assignee_id,
                    idempotency_key=idempotency_key,
                    rich_text=payload.rich_text,
                    heading="",
                    blocks=payload.blocks,
                    title_property=payload.title_property,
                    async_attachments=False,  # No attachments to process
                    issue_type=submit_issue_type,
                    project=submit_project,
                    pipeline_release=submit_pipeline,
                )
                log.debug(f"Debugly Notion: Service call successful, result: {result}")
                return result
            except Exception as e:
                log.error(f"Debugly Notion: Service call failed: {e}")
                log.error(f"Debugly Notion: Exception type: {type(e)}")
                import traceback

                log.error(f"Debugly Notion: Traceback: {traceback.format_exc()}")

                # Provide more helpful error messages based on the error type
                error_msg = str(e)
                log.error(f"Debugly Notion: Original error message: '{error_msg}'")
                log.error(f"Debugly Notion: Error type: {type(e).__name__}")

                # More specific error handling
                if "authentication failed" in error_msg.lower() or "401" in error_msg:
                    error_msg = (
                        "Authentication failed. Please check your Notion API token."
                    )
                elif (
                    "database" in error_msg.lower() and "not found" in error_msg.lower()
                ):
                    error_msg = "Database not found. Please verify the database ID and integration permissions."
                elif "data source" in error_msg.lower():
                    error_msg = f"Data source discovery failed: {error_msg}. This may be due to API version compatibility or database access issues."
                elif "timeout" in error_msg.lower():
                    error_msg = f"Request timeout: {error_msg}. Try increasing timeout values or check network connectivity."
                elif (
                    "connection" in error_msg.lower() or "network" in error_msg.lower()
                ):
                    error_msg = f"Network connection failed: {error_msg}. Check proxy settings, firewall, or internet connection."
                elif "400" in error_msg and "Bad Request" in error_msg:
                    # For 400 errors, preserve the original detailed error message
                    error_msg = f"Bad Request: {error_msg}"
                else:
                    # Don't modify the error message if we don't recognize the error type
                    pass

                return {"error": f"Notion API error: {error_msg}"}
        except Exception as e:
            log.error(f"Debugly Notion: Unexpected error in notion_submit: {e}")
            log.error(f"Debugly Notion: Exception type: {type(e)}")
            import traceback

            log.error(f"Debugly Notion: Traceback: {traceback.format_exc()}")
            return {"error": f"Unexpected error: {str(e)}"}

    async def notion_capabilities(self):
        """Report server-side Notion upload features for client pre-flight checks."""
        return {
            "success": True,
            "attach_bundle": True,
            "notion_api_version": NOTION_API_VERSION,
        }

    async def notion_append_note(self, payload: NotionAppendNoteRequest):
        """Append a failure/status paragraph to an existing Notion page."""
        page_id = (payload.page_id or "").strip()
        message = (payload.message or "").strip()
        if not page_id:
            return {"success": False, "error": "page_id is required"}
        if not message:
            return {"success": False, "error": "message is required"}
        try:
            service, err = await self._notion_service_for_uploads(
                database_id_override=(payload.database_id or "").strip() or None
            )
            if service is None:
                return {"success": False, "error": err or "Notion not configured"}

            def _run() -> None:
                from .notion_service import SHARED_FOLDER_ARCHIVE_HINT

                service._append_upload_failures_to_page(
                    page_id,
                    [message],
                    SHARED_FOLDER_ARCHIVE_HINT,
                )

            await asyncio.to_thread(_run)
            return {"success": True}
        except Exception as e:
            log.error("Debugly Notion: append_note failed: %s", e)
            return {"success": False, "error": str(e)}

    async def _notion_service_from_settings(
        self,
        settings: BaseSettingsModel,
        *,
        database_id_override: Optional[str] = None,
    ) -> tuple[Optional[NotionService], Optional[str]]:
        """Build NotionService from studio settings with optional database_id override."""
        notion_settings = settings.endpoints.notion.notion
        secret_name = notion_settings.api_key
        token = await Secrets.get(secret_name)
        if not token:
            return None, "Notion API token not configured"
        req_dbid = (database_id_override or "").strip()
        cfg_dbid = (notion_settings.database_id or "").strip()
        raw_db = (req_dbid or cfg_dbid).strip()
        database_id, ds_hint = _parse_notion_database_and_data_source_hint(raw_db)
        if not database_id:
            return None, "Notion database ID is not configured"
        service = NotionService(
            token=token,
            database_id=database_id,
            data_source_id_hint=ds_hint,
        )
        return service, None

    async def _notion_service_for_uploads(
        self,
        *,
        database_id_override: Optional[str] = None,
    ) -> tuple[Optional[NotionService], Optional[str]]:
        """Build NotionService for server-side ZIP upload pass (token + database)."""
        settings = await self.get_studio_settings()
        return await self._notion_service_from_settings(
            settings,
            database_id_override=database_id_override,
        )

    async def notion_attach_bundle(self, payload: NotionAttachBundleRequest):
        """Upload a report ZIP to Notion and attach its members in one request.

        Stateless: the client sends the whole ZIP once; the server decodes it,
        uploads each member via the Notion File Upload API (single- or
        multi-part), and PATCHes the page's Attachments property. No transfer
        session persists between requests, so this is safe across multi-worker /
        multi-replica backends.
        """
        import base64

        page_id = (payload.page_id or "").strip()
        if not page_id:
            return {"success": False, "error": "page_id is required"}
        b64 = (payload.attachments_zip_b64 or "").strip()
        if not b64:
            return {"success": False, "error": "attachments_zip_b64 is required"}
        try:
            zip_bytes = base64.b64decode(b64, validate=False)
        except Exception as e:
            return {"success": False, "error": f"invalid attachments_zip_b64: {e}"}
        if not zip_bytes:
            return {"success": False, "error": "attachments_zip_b64 decoded to empty"}

        try:
            service, err = await self._notion_service_for_uploads(
                database_id_override=(payload.database_id or "").strip() or None
            )
            if service is None:
                return {"success": False, "error": err or "Notion not configured"}

            def _run() -> dict[str, Any]:
                return service.attach_zip_bytes_to_page(zip_bytes, page_id)

            result = await asyncio.to_thread(_run)
            if not isinstance(result, dict):
                return {"success": False, "error": "internal: invalid attach result"}
            log.info(
                "Debugly Notion: attach_bundle page=%s... uploaded=%s failed=%s",
                page_id[:8],
                result.get("attachments_uploaded"),
                result.get("attachments_failed"),
            )
            return result
        except Exception as e:
            log.error("Debugly Notion: attach_bundle failed: %s", e)
            import traceback

            log.error("Traceback: %s", traceback.format_exc())
            return {"success": False, "error": f"attach_bundle failed: {e}"}
