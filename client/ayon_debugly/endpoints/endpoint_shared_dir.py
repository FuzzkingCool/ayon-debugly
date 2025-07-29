"""Simple endpoint that uses a shared directory on the server to store reports"""
import os
from .endpoint_base import EndpointBase
import ayon_api
import shutil
import sys


class EndpointSharedDir(EndpointBase):
    def __init__(self, settings=None):
        self.settings = settings
        self.shared_dir = None
        self.initialize()

    def initialize(self):
        # Use platform-specific shared_dir from settings
        plat = self._get_os()
        shared_dir = None
        if self.settings and hasattr(self.settings, "shared_dir"):
            shared_dir_obj = self.settings.shared_dir
            shared_dir = getattr(shared_dir_obj, plat, None)
        if not shared_dir:
            shared_dir = os.path.expanduser("~/ayon_reports")
        self.shared_dir = os.path.expanduser(shared_dir)
        os.makedirs(self.shared_dir, exist_ok=True)

    def _get_os(self):
        if sys.platform.startswith("win"): return "windows"
        if sys.platform == "darwin": return "macos"
        return "linux"

    def get_shared_dir_from_server():
        # Connect to AYON server (make sure env vars or config are set for URL/token)
        # ayon_api.init_service()  # If running as a service, or use ayon_api.login_to_server() for user login

        # Fetch the settings for your addon (replace 'debugly' with your actual addon name if different)
        settings = ayon_api.get_addon_settings("debugly")
        _platform = sys.platform
        if _platform.startswith("win"): _platform = "windows"
        elif _platform == "darwin": _platform = "macos"
        else: _platform = "linux"
        shared_dir = settings.get("shared_dir", {}).get(_platform, "~/ayon_reports")
        return os.path.expanduser(shared_dir)

    def submit(self, issue):
        zip_path = issue.to_zip()
        dest_path = os.path.join(self.shared_dir, os.path.basename(zip_path))
        shutil.move(zip_path, dest_path)
        return dest_path
    