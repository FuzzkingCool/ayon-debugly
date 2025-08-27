import base64
import io
import zipfile
import threading
from typing import Any
import html as _html

import requests


class NotionService:
    def __init__(self, token: str, database_id: str, notion_version: str = "2022-06-28"):
        self.token = token
        self.database_id = database_id
        self.notion_version = notion_version
        self.base_url = "https://api.notion.com/v1"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": self.notion_version,
        }

    def _get_database_properties(self) -> dict[str, Any]:
        resp = requests.get(
            f"{self.base_url}/databases/{self.database_id}",
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            return {}
        return resp.json().get("properties", {})

    def submit_issue(
        self,
        title: str,
        user_message: str,
        collected_data: dict[str, Any],
        tags: list[str],
        attachments_zip_b64: str | None,
        assignee_id: str,
        idempotency_key: str | None = None,
        async_attachments: bool = True,
        rich_text: list[dict[str, Any]] | None = None,
        heading: str = "",
        blocks: list[dict[str, Any]] | None = None,
        title_property: str | None = None,
    ) -> dict[str, str]:
        properties = self._build_properties(title, tags, collected_data, assignee_id, title_property)
        # Prefer prebuilt blocks from client
        if blocks and isinstance(blocks, list) and len(blocks) > 0:
            # Use client-provided blocks as-is (no extra heading)
            children = blocks
        else:
            children = self._build_children(user_message, rich_text=rich_text, heading=heading)

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
            "children": children,
            "icon": {"type": "emoji", "emoji": "❓"},
        }

        headers = self._headers().copy()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        # More tolerant timeouts and a single retry on transient network errors
        resp = None
        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{self.base_url}/pages",
                    headers=headers,
                    json=payload,
                    timeout=(10, 90),
                )
                resp.raise_for_status()
                break
            except Exception:
                if attempt == 1:
                    raise
                # brief backoff
                import time
                time.sleep(1.0)
        data = resp.json()

        page_id = data.get("id", "")
        url = data.get("url", "")

        # Optionally attach files if provided via zip
        if attachments_zip_b64 and page_id:
            if async_attachments:
                t = threading.Thread(
                    target=self._safe_attach_wrapper,
                    args=(attachments_zip_b64, page_id),
                    daemon=True,
                )
                t.start()
            else:
                try:
                    self._attach_zip_to_page(attachments_zip_b64, page_id)
                except Exception:
                    pass

        return {"url": url, "page_id": page_id}

    def _build_properties(
        self,
        title: str,
        tags: list[str],
        collected_data: dict[str, Any],
        assignee_id: str,
        title_property_override: str | None = None,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        # Always fetch schema to validate title property key
        db_props = self._get_database_properties()

        # Title
        # Decide title property: prefer override if it exists and is a title; else find first 'title' type; else fallback "Title"
        title_key = None
        if title_property_override and title_property_override in db_props:
            if db_props[title_property_override].get("type") == "title":
                title_key = title_property_override
        if not title_key:
            title_key = next((k for k, v in db_props.items() if v.get("type") == "title"), None)
        if not title_key:
            title_key = "Title"
        properties[title_key] = {
            "title": [
                {
                    "type": "text",
                    "text": {"content": title[:2000]},
                }
            ]
        }

        # Tags
        if "Tags" in db_props and tags:
            properties["Tags"] = {"multi_select": [{"name": t} for t in tags if t]}

        # Submitted By (assignee)
        if "Submitted By" in db_props and assignee_id:
            properties["Submitted By"] = {"people": [{"id": assignee_id}]}

        return properties

    def _build_children(self, user_message: str, rich_text: list[dict[str, Any]] | None = None, heading: str = "") -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        if user_message or rich_text:
            text_input = user_message or ""
            if "<" in text_input and ">" in text_input:
                text_input = self._html_to_markdown(text_input)
            cleaned = self._clean_user_message(text_input)
            blocks = self._markdown_to_blocks(cleaned)
            if not blocks:
                rt = self._parse_markdown_to_rich_text(cleaned)
                blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt}}]
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
        text = re.sub(r"<h2[^>]*>([\s\S]*?)</h2>", r"## \1\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<h3[^>]*>([\s\S]*?)</h3>", r"### \1\n", text, flags=re.IGNORECASE)

        # Horizontal rule
        text = re.sub(r"<hr[^>]*>", "\n---\n", text, flags=re.IGNORECASE)

        # Bold/italic
        text = re.sub(r"<(?:b|strong)>([\s\S]*?)</(?:b|strong)>", r"**\1**", text, flags=re.IGNORECASE)
        text = re.sub(r"<(?:i|em)>([\s\S]*?)</(?:i|em)>", r"*\1*", text, flags=re.IGNORECASE)

        # Links
        def _a_to_md(m: re.Match) -> str:
            label = m.group(2) or m.group(1) or ""
            href = m.group(1) or ""
            return f"[{label}]({href})"

        text = re.sub(r"<a[^>]*href=\"([^\"]+)\"[^>]*>([\s\S]*?)</a>", _a_to_md, text, flags=re.IGNORECASE)

        # Paragraphs → ensure newline boundaries
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)

        # Strip any remaining tags (defensive)
        text = re.sub(r"<[^>]+>", "", text)

        return text.strip()

    def _parse_markdown_to_rich_text(self, markdown_text: str) -> list[dict[str, Any]]:
        import re
        rich_text_blocks: list[dict[str, Any]] = []
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        matches = list(re.finditer(link_pattern, markdown_text))
        if not matches:
            return [{"type": "text", "text": {"content": markdown_text}}]
        last_end = 0
        for match in matches:
            if match.start() > last_end:
                plain_text = markdown_text[last_end:match.start()]
                if plain_text:
                    rich_text_blocks.append({"type": "text", "text": {"content": plain_text}})
            link_text = match.group(1)
            link_url = match.group(2)
            if not link_url.startswith(("http://", "https://")):
                link_url = "https://" + link_url
            rich_text_blocks.append({
                "type": "text",
                "text": {"content": link_text, "link": {"url": link_url}},
            })
            last_end = match.end()
        if last_end < len(markdown_text):
            plain_text = markdown_text[last_end:]
            if plain_text:
                rich_text_blocks.append({"type": "text", "text": {"content": plain_text}})
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
                blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": line[4:]}}]}})
                i += 1
                continue
            if line.startswith("## "):
                blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]}})
                i += 1
                continue
            if line.startswith("# "):
                blocks.append({"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]}})
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
                blocks.append({"object": "block", "type": "quote", "quote": {"rich_text": self._parse_markdown_to_rich_text(quote_text)}})
                i += 1
                continue

            # Bulleted list
            if line.lstrip().startswith("- "):
                while i < len(lines) and lines[i].lstrip().startswith("- "):
                    item_text = lines[i].lstrip()[2:]
                    blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": self._parse_markdown_to_rich_text(item_text)}})
                    i += 1
                continue

            # Numbered list
            if re.match(r"\s*\d+\.\s+", line):
                while i < len(lines) and re.match(r"\s*\d+\.\s+", lines[i]):
                    item_text = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                    blocks.append({"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": self._parse_markdown_to_rich_text(item_text)}})
                    i += 1
                continue

            # Paragraph - collect until blank line
            para_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                para_lines.append(lines[i])
                i += 1
            para_text = "\n".join(para_lines)
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": self._parse_markdown_to_rich_text(para_text)}})

        return blocks

    def _attach_zip_to_page(self, attachments_zip_b64: str, page_id: str):
        raw = base64.b64decode(attachments_zip_b64)
        with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
            uploaded_files: list[dict[str, Any]] = []

            def guess_content_type(name: str) -> str:
                name_l = name.lower()
                if name_l.endswith(".png"):
                    return "image/png"
                if name_l.endswith(".jpg") or name_l.endswith(".jpeg"):
                    return "image/jpeg"
                if name_l.endswith(".gif"):
                    return "image/gif"
                if name_l.endswith(".pdf"):
                    return "application/pdf"
                if name_l.endswith(".txt") or name_l.endswith(".log"):
                    return "text/plain"
                if name_l.endswith(".md"):
                    return "text/markdown"
                if name_l.endswith(".csv"):
                    return "text/csv"
                if name_l.endswith(".json"):
                    return "application/json"
                return "text/plain"

            for zi in zf.infolist():
                # Only attach meaningful files under attachments/, screenshot/, logs/
                if not (zi.filename.startswith("attachments/") or zi.filename.startswith("screenshot/") or zi.filename.startswith("logs/")):
                    continue
                if zi.is_dir():
                    continue

                file_bytes = zf.read(zi)
                base_name = zi.filename.split("/")[-1]

                # Rename .log to .txt for Notion compatibility
                if base_name.lower().endswith(".log"):
                    display_name = base_name[:-4] + ".txt"
                else:
                    display_name = base_name

                content_type = guess_content_type(display_name)
                try:
                    file_id = self._upload_file_bytes(display_name, content_type, file_bytes)
                except Exception:
                    continue

                uploaded_files.append(
                    {
                        "type": "file_upload",
                        "file_upload": {"id": file_id},
                        "name": display_name,
                    }
                )

            if uploaded_files:
                self._update_page_attachments(page_id, uploaded_files)

    def _upload_file_bytes(self, file_name: str, content_type: str, file_bytes: bytes) -> str:
        # Step 1: create file upload object
        create_payload = {"filename": file_name, "content_type": content_type}
        resp = requests.post(
            f"{self.base_url}/file_uploads",
            headers=self._headers(),
            json=create_payload,
            timeout=60,
        )
        resp.raise_for_status()
        info = resp.json()
        file_upload_id = info["id"]
        upload_url = info["upload_url"]

        # Step 2: upload file content
        # Some Notion upload URLs accept multipart POST, mirroring client behavior
        files = {"file": (file_name, file_bytes, content_type)}
        resp2 = requests.post(
            upload_url,
            headers={
                "Authorization": self._headers()["Authorization"],
                "Notion-Version": self.notion_version,
            },
            files=files,
            timeout=300,
        )
        resp2.raise_for_status()

        return file_upload_id

    def _update_page_attachments(self, page_id: str, uploaded_files: list[dict[str, Any]]):
        payload = {"properties": {"Attachments": {"files": uploaded_files}}}
        resp = requests.patch(
            f"{self.base_url}/pages/{page_id}",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()

    def _safe_attach_wrapper(self, attachments_zip_b64: str, page_id: str) -> None:
        try:
            self._attach_zip_to_page(attachments_zip_b64, page_id)
        except Exception:
            # Background failures are non-fatal
            pass


