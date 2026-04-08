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


class NotionUploadAttachmentRequest(OPModel):
    page_id: str = Field("", title="Page ID")
    filename: str = Field("", title="Filename")
    file_b64: str = Field("", title="File content (base64)")
    file_size: int = Field(0, title="File size in bytes")


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
            self.add_endpoint("/notion/submit", self.notion_submit, method="POST")
            self.add_endpoint(
                "/notion/upload_attachment",
                self.notion_upload_attachment,
                method="POST",
            )
            self.add_endpoint(
                "/notion/upload_attachments",
                self.notion_upload_attachments,
                method="POST",
            )
            self.add_endpoint(
                "/notion/finalize_attachments",
                self.notion_finalize_attachments,
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
            log.debug(
                f"Debugly Notion: issue_type={getattr(payload, 'issue_type', None)!r} "
                f"project={getattr(payload, 'project', None)!r} "
                f"pipeline_release={getattr(payload, 'pipeline_release', None)!r}"
            )
            log.info(
                "Debugly Notion submit: issue_type=%r project=%r pipeline_release=%r",
                getattr(payload, "issue_type", None),
                getattr(payload, "project", None),
                getattr(payload, "pipeline_release", None),
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

            # Resolve Notion token from secret store
            secret_name = notion_cfg.api_key
            log.debug(f"Debugly Notion: Looking for secret: '{secret_name}'")
            token = await Secrets.get(secret_name)
            if not token:
                log.error(f"Debugly Notion: Secret '{secret_name}' not found or empty")
                return {
                    "error": "Notion API key secret is not set or not accessible on server"
                }
            log.debug(f"Debugly Notion: Secret retrieved, token length: {len(token)}")

            # Prefer request database_id if provided, else settings
            req_dbid = (
                (payload.database_id or "").strip()
                if hasattr(payload, "database_id")
                else ""
            )
            cfg_dbid = (notion_cfg.database_id or "").strip()
            raw_db = (req_dbid or cfg_dbid).strip()
            database_id, ds_hint = _parse_notion_database_and_data_source_hint(
                raw_db
            )
            log.debug(
                f"Debugly Notion: req_dbid='{req_dbid}', cfg_dbid set={bool(cfg_dbid)}"
            )
            log.debug(
                f"Debugly Notion: normalized database_id='{database_id}' "
                f"data_source_hint={ds_hint[:8] + '...' if ds_hint else None}"
            )
            if not database_id:
                log.error("Debugly Notion: No database ID provided")
                return {"error": "Notion database ID is required in settings"}

            log.debug(
                f"Debugly Notion: Creating NotionService with database_id: {database_id[:8]}..."
            )
            try:
                service = NotionService(
                    token=token,
                    database_id=database_id,
                    data_source_id_hint=ds_hint,
                )
                log.debug("Debugly Notion: NotionService created successfully")
            except Exception as e:
                log.error(f"Debugly Notion: Failed to create NotionService: {e}")
                log.error(f"Debugly Notion: Exception type: {type(e)}")
                import traceback

                log.error(f"Debugly Notion: Traceback: {traceback.format_exc()}")
                return {"error": f"Failed to create NotionService: {str(e)}"}

            # Build a stable idempotency key to prevent duplicate page creation on retries
            idem_src = (
                f"{payload.title}|{payload.user_message or ''}|"
                f"{','.join(payload.tags or [])}|{payload.issue_type or ''}|"
                f"{payload.project or ''}|{payload.pipeline_release or ''}"
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

            # Create page without attachments - client will upload them individually
            log.debug("Debugly Notion: Creating page without attachments...")
            log.info(
                "Debugly Notion: calling NotionService.submit_issue "
                "(server addon must include issue_type/project/pipeline_release wiring; "
                "issue_type=%r project=%r pipeline_release=%r)",
                getattr(payload, "issue_type", None),
                getattr(payload, "project", None),
                getattr(payload, "pipeline_release", None),
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
                    issue_type=(payload.issue_type or "").strip() or None,
                    project=(payload.project or "").strip() or None,
                    pipeline_release=(payload.pipeline_release or "").strip() or None,
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

    async def notion_upload_attachment(self, payload: NotionUploadAttachmentRequest):
        """Upload a single attachment to an existing Notion page.

        This endpoint handles individual file uploads to avoid timeouts.
        The page must already exist (created via notion_submit).

        For file uploads, we don't actually need the full NotionService since we're just
        uploading files directly to Notion's file upload API - no database operations needed.

        Args:
            payload: Contains page_id, filename, file_b64, and file_size

        Returns:
            dict: Success status and any error messages
        """
        log.debug(
            f"Debugly Notion: Starting attachment upload for page {payload.page_id[:8]}..."
        )
        log.debug(
            f"Debugly Notion: Filename: {payload.filename}, Size: {payload.file_size} bytes"
        )

        try:
            # Get settings and API token
            settings = await self.get_studio_settings()
            notion_settings = settings.endpoints.notion.notion

            # Get token from server secrets
            secret_name = notion_settings.api_key
            log.debug(f"Debugly Notion: Looking for secret: '{secret_name}'")
            token = await Secrets.get(secret_name)
            if not token:
                log.error(f"Debugly Notion: Secret '{secret_name}' not found or empty")
                return {"error": "Notion API token not configured"}
            log.debug(f"Debugly Notion: Secret retrieved, token length: {len(token)}")

            # For file uploads, we don't need NotionService - we can upload directly to Notion's API
            # This avoids the database_id requirement issue entirely

            # Decode the file
            import base64

            try:
                file_bytes = base64.b64decode(payload.file_b64)
            except Exception as e:
                log.error(
                    f"Debugly Notion: Failed to decode file {payload.filename}: {e}"
                )
                return {"error": f"Failed to decode file: {e}"}

            # Determine content type using Python's built-in mimetypes module
            import mimetypes

            content_type, _ = mimetypes.guess_type(payload.filename)
            if not content_type:
                content_type = "application/octet-stream"

            # Upload the file directly using Notion's file upload API (2-step process)
            log.debug(f"Debugly Notion: Uploading {payload.filename} to Notion...")
            file_id = await self._upload_file_bytes_direct(
                token, payload.filename, content_type, file_bytes
            )

            # Just return the file ID - the client will handle batching all files together
            log.debug(
                f"Debugly Notion: Successfully uploaded {payload.filename} with ID: {file_id[:8]}..."
            )
            return {"success": True, "file_id": file_id, "filename": payload.filename}

        except Exception as e:
            log.error(f"Debugly Notion: Attachment upload failed: {e}")
            import traceback

            log.error(f"Debugly Notion: Upload traceback: {traceback.format_exc()}")
            return {"error": f"Attachment upload failed: {e}"}

    async def _upload_file_bytes_direct(
        self, token: str, filename: str, content_type: str, file_bytes: bytes
    ) -> str:
        """
        Upload file bytes directly to Notion using the 2-step upload process.
        This bypasses NotionService to avoid database_id requirements.

        Based on: https://developers.notion.com/reference/file-upload
        """
        import requests

        file_size = len(file_bytes)
        log.debug(f"Starting direct upload for {filename} ({file_size} bytes)")

        # Set up headers for Notion API
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }

        # Step 1: Create file upload object (see uploading-small-files guide)
        create_payload = {
            "mode": "single_part",
            "filename": filename,
            "content_type": content_type,
        }

        try:
            resp = requests.post(
                "https://api.notion.com/v1/file_uploads",
                headers=headers,
                json=create_payload,
                timeout=(30, 600),  # 30s connect, 10min read
            )
            if resp.status_code >= 400:
                log.error(
                    "Debugly Notion: POST /file_uploads failed: status=%s body=%s",
                    resp.status_code,
                    resp.text[:2000],
                )
            resp.raise_for_status()

            info = resp.json()
            file_upload_id = info["id"]
            upload_url = info.get("upload_url") or (
                f"https://api.notion.com/v1/file_uploads/{file_upload_id}/send"
            )

            log.debug(
                "Created upload object %s... for %s",
                file_upload_id[:8],
                filename,
            )

        except Exception as e:
            log.error(f"Failed to create upload object for {filename}: {e}")
            raise

        # Step 2: Upload file content to upload_url (typically .../send)
        try:
            # Use generous timeout for file uploads
            upload_timeout = 600  # 10 minutes for all file uploads
            log.debug(f"Using upload timeout: {upload_timeout}s for {file_size} bytes")

            files = {"file": (filename, file_bytes, content_type)}
            resp2 = requests.post(
                upload_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": NOTION_API_VERSION,
                },
                files=files,
                timeout=(30, upload_timeout),  # 30s connect, 10min read timeout
            )
            if resp2.status_code >= 400:
                log.error(
                    "Debugly Notion: file send failed: url=%s status=%s body=%s",
                    upload_url,
                    resp2.status_code,
                    resp2.text[:2000],
                )
            resp2.raise_for_status()

            log.debug(f"Successfully uploaded content for {filename}")
            return file_upload_id

        except requests.exceptions.Timeout as e:
            log.error(f"Upload timeout for {filename} after {upload_timeout}s: {e}")
            raise Exception(f"File upload timeout for {filename}")
        except Exception as e:
            log.error(f"Failed to upload content for {filename}: {e}")
            raise

    async def notion_upload_attachments(self, payload: dict):
        """Upload multiple attachments to a Notion page in one batch."""
        log.debug(
            f"Debugly Notion: Starting batch attachment upload for page {payload.get('page_id', 'unknown')[:8]}..."
        )

        try:
            # Get settings and API token
            settings = await self.get_studio_settings()
            notion_settings = settings.endpoints.notion.notion

            # Get token from server secrets
            secret_name = notion_settings.api_key
            log.debug(f"Debugly Notion: Looking for secret: '{secret_name}'")
            token = await Secrets.get(secret_name)
            if not token:
                log.error(f"Debugly Notion: Secret '{secret_name}' not found or empty")
                return {"error": "Notion API token not configured"}
            log.debug(f"Debugly Notion: Secret retrieved, token length: {len(token)}")

            raw_db = (notion_settings.database_id or "").strip()
            database_id, ds_hint = _parse_notion_database_and_data_source_hint(
                raw_db
            )
            if not database_id:
                log.error("Debugly Notion: No database ID for attachment upload")
                return {"error": "Notion database ID is not configured"}

            service = NotionService(
                token=token,
                database_id=database_id,
                data_source_id_hint=ds_hint,
            )

            page_id = payload.get("page_id")
            if not page_id:
                return {"error": "Page ID is required"}

            # Process all files
            uploaded_files = []
            files_data = payload.get("files", [])

            for file_data in files_data:
                try:
                    filename = file_data.get("filename")
                    file_b64 = file_data.get("file_b64")

                    if not filename or not file_b64:
                        log.warning(f"Skipping file with missing data: {filename}")
                        continue

                    # Decode the file
                    import base64

                    file_bytes = base64.b64decode(file_b64)

                    # Determine content type
                    import mimetypes

                    content_type, _ = mimetypes.guess_type(filename)
                    if not content_type:
                        content_type = "application/octet-stream"

                    # Upload the file
                    log.debug(f"Debugly Notion: Uploading {filename} to Notion...")
                    file_id = service._upload_file_bytes(
                        filename, content_type, file_bytes
                    )

                    # Add to uploaded files list
                    uploaded_files.append(
                        {
                            "type": "file_upload",
                            "file_upload": {"id": file_id},
                            "name": filename,
                        }
                    )

                    log.debug(f"Debugly Notion: Successfully uploaded {filename}")

                except Exception as e:
                    log.warning(
                        f"Failed to upload {file_data.get('filename', 'unknown')}: {e}"
                    )
                    continue

            # Update the page with all uploaded files at once
            if uploaded_files:
                log.debug(
                    f"Debugly Notion: Updating page with {len(uploaded_files)} attachments..."
                )
                service._update_page_attachments(page_id, uploaded_files)
                log.debug(
                    "Debugly Notion: Successfully updated page with all attachments"
                )

            return {"success": True, "uploaded_count": len(uploaded_files)}

        except Exception as e:
            log.error(f"Debugly Notion: Batch attachment upload failed: {e}")
            import traceback

            log.error(f"Debugly Notion: Upload traceback: {traceback.format_exc()}")
            return {"error": f"Batch attachment upload failed: {e}"}

    async def notion_finalize_attachments(self, payload: dict):
        """Finalize attachments by updating the Notion page with already uploaded files.

        Uses direct API calls to update page properties, bypassing NotionService database requirements.
        """
        log.debug(
            f"Debugly Notion: Finalizing attachments for page {payload.get('page_id', 'unknown')[:8]}..."
        )

        try:
            # Get settings and API token
            settings = await self.get_studio_settings()
            notion_settings = settings.endpoints.notion.notion

            # Get token from server secrets
            secret_name = notion_settings.api_key
            log.debug(f"Debugly Notion: Looking for secret: '{secret_name}'")
            token = await Secrets.get(secret_name)
            if not token:
                log.error(f"Debugly Notion: Secret '{secret_name}' not found or empty")
                return {"error": "Notion API token not configured"}
            log.debug(f"Debugly Notion: Secret retrieved, token length: {len(token)}")

            page_id = payload.get("page_id")
            if not page_id:
                return {"error": "Page ID is required"}

            # Get the uploaded files from the payload
            uploaded_files = payload.get("files", [])
            if not uploaded_files:
                log.debug("Debugly Notion: No files to finalize")
                return {"success": True, "finalized_count": 0}

            # Update the page with all uploaded files at once using direct API call
            log.debug(
                f"Debugly Notion: Updating page with {len(uploaded_files)} attachments..."
            )
            await self._update_page_attachments_direct(token, page_id, uploaded_files)
            log.debug("Debugly Notion: Successfully updated page with all attachments")

            return {"success": True, "finalized_count": len(uploaded_files)}

        except Exception as e:
            log.error(f"Debugly Notion: Finalize attachments failed: {e}")
            import traceback

            log.error(f"Debugly Notion: Finalize traceback: {traceback.format_exc()}")
            return {"error": f"Finalize attachments failed: {e}"}

    async def _update_page_attachments_direct(
        self, token: str, page_id: str, uploaded_files: list[dict]
    ) -> None:
        """
        Update page attachments directly using Notion API without NotionService.

        Based on: https://developers.notion.com/reference/patch-page
        """
        import requests

        log.debug(
            f"Updating page {page_id[:8]}... with {len(uploaded_files)} new attachments"
        )

        # Set up headers for Notion API
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }

        try:
            # First, get existing attachments from the page
            existing_files = await self._get_existing_attachments_direct(token, page_id)
            log.debug(f"Found {len(existing_files)} existing attachments")

            # Combine existing files with new files
            all_files = existing_files + uploaded_files
            log.debug(f"Total files after adding new ones: {len(all_files)}")

        except Exception as e:
            log.warning(
                f"Failed to get existing attachments, using only new files: {e}"
            )
            all_files = uploaded_files

        # Typed files property (Notion 2026-03-11 upload guide)
        payload = {
            "properties": {
                "Attachments": {"type": "files", "files": all_files},
            }
        }
        log.debug(
            "Debugly Notion: PATCH page attachments count=%s",
            len(all_files),
        )

        try:
            resp = requests.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=headers,
                json=payload,
                timeout=(30, 600),
            )
            if resp.status_code >= 400:
                log.error(
                    "Debugly Notion: PATCH attachments failed: status=%s body=%s",
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

    async def _get_existing_attachments_direct(
        self, token: str, page_id: str
    ) -> list[dict]:
        """Get existing attachments from a page using direct API call."""
        import requests

        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_API_VERSION,
        }

        try:
            response = requests.get(
                f"https://api.notion.com/v1/pages/{page_id}/properties/Attachments",
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
                    "Failed to get existing attachments: status=%s body=%s",
                    response.status_code,
                    response.text[:800],
                )
                return []
        except Exception as e:
            log.warning(f"Failed to get existing attachments: {e}")
            return []
