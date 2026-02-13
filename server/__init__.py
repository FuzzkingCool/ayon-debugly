import hashlib
from typing import Any, Optional

from nxtools import logging as log

# log.info("Debugly server addon module loading...")

try:
    from ayon_server.addons import BaseServerAddon
    from ayon_server.api.responses import EmptyResponse
    from ayon_server.secrets import Secrets
    from ayon_server.settings import BaseSettingsModel
    from ayon_server.types import Field, OPModel
    # log.info("AYON server modules imported successfully")
except Exception as e:
    log.error(f"Failed to import AYON server modules: {e}")
    raise

# Add error handling for imports
try:
    from .notion_service import NotionService
    from .settings import DEFAULT_DEBUGLY_SETTINGS, DebuglySettings

    # log.info("Debugly server modules imported successfully")
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
            # log.info("Debugly server addon initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize Debugly server addon: {e}")
            raise

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
            log.debug(
                f"Debugly Notion: req_dbid='{req_dbid}', cfg_dbid set={bool(cfg_dbid)}"
            )
            # Strip Notion view/query params if pasted from URL
            if database_id and "?" in database_id:
                database_id = database_id.split("?", 1)[0]
            log.debug(f"Debugly Notion: normalized database_id='{database_id}'")
            # Convert compact UUID (32 hex chars) to dashed UUID
            if database_id and len(database_id) == 32 and "-" not in database_id:
                database_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"
                log.debug(f"Debugly Notion: converted compact UUID to '{database_id}'")
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
            log.debug("Debugly Notion: Creating page without attachments...")
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
            "Notion-Version": "2025-09-03",
        }

        # Step 1: Create file upload object
        create_payload = {"filename": filename, "content_type": content_type}

        try:
            resp = requests.post(
                "https://api.notion.com/v1/file_uploads",
                headers=headers,
                json=create_payload,
                timeout=(30, 600),  # 30s connect, 10min read
            )
            resp.raise_for_status()

            info = resp.json()
            file_upload_id = info["id"]
            upload_url = info["upload_url"]

            log.debug(f"Created upload object {file_upload_id[:8]}... for {filename}")

        except Exception as e:
            log.error(f"Failed to create upload object for {filename}: {e}")
            raise

        # Step 2: Upload file content to the provided URL
        try:
            # Use generous timeout for file uploads
            upload_timeout = 600  # 10 minutes for all file uploads
            log.debug(f"Using upload timeout: {upload_timeout}s for {file_size} bytes")

            files = {"file": (filename, file_bytes, content_type)}
            resp2 = requests.post(
                upload_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": "2025-09-03",
                },
                files=files,
                timeout=(30, upload_timeout),  # 30s connect, 10min read timeout
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

            # Initialize service
            database_id = notion_settings.database_id
            if "?" in database_id:
                database_id = database_id.split("?")[0]

            # Convert to UUID format if needed
            if len(database_id) == 32 and "-" not in database_id:
                database_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"

            service = NotionService(token=token, database_id=database_id)

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
            "Notion-Version": "2025-09-03",
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

        # Update the page with all files
        payload = {"properties": {"Attachments": {"files": all_files}}}

        try:
            resp = requests.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=headers,
                json=payload,
                timeout=30,
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
            "Notion-Version": "2025-09-03",
        }

        try:
            response = requests.get(
                f"https://api.notion.com/v1/pages/{page_id}/properties/Attachments",
                headers=headers,
                timeout=30,
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
