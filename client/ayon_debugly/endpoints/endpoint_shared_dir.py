"""Simple endpoint that uses a shared directory on the server to store reports"""
import os
import shutil
import sys

import ayon_api

from ayon_debugly.endpoints.endpoint_base import EndpointBase
from ayon_debugly.ui.dialogs import show_warning
from ayon_debugly.logger import log


class EndpointSharedDir(EndpointBase):
    def __init__(self, settings=None):
        self.settings = settings
        self.shared_dir = None
        self.initialize()

    def initialize(self):
        log.debug("Starting initialize() method")
        # Use platform-specific shared_dir from settings
        plat = self._get_os()
        log.debug(f"Platform: {plat}")
        shared_dir = None
        if self.settings and hasattr(self.settings, "endpoints") and hasattr(self.settings.endpoints, "shared_dir"):
            log.debug("Using object-based settings")
            # Check if shared directory is enabled at section level
            if hasattr(self.settings.endpoints.shared_dir, "enabled") and not self.settings.endpoints.shared_dir.enabled:
                raise Exception("Shared directory endpoint is disabled in settings")
            shared_dir_obj = self.settings.endpoints.shared_dir.shared_dir
            shared_dir = getattr(shared_dir_obj, plat, None)
        elif (self.settings and isinstance(self.settings, dict) and 
              "endpoints" in self.settings and 
              "shared_dir" in self.settings["endpoints"] and
              "shared_dir" in self.settings["endpoints"]["shared_dir"]):
            log.debug("Using dict-based settings")
            # Check if shared directory is enabled at section level
            if "enabled" in self.settings["endpoints"]["shared_dir"] and not self.settings["endpoints"]["shared_dir"]["enabled"]:
                raise Exception("Shared directory endpoint is disabled in settings")
            shared_dir_obj = self.settings["endpoints"]["shared_dir"]["shared_dir"]
            shared_dir = shared_dir_obj.get(plat, None)
        if not shared_dir:
            shared_dir = os.path.expanduser("~/ayon_reports")
        
        log.debug(f"Raw shared_dir from settings: {shared_dir}")
        
        # Expand the path
        self.shared_dir = os.path.expanduser(shared_dir)
        # Normalize the path to handle any double backslash issues
        self.shared_dir = os.path.normpath(self.shared_dir)
        log.debug(f"[DEBUG] Original shared_dir: {shared_dir}")
        log.debug(f"[DEBUG] Expanded shared_dir: {self.shared_dir}")
        log.debug(f"[DEBUG] Normalized shared_dir: {self.shared_dir}")
        
        # Try to create the directory with better error handling
        try:
            # First, let's diagnose the P: drive issue
            log.debug(f"[DEBUG] Attempting to create directory: {self.shared_dir}")
            
            # Check if we can access the drive root
            drive, path = os.path.splitdrive(self.shared_dir)
            log.debug(f"[DEBUG] Drive: '{drive}', Path: '{path}'")
            
            # Test drive accessibility more thoroughly
            drive_root = drive + "\\"
            log.debug(f"[DEBUG] Testing drive root: '{drive_root}'")
            
            try:
                # Try to list contents of the drive root
                contents = os.listdir(drive_root)
                log.debug(f"[DEBUG] Drive root contents: {contents[:5]}...")  # Show first 5 items
            except Exception as e:
                log.debug(f"[DEBUG] Cannot list drive root contents: {e}")
            
            # Try to create a test file to check write permissions
            test_file = os.path.join(drive_root, "test_write_permission.tmp")
            try:
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                log.debug("[DEBUG] Write permission test passed")
            except Exception as e:
                log.debug(f"[DEBUG] Write permission test failed: {e}")
            
            # Now try to create the directory
            if not os.path.exists(self.shared_dir):
                log.debug("[DEBUG] Directory does not exist, creating...")
                os.makedirs(self.shared_dir, exist_ok=True)
                log.debug(f"[DEBUG] Successfully created directory: {self.shared_dir}")
            else:
                log.debug(f"[DEBUG] Directory already exists: {self.shared_dir}")
            
            log.debug(f"[OK] Shared directory ready: {self.shared_dir}")
        except (OSError, PermissionError) as e:
            log.error(f"[ERROR] Could not create shared directory '{self.shared_dir}': {e}")
            
            # Show PyQt warning dialog
            show_warning(
                f"Could not access the configured shared directory:\n{self.shared_dir}\n\n"
                f"Error: {str(e)}\n\n"
                "This may be due to network connectivity issues or the directory not being available.\n\n"
                "Please try closing and relaunching the AYON launcher.",
                "AYON Debugly - Directory Error"
            )
            
            raise Exception(f"Shared directory '{self.shared_dir}' is not accessible. Please check your network connection and try relaunching AYON.")

    def _get_os(self):
        if sys.platform.startswith("win"):
            return "windows"
        if sys.platform == "darwin":
            return "macos"
        return "linux"

    def get_shared_dir_from_server():
        # Connect to AYON server (make sure env vars or config are set for URL/token)
        # ayon_api.init_service()  # If running as a service, or use ayon_api.login_to_server() for user login

        # Fetch the settings for your addon (replace 'debugly' with your actual addon name if different)
        try:
            from ayon_debugly.version import __version__
            settings = ayon_api.get_addon_settings("debugly", __version__)
            _platform = sys.platform
            if _platform.startswith("win"):
                _platform = "windows"
            elif _platform == "darwin":
                _platform = "macos"
            else: _platform = "linux"
            
            if (hasattr(settings, "endpoints") and 
                hasattr(settings.endpoints, "shared_dir") and
                hasattr(settings.endpoints.shared_dir, "shared_dir")):
                # Check if shared directory is enabled at section level
                if hasattr(settings.endpoints.shared_dir, "enabled") and not settings.endpoints.shared_dir.enabled:
                    raise Exception("Shared directory endpoint is disabled in settings")
                shared_dir_obj = settings.endpoints.shared_dir.shared_dir
                shared_dir = getattr(shared_dir_obj, _platform, "~/ayon_reports")
                return os.path.expanduser(shared_dir)
            else:
                return os.path.expanduser("~/ayon_reports")
        except Exception:
            return os.path.expanduser("~/ayon_reports")

    def submit(self, issue):
        zip_path = issue.to_zip()
        
        # Create a meaningful filename with title and date
        from datetime import datetime
        import re
        
        # Clean the title for use in filename (remove special chars, limit length)
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', issue.title)
        safe_title = safe_title[:50]  # Limit length
        safe_title = safe_title.strip()
        
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create filename: debugly_YYYYMMDD_HHMMSS_title.zip
        filename = f"debugly_{timestamp}_{safe_title}.zip"
        
        dest_path = os.path.join(self.shared_dir, filename)
        shutil.move(zip_path, dest_path)
        return dest_path
    