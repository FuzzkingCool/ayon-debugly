"""List and download Debugly issue ZIPs from the configured shared folder (server-side)."""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import zipfile
from pathlib import Path
from typing import Any

from ayon_server.settings import BaseSettingsModel
from nxtools import logging as log


def _platform_folder_key() -> str:
    sysname = platform.system().lower()
    if sysname == "darwin":
        return "macos"
    if sysname == "windows":
        return "windows"
    return "linux"


def resolve_reports_dir(settings: BaseSettingsModel) -> tuple[str | None, str | None]:
    """Return (directory_path, error_message). None dir means unavailable."""
    try:
        endpoints = settings.endpoints
        sf = endpoints.shared_folder
        if not getattr(sf, "enabled", True):
            return None, "Shared folder endpoint is disabled in settings"
        cfg = sf.shared_folder
        key = _platform_folder_key()
        raw = getattr(cfg, key, None) or ""
        path = os.path.normpath(os.path.expanduser(str(raw).strip()))
        if not path:
            return None, f"No shared folder path configured for {key}"
        return path, None
    except Exception as e:
        log.warning(f"resolve_reports_dir: {e}")
        return None, str(e)


def _is_safe_zip_basename(name: str) -> bool:
    if not name or name != os.path.basename(name):
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    if not name.lower().endswith(".zip"):
        return False
    return True


def _is_safe_attachment_basename(name: str) -> bool:
    if not name or name != os.path.basename(name):
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    return True


def zip_path_under_root(root: str, zip_basename: str) -> Path | None:
    if not _is_safe_zip_basename(zip_basename):
        return None
    try:
        root_path = Path(root).expanduser().resolve()
        zpath = (root_path / zip_basename).resolve()
        zpath.relative_to(root_path)
    except (OSError, ValueError):
        return None
    if not zpath.is_file():
        return None
    return zpath


def load_issue_json_from_zip(zip_path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "issue.json" not in zf.namelist():
                return None
            raw = zf.read("issue.json")
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        log.debug(f"load_issue_json_from_zip {zip_path}: {e}")
        return None


def list_issues(root: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        root_path = Path(root)
        if not root_path.is_dir():
            return issues
        for p in sorted(root_path.iterdir(), key=lambda x: x.name.lower()):
            if not p.is_file() or not p.name.lower().endswith(".zip"):
                continue
            data = load_issue_json_from_zip(p)
            if data is None:
                continue
            data = dict(data)
            data["zip_file"] = p.name
            issues.append(data)
    except Exception as e:
        log.warning(f"list_issues: {e}")
    return issues


def read_zip_member(
    zip_path: Path, attachment_basename: str
) -> tuple[bytes, str] | None:
    if not _is_safe_attachment_basename(attachment_basename):
        return None
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            member_name: str | None = None
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                if name == attachment_basename or name.endswith("/" + attachment_basename):
                    member_name = name
                    break
            if member_name is None:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    if os.path.basename(name) == attachment_basename:
                        member_name = name
                        break
            if member_name is None:
                return None
            body = zf.read(member_name)
        ctype, _ = mimetypes.guess_type(attachment_basename)
        return body, ctype or "application/octet-stream"
    except Exception as e:
        log.debug(f"read_zip_member {zip_path} {attachment_basename}: {e}")
        return None


def attachment_response(zip_path: Path, attachment_basename: str) -> tuple[bytes, str, str]:
    """Returns (body, content_type, filename_for_disposition). Raises FileNotFoundError."""
    found = read_zip_member(zip_path, attachment_basename)
    if not found:
        raise FileNotFoundError("member not found")
    body, ctype = found
    return body, ctype, attachment_basename
