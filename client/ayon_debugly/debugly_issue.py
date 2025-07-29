import os
import zipfile
import tempfile
import json
from datetime import datetime

class DebuglyIssue:
    def __init__(self, title, user_message, collected_data, attachments=None, screenshot=None, timestamp=None):
        self.title = title
        self.user_message = user_message
        self.collected_data = collected_data  # dict from collectors
        self.attachments = attachments or []  # list of file paths
        self.screenshot = screenshot  # file path or None
        self.timestamp = timestamp or datetime.utcnow().isoformat()

    def to_dict(self):
        return {
            "title": self.title,
            "user_message": self.user_message,
            "collected_data": self.collected_data,
            "attachments": self.attachments,
            "screenshot": self.screenshot,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            title=data.get("title", ""),
            user_message=data.get("user_message"),
            collected_data=data.get("collected_data", {}),
            attachments=data.get("attachments", []),
            screenshot=data.get("screenshot"),
            timestamp=data.get("timestamp"),
        )

    def to_zip(self, dest_path=None):
        if dest_path is None:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            dest_path = tmp.name
        with zipfile.ZipFile(dest_path, "w") as z:
            z.writestr("issue.json", json.dumps(self.to_dict(), indent=2))
            for f in self.attachments:
                if f and os.path.exists(f):
                    z.write(f, os.path.join("attachments", os.path.basename(f)))
            if self.screenshot and os.path.exists(self.screenshot):
                z.write(self.screenshot, os.path.join("screenshot", os.path.basename(self.screenshot)))
        return dest_path

    @classmethod
    def from_zip(cls, zip_path):
        with zipfile.ZipFile(zip_path, "r") as z:
            data = json.loads(z.read("issue.json").decode("utf-8"))
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
