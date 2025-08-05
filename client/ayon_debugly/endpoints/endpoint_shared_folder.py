# -*- coding: utf-8 -*-
"""Simple endpoint that uses a Shared Folder on the server to store reports"""
import os
import shutil
import sys

import ayon_api

from ayon_debugly.endpoints.endpoint_base import EndpointBase
from ayon_debugly.logger import log
from ayon_debugly.ui.dialogs import show_warning


class EndpointSharedFolder(EndpointBase):
    def __init__(self, settings=None):
        self.settings = settings
        self.shared_folder = None
        super().__init__()  # Call parent __init__ to initialize _temp_files
        self.initialize()

    def initialize(self):
        log.debug("Starting initialize() method")
        # Use platform-specific shared_folder from settings
        plat = self._get_os()
        log.debug(f"Platform: {plat}")
        shared_folder = None
        if self.settings and hasattr(self.settings, "endpoints") and hasattr(self.settings.endpoints, "shared_folder"):
            log.debug("Using object-based settings")
            # Check if Shared Folder is enabled at section level
            if hasattr(self.settings.endpoints.shared_folder, "enabled") and not self.settings.endpoints.shared_folder.enabled:
                raise Exception("Shared Folder endpoint is disabled in settings")
            shared_folder_obj = self.settings.endpoints.shared_folder.shared_folder
            shared_folder = getattr(shared_folder_obj, plat, None)
        elif (self.settings and isinstance(self.settings, dict) and 
              "endpoints" in self.settings and 
              "shared_folder" in self.settings["endpoints"] and
              "shared_folder" in self.settings["endpoints"]["shared_folder"]):
            log.debug("Using dict-based settings")
            # Check if Shared Folder is enabled at section level
            if "enabled" in self.settings["endpoints"]["shared_folder"] and not self.settings["endpoints"]["shared_folder"]["enabled"]:
                raise Exception("Shared Folder endpoint is disabled in settings")
            shared_folder_obj = self.settings["endpoints"]["shared_folder"]["shared_folder"]
            shared_folder = shared_folder_obj.get(plat, None)
        if not shared_folder:
            shared_folder = os.path.expanduser("~/ayon_reports")
        
        log.debug(f"Raw shared_folder from settings: {shared_folder}")
        
        # Expand the path
        self.shared_folder = os.path.expanduser(shared_folder)
        # Normalize the path to handle any double backslash issues
        self.shared_folder = os.path.normpath(self.shared_folder)
        log.debug(f"[DEBUG] Original shared_folder: {shared_folder}")
        log.debug(f"[DEBUG] Expanded shared_folder: {self.shared_folder}")
        log.debug(f"[DEBUG] Normalized shared_folder: {self.shared_folder}")
        
        # Try to create the directory with better error handling
        try:
            # First, let's diagnose the P: drive issue
            log.debug(f"[DEBUG] Attempting to create directory: {self.shared_folder}")
            
            # Check if we can access the drive root
            drive, path = os.path.splitdrive(self.shared_folder)
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
                with open(test_file, 'w', encoding='utf-8') as f:
                    f.write("test")
                os.remove(test_file)
                log.debug("[DEBUG] Write permission test passed")
            except Exception as e:
                log.debug(f"[DEBUG] Write permission test failed: {e}")
            
            # Now try to create the directory
            if not os.path.exists(self.shared_folder):
                log.debug("[DEBUG] Directory does not exist, creating...")
                os.makedirs(self.shared_folder, exist_ok=True)
                log.debug(f"[DEBUG] Successfully created directory: {self.shared_folder}")
            else:
                log.debug(f"[DEBUG] Directory already exists: {self.shared_folder}")
            
            log.debug(f"[OK] Shared Folder ready: {self.shared_folder}")
        except (OSError, PermissionError) as e:
            log.error(f"[ERROR] Could not create Shared Folder '{self.shared_folder}': {e}")
            
            # Show PyQt warning dialog
            show_warning(
                f"Could not access the configured Shared Folder:\n{self.shared_folder}\n\n"
                f"Error: {str(e)}\n\n"
                "This may be due to network connectivity issues or the directory not being available.\n\n"
                "Please try closing and relaunching the AYON launcher.",
                "AYON Debugly - Directory Error"
            )
            
            raise Exception(f"Shared Folder '{self.shared_folder}' is not accessible. Please check your network connection and try relaunching AYON.")

    def _get_os(self):
        if sys.platform.startswith("win"):
            return "windows"
        if sys.platform == "darwin":
            return "macos"
        return "linux"

    def get_shared_folder_from_server():
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
                hasattr(settings.endpoints, "shared_folder") and
                hasattr(settings.endpoints.shared_folder, "shared_folder")):
                # Check if Shared Folder is enabled at section level
                if hasattr(settings.endpoints.shared_folder, "enabled") and not settings.endpoints.shared_folder.enabled:
                    raise Exception("Shared Folder endpoint is disabled in settings")
                shared_folder_obj = settings.endpoints.shared_folder.shared_folder
                shared_folder = getattr(shared_folder_obj, _platform, "~/ayon_reports")
                return os.path.expanduser(shared_folder)
            else:
                return os.path.expanduser("~/ayon_reports")
        except Exception:
            return os.path.expanduser("~/ayon_reports")

    def submit(self, issue):
        zip_path = issue.to_zip()
        
        # Create a meaningful filename with title and date
        import re
        from datetime import datetime
        
        # Clean the title for use in filename (remove special chars, limit length)
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', issue.title)
        safe_title = safe_title[:50]  # Limit length
        safe_title = safe_title.strip()
        
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create filename: debugly_YYYYMMDD_HHMMSS_title.zip
        filename = f"debugly_{timestamp}_{safe_title}.zip"
        
        dest_path = os.path.join(self.shared_folder, filename)
        shutil.move(zip_path, dest_path)
        return {"file_path": dest_path, "filename": filename}
    
    def get_success_info(self, result):
        """
        Get Shared Folder-specific success information to display to the user
        
        Args:
            result: The result returned by the submit method (dict with file_path and filename)
            
        Returns:
            dict: Dictionary containing success information
        """
        if isinstance(result, dict) and "file_path" in result:
            return {
                "title": "Shared Folder",
                "message": f"Report saved to shared folder: {result['filename']}",
                "url": None,
                "file_path": result["file_path"],
                "can_open": True
            }
        else:
            # Fallback for old format
            return {
                "title": "Shared Folder",
                "message": "Report saved to shared folder",
                "url": None,
                "file_path": result if isinstance(result, str) else None,
                "can_open": True
            }
    