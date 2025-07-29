from .collector_base import CollectorBase
import getpass
import os
import sys
import time

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
                import subprocess
                out = subprocess.check_output(["who", "-m"]).decode()
                info["login_time"] = out.strip()
            except Exception:
                info["login_time"] = None
        else:
            # Windows: try to get shell and login time
            info["shell"] = os.environ.get("ComSpec")
            info["login_time"] = None
        return {"user": info}
