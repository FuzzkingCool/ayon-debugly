# -*- coding: utf-8 -*-
import os
import zipfile
import tempfile
import json
from datetime import datetime

class DebuglyIssue:
    def __init__(
        self,
        title,
        user_message,
        collected_data,
        attachments=None,
        screenshot=None,
        log_files=None,
        timestamp=None,
        tags=None,
        issue_type=None,
        project=None,
        pipeline_release=None,
    ):
        self.title = title
        self.user_message = user_message
        self.collected_data = collected_data  # dict from collectors
        self.attachments = attachments or []  # list of file paths
        self.screenshot = screenshot  # file path or None
        self.log_files = log_files or []  # list of log file paths
        self.timestamp = timestamp or datetime.utcnow().isoformat()
        self.tags = tags or []
        self.issue_type = issue_type
        self.project = project
        self.pipeline_release = pipeline_release

        # Track temporary files for cleanup
        self._temp_files = []
        
        # Create a separate JSON file for collected data
        self.collected_data_file = self._create_collected_data_file()

    def _create_collected_data_file(self):
        """Create a temporary JSON file containing the collected data"""
        if self.collected_data is None:
            return None

        # Create a temporary file for the collected data (text mode)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", prefix="debugly_collected_data_", mode='w', encoding='utf-8')
        json.dump(self.collected_data, tmp, indent=2)
        tmp.close()
        self._temp_files.append(tmp.name)
        return tmp.name

    def to_dict(self):
        d = {
            "title": self.title,
            "user_message": self.user_message,
            "collected_data": self.collected_data,
            "attachments": self.attachments,
            "screenshot": self.screenshot,
            "log_files": self.log_files,
            "timestamp": self.timestamp,
        }
        if self.tags:
            d["tags"] = self.tags
        if self.issue_type:
            d["issue_type"] = self.issue_type
        if self.project:
            d["project"] = self.project
        if self.pipeline_release:
            d["pipeline_release"] = self.pipeline_release
        return d

    def _issue_dict_for_zip(self) -> dict:
        """Manifest for issue.json inside the ZIP: no embedded collected_data (see collected_data.json)."""
        d = self.to_dict()
        d.pop("collected_data", None)
        if self.collected_data_file and os.path.exists(self.collected_data_file):
            d["collected_data_in_archive"] = "collected_data.json"
        return d

    @classmethod
    def from_dict(cls, data, attachments=None, screenshot=None):
        return cls(
            title=data.get("title", ""),
            user_message=data.get("user_message"),
            collected_data=data.get("collected_data", {}),
            attachments=(
                attachments if attachments is not None else data.get("attachments", [])
            ),
            screenshot=(
                screenshot if screenshot is not None else data.get("screenshot")
            ),
            log_files=data.get("log_files", []),
            timestamp=data.get("timestamp"),
            tags=data.get("tags"),
            issue_type=data.get("issue_type"),
            project=data.get("project"),
            pipeline_release=data.get("pipeline_release"),
        )

    def to_zip(self, dest_path=None):
        if dest_path is None:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            dest_path = tmp.name
        with zipfile.ZipFile(dest_path, "w") as z:
            z.writestr("issue.json", json.dumps(self._issue_dict_for_zip(), indent=2))
            
            # Add collected data file
            if self.collected_data_file and os.path.exists(self.collected_data_file):
                z.write(self.collected_data_file, "collected_data.json")
            
            for f in self.attachments:
                if f and os.path.exists(f):
                    z.write(f, os.path.join("attachments", os.path.basename(f)))
            if self.screenshot and os.path.exists(self.screenshot):
                z.write(self.screenshot, os.path.join("screenshot", os.path.basename(self.screenshot)))
            
            # Add redacted log files to logs subfolder
            from ayon_debugly.collectors.collector_base import redact_log_content
            for log_file in self.log_files:
                if log_file and os.path.exists(log_file):
                    try:
                        # Read and redact the log file
                        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        redacted_content = redact_log_content(content)
                        
                        # Add redacted content to ZIP
                        base_name = os.path.basename(log_file)
                        name, ext = os.path.splitext(base_name)
                        redacted_name = f"{name}_redacted{ext}"
                        z.writestr(os.path.join("logs", redacted_name), redacted_content)
                    except Exception:
                        # If redaction fails, skip this file for safety
                        continue
        return dest_path

    def cleanup(self):
        """Clean up temporary files created by this issue"""
        for temp_file in self._temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except OSError:
                pass  # Ignore errors during cleanup
        
        self._temp_files.clear()

    @classmethod
    def from_zip(cls, zip_path):
        with zipfile.ZipFile(zip_path, "r") as z:
            data = json.loads(z.read("issue.json").decode("utf-8"))
            data.pop("collected_data_in_archive", None)
            if not data.get("collected_data") and "collected_data.json" in z.namelist():
                data["collected_data"] = json.loads(
                    z.read("collected_data.json").decode("utf-8")
                )
            # Optionally extract attachments/screenshot if needed
            attachments = []
            for f in z.namelist():
                if f.startswith("attachments/"):
                    attachments.append(os.path.join(zip_path, f))

            if "screenshot" in data:
                screenshot = os.path.join(zip_path, data["screenshot"])
                # extract screenshot to temp file
                with open(screenshot, "rb") as f:
                    screenshot = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                    screenshot.write(f.read())
                    screenshot.flush()
            else:
                screenshot = None



            return cls.from_dict(data, attachments=attachments, screenshot=screenshot)
