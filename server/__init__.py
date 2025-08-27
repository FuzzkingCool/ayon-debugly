import hashlib
from typing import Any, Optional

from ayon_server.addons import BaseServerAddon
from ayon_server.api.responses import EmptyResponse
from ayon_server.secrets import Secrets
from ayon_server.settings import BaseSettingsModel
from ayon_server.types import Field, OPModel
from nxtools import logging

from .notion_service import NotionService
from .settings import DEFAULT_DEBUGLY_SETTINGS, DebuglySettings


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
    rich_text: Optional[list[dict[str, Any]]] = Field(None, title="Pre-parsed rich_text for Notion body")
    heading: Optional[str] = Field(None, title="Heading text for description block")
    blocks: Optional[list[dict[str, Any]]] = Field(None, title="Prebuilt Notion blocks for body (preferred)")
    title_property: Optional[str] = Field(None, title="Override Notion title property key (skip schema fetch)")


class Debugly(BaseServerAddon):
    settings_model = DebuglySettings

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_DEBUGLY_SETTINGS)

    def initialize(self):
        self.add_endpoint("/notion/submit", self.notion_submit, method="POST")

    async def notion_submit(self, payload: NotionSubmitRequest):
        """Create a Notion page using server-side credentials.

        Returns dict with url and page_id.
        """
        settings: BaseSettingsModel = await self.get_studio_settings()
        notion_cfg = settings.endpoints.notion.notion

        # Resolve Notion token from secret store
        secret_name = notion_cfg.api_key
        token = await Secrets.get(secret_name)
        if not token:
            raise ValueError("Notion API key secret is not set or not accessible on server")

        # Prefer request database_id if provided, else settings
        req_dbid = (payload.database_id or "").strip() if hasattr(payload, 'database_id') else ""
        cfg_dbid = (notion_cfg.database_id or "").strip()
        database_id = req_dbid or cfg_dbid
        logging.info(f"Debugly Notion: req_dbid='{req_dbid}', cfg_dbid set={bool(cfg_dbid)}")
        # Strip Notion view/query params if pasted from URL
        if database_id and "?" in database_id:
            database_id = database_id.split("?", 1)[0]
        logging.info(f"Debugly Notion: normalized database_id='{database_id}'")
        # Convert compact UUID (32 hex chars) to dashed UUID
        if database_id and len(database_id) == 32 and '-' not in database_id:
            database_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"
            logging.info(f"Debugly Notion: converted compact UUID to '{database_id}'")
        if not database_id:
            raise ValueError("Notion database ID is required in settings")

        service = NotionService(token=token, database_id=database_id)

        # Build a stable idempotency key to prevent duplicate page creation on retries
        idem_src = f"{payload.title}|{payload.user_message or ''}|{','.join(payload.tags or [])}"
        idempotency_key = hashlib.sha256(idem_src.encode('utf-8')).hexdigest()

        result = service.submit_issue(
            title=payload.title,
            user_message=payload.user_message or "",
            collected_data=payload.collected_data or {},
            tags=payload.tags or [],
            attachments_zip_b64=payload.attachments_zip_b64,
            assignee_id=(payload.assignee_id or getattr(notion_cfg, "assignee_id", "") or ""),
            idempotency_key=idempotency_key,
            rich_text=payload.rich_text,
            heading="",
            blocks=payload.blocks,
            title_property=payload.title_property,
        )
        return result
