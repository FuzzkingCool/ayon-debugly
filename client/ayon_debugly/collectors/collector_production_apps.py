from .collector_base import CollectorBase
import os
import sys

try:
    import psutil
except ImportError:
    psutil = None

class CollectorProductionApps(CollectorBase):
    def __init__(self, software_checks=None, settings=None):
        """Check for running software/processes as specified in settings or defaults."""
        if settings and hasattr(settings, "software_checks"):
            self.software_checks = settings.software_checks
        else:
            self.software_checks = software_checks or []
        self.platform = self._get_platform()

    def _get_platform(self):
        if sys.platform.startswith("win"): return "windows"
        if sys.platform == "darwin": return "macos"
        return "linux"

    def collect(self):
        results = []
        for sw in self.software_checks:
            # Support both new nested model and dict fallback
            name = getattr(sw, 'name', None) or (sw.get("name") if isinstance(sw, dict) else None)
            plat = self.platform
            exe = None
            path = None
            # New nested model
            if hasattr(sw, plat):
                plat_obj = getattr(sw, plat)
                exe = getattr(plat_obj, 'exe', None)
                path = getattr(plat_obj, 'path', None)
            # Fallback for dict
            elif isinstance(sw, dict) and plat in sw:
                plat_obj = sw[plat]
                exe = plat_obj.get('exe')
                path = plat_obj.get('path')
            found = False
            version = None
            if exe:
                if psutil:
                    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
                        try:
                            if exe.lower() in (proc.info["name"] or "").lower():
                                found = True
                                # Try to get version from exe path if possible
                                exe_path = proc.info.get("exe")
                                if exe_path and os.path.exists(exe_path):
                                    version = self._get_version_from_exe(exe_path)
                                break
                        except Exception:
                            continue
                else:
                    # Fallback: use os.popen for 'tasklist' (Windows) or 'ps' (Unix)
                    if sys.platform == "win32":
                        try:
                            out = os.popen(f'tasklist /FI "IMAGENAME eq {exe}"').read()
                            if exe.lower() in out.lower():
                                found = True
                        except Exception:
                            pass
                    else:
                        try:
                            out = os.popen(f'ps aux | grep {exe}').read()
                            if exe.lower() in out.lower():
                                found = True
                        except Exception:
                            pass
            results.append({
                "name": name,
                "platform": plat,
                "exe": exe,
                "install_path": path,
                "running": found,
                "version": version
            })
        return {"production_apps": results}

    def _get_version_from_exe(self, exe_path):
        # Platform-specific: try to get version from exe metadata
        # For now, just return the file's mtime as a placeholder
        try:
            return str(os.path.getmtime(exe_path))
        except Exception:
            return None
