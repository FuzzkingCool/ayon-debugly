from ayon_debugly.collectors.collector_base import CollectorBase
import getpass
import os
import sys
import time
import ayon_api

class CollectorUser(CollectorBase):
    def collect(self):
        info = {
            "user": getpass.getuser(),
            "home": os.path.expanduser("~"),
        }
        
        # User ID, groups, shell (Unix)
        if hasattr(os, "getuid"):
            try:
                info["uid"] = os.getuid()
                info["groups"] = os.getgroups()
                info["shell"] = os.environ.get("SHELL")
            except Exception:
                pass
        # Login time (Unix)
        if sys.platform != "win32":
            try:
                import pwd
                from ayon_debugly.utils.subprocess_utils import check_output_silent
                out = check_output_silent(["who", "-m"])
                info["login_time"] = out.strip()
            except Exception:
                info["login_time"] = None
        else:
            # Windows: try to get shell and login time
            info["shell"] = os.environ.get("ComSpec")
            info["login_time"] = None
        
        # AYON account information
        try:
            ayon_user_info = self._get_ayon_user_info()
            info.update(ayon_user_info)
        except Exception as e:
            info["ayon_error"] = str(e)
        
        return {"user": info}
    
    def _get_ayon_user_info(self):
        """Get AYON account information from the API."""
        try:
            # Get current user info from AYON API
            user_info = ayon_api.get_user()
            
            ayon_data = {
                "ayon_username": user_info.get("name", "unknown"),
                "ayon_active": user_info.get("active", False),
            }
            
            # Get user details from attrib
            if user_info.get("attrib"):
                attrib = user_info["attrib"]
                ayon_data.update({
                    "ayon_full_name": attrib.get("fullName", "unknown"),
                    "ayon_email": attrib.get("email", "unknown"),
                })
            
            # Get additional user details from data
            if user_info.get("data"):
                data = user_info["data"]
                ayon_data.update({
                    "ayon_is_admin": data.get("isAdmin", False),
                    "ayon_is_developer": data.get("isDeveloper", False),
                    "ayon_is_manager": data.get("isManager", False),
                    "ayon_is_guest": data.get("isGuest", False),
                })
            
            return ayon_data
            
        except Exception as e:
            return {
                "ayon_username": "unknown",
                "ayon_error": f"Could not fetch AYON user info: {e}"
            }
