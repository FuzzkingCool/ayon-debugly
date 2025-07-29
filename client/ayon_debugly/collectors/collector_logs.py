from .collector_base import CollectorBase
import os
import sys

class CollectorLogs(CollectorBase):
    def __init__(self, log_dirs=None, tail_lines=20, settings=None):
        """Collect logs from directories specified in settings or defaults."""
        self.tail_lines = tail_lines
        self.log_dirs = []
        if settings and hasattr(settings, "log_dirs"):
            plat = self._get_platform()
            for entry in settings.log_dirs:
                log_dir = getattr(entry, plat, None)
                if log_dir:
                    self.log_dirs.append(os.path.expanduser(log_dir))
        elif log_dirs:
            self.log_dirs = [os.path.expanduser(ld) for ld in log_dirs]
        else:
            # No logs if not specified
            self.log_dirs = []

    def _get_platform(self):
        if sys.platform.startswith("win"):
            return "windows"
        if sys.platform == "darwin":
            return "macos"
        return "linux"

    def collect(self):
        files = []
        for log_dir in self.log_dirs:
            if not log_dir or not os.path.exists(log_dir):
                continue
            for f in os.listdir(log_dir):
                path = os.path.join(log_dir, f)
                if os.path.isfile(path):
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                            lines = fp.readlines()
                            tail = lines[-self.tail_lines:] if len(lines) > self.tail_lines else lines
                        files.append({
                            "path": path,
                            "size": os.path.getsize(path),
                            "mtime": os.path.getmtime(path),
                            "tail": "".join(tail)
                        })
                    except Exception:
                        files.append({
                            "path": path,
                            "size": os.path.getsize(path),
                            "mtime": os.path.getmtime(path),
                            "tail": "<unreadable>"
                        })
        return {"log_files": files}
