import hashlib
from typing import Any, Optional

from nxtools import logging as log

log.info("Debugly server addon module loading...")

try:
    from ayon_server.addons import BaseServerAddon
    from ayon_server.api.responses import EmptyResponse
    from ayon_server.secrets import Secrets
    from ayon_server.settings import BaseSettingsModel
    from ayon_server.types import Field, OPModel

    log.info("AYON server modules imported successfully")
except Exception as e:
    log.error(f"Failed to import AYON server modules: {e}")
    raise

# Add error handling for imports
try:
    from .notion_service import NotionService
    from .settings import DEFAULT_DEBUGLY_SETTINGS, DebuglySettings

    log.info("Debugly server modules imported successfully")
except Exception as e:
    log.error(f"Failed to import server modules: {e}")
    raise


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
    assignee_id: Optional[str] = Field(None, title="Assignee ID (optional override)")
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

    async def get_default_settings(self):
        log.info("Debugly server addon get_default_settings called")
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_DEBUGLY_SETTINGS)

    def initialize(self):
        log.info("Debugly server addon initialize() called")
        try:
            self.add_endpoint("/test", self.test_endpoint, method="GET")
            self.add_endpoint("/notion/test", self.notion_test, method="GET")
            self.add_endpoint(
                "/notion/connectivity", self.notion_connectivity_test, method="GET"
            )
            self.add_endpoint("/notion/submit", self.notion_submit, method="POST")
            self.add_endpoint("/notion/upload_attachment", self.notion_upload_attachment, method="POST")
            log.info("Debugly server addon initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize Debugly server addon: {e}")
            raise

    async def test_endpoint(self):
        """Simple test endpoint to verify the addon is working"""
        log.info("Test endpoint called")
        return {"status": "ok", "message": "Debugly server addon is working"}

    async def notion_test(self):
        """Test Notion API connection and configuration"""
        log.info("Notion test endpoint called")
        try:
            settings: BaseSettingsModel = await self.get_studio_settings()
            notion_cfg = settings.endpoints.notion.notion

            # Get credentials
            secret_name = notion_cfg.api_key
            token = await Secrets.get(secret_name)
            if not token:
                return {"success": False, "error": f"Secret '{secret_name}' not found"}

            # Get database ID
            database_id = (notion_cfg.database_id or "").strip()
            if "?" in database_id:
                database_id = database_id.split("?", 1)[0]
            if len(database_id) == 32 and "-" not in database_id:
                database_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"

            if not database_id:
                return {"success": False, "error": "No database ID configured"}

            # Test connection
            service = NotionService(token=token, database_id=database_id)
            result = service.test_connection()

            log.info(f"Notion test result: {result}")
            return result

        except Exception as e:
            log.error(f"Notion test failed: {e}")
            return {"success": False, "error": str(e)}

    async def notion_connectivity_test(self):
        """Test basic network connectivity to Notion API without authentication"""
        log.info("Notion connectivity test endpoint called")
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
                        "Notion-Version": "2025-09-03",
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
            log.info(
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
            database_id = req_dbid or cfg_dbid
            log.info(
                f"Debugly Notion: req_dbid='{req_dbid}', cfg_dbid set={bool(cfg_dbid)}"
            )
            # Strip Notion view/query params if pasted from URL
            if database_id and "?" in database_id:
                database_id = database_id.split("?", 1)[0]
            log.info(f"Debugly Notion: normalized database_id='{database_id}'")
            # Convert compact UUID (32 hex chars) to dashed UUID
            if database_id and len(database_id) == 32 and "-" not in database_id:
                database_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"
                log.info(f"Debugly Notion: converted compact UUID to '{database_id}'")
            if not database_id:
                log.error("Debugly Notion: No database ID provided")
                return {"error": "Notion database ID is required in settings"}

            log.debug(
                f"Debugly Notion: Creating NotionService with database_id: {database_id[:8]}..."
            )
            try:
                service = NotionService(token=token, database_id=database_id)
                log.debug("Debugly Notion: NotionService created successfully")
            except Exception as e:
                log.error(f"Debugly Notion: Failed to create NotionService: {e}")
                log.error(f"Debugly Notion: Exception type: {type(e)}")
                import traceback

                log.error(f"Debugly Notion: Traceback: {traceback.format_exc()}")
                return {"error": f"Failed to create NotionService: {str(e)}"}

            # Build a stable idempotency key to prevent duplicate page creation on retries
            idem_src = f"{payload.title}|{payload.user_message or ''}|{','.join(payload.tags or [])}"
            idempotency_key = hashlib.sha256(idem_src.encode("utf-8")).hexdigest()
            log.debug(
                f"Debugly Notion: Generated idempotency key: {idempotency_key[:8]}..."
            )

            assignee_id = (
                payload.assignee_id or getattr(notion_cfg, "assignee_id", "") or ""
            )
            log.debug(f"Debugly Notion: Using assignee_id: '{assignee_id}'")

            # Create page without attachments - client will upload them individually
            log.info("Debugly Notion: Creating page without attachments...")
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
                )
                log.info(f"Debugly Notion: Service call successful, result: {result}")
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
        
        Args:
            payload: Contains page_id, filename, file_b64, and file_size
            
        Returns:
            dict: Success status and any error messages
        """
        log.info(f"Debugly Notion: Starting attachment upload for page {payload.page_id[:8]}...")
        log.debug(f"Debugly Notion: Filename: {payload.filename}, Size: {payload.file_size} bytes")
        
        try:
            # Get settings and API token
            settings = await self.get_studio_settings()
            notion_settings = settings.endpoints.notion.notion
            
            # Get token from server secrets
            token = await self.get_secret(notion_settings.api_key)
            if not token:
                log.error("Debugly Notion: No API token found in server secrets")
                return {"error": "Notion API token not configured"}
            
            # Initialize service
            # Use database_id for token validation, but we don't need it for file upload
            database_id = notion_settings.database_id
            if "?" in database_id:
                database_id = database_id.split("?")[0]
            
            # Convert to UUID format if needed
            if len(database_id) == 32 and "-" not in database_id:
                database_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"
            
            service = NotionService(token=token, database_id=database_id)
            
            # Decode the file
            import base64
            try:
                file_bytes = base64.b64decode(payload.file_b64)
            except Exception as e:
                log.error(f"Debugly Notion: Failed to decode file {payload.filename}: {e}")
                return {"error": f"Failed to decode file: {e}"}
            
            # Determine content type
            content_type = service._guess_content_type(payload.filename)
            
            # Upload the file
            log.info(f"Debugly Notion: Uploading {payload.filename} to Notion...")
            file_id = service._upload_file_bytes(payload.filename, content_type, file_bytes)
            
            # Add the file as a block to the page content
            service._add_file_block_to_page(payload.page_id, file_id, payload.filename)
            
            log.info(f"Debugly Notion: Successfully uploaded {payload.filename}")
            return {"success": True, "file_id": file_id}
            
        except Exception as e:
            log.error(f"Debugly Notion: Attachment upload failed: {e}")
            import traceback
            log.error(f"Debugly Notion: Upload traceback: {traceback.format_exc()}")
            return {"error": f"Attachment upload failed: {e}"}
