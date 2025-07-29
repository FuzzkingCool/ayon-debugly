from .collector_base import CollectorBase
import platform
import sys
import os

try:
    import psutil
except ImportError:
    psutil = None

class CollectorSystemSpec(CollectorBase):
    def collect(self):
        info = {
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
                "executable": sys.executable,
            },
            "cpu": platform.processor(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        }
        # RAM
        if psutil:
            try:
                info["ram"] = {
                    "total": psutil.virtual_memory().total,
                    "available": psutil.virtual_memory().available,
                }
            except Exception:
                info["ram"] = None
        # Disk
        try:
            if psutil:
                disk = psutil.disk_usage(os.path.expanduser("~"))
                info["disk"] = {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                }
            else:
                stat = os.statvfs(os.path.expanduser("~"))
                info["disk"] = {
                    "total": stat.f_frsize * stat.f_blocks,
                    "free": stat.f_frsize * stat.f_bfree,
                }
        except Exception:
            info["disk"] = None
        # GPU (very basic, platform-dependent)
        try:
            import subprocess
            if sys.platform == "win32":
                out = os.popen('wmic path win32_VideoController get name').read()
                info["gpu"] = out.strip().split("\n")[1:]
            elif sys.platform == "darwin":
                out = subprocess.check_output(["system_profiler", "SPDisplaysDataType"]).decode()
                info["gpu"] = [line.strip() for line in out.split("\n") if "Chipset Model" in line]
            else:
                out = os.popen('lspci | grep VGA').read()
                info["gpu"] = [line.strip() for line in out.split("\n") if line]
        except Exception:
            info["gpu"] = None
        # Installed Python packages
        try:
            import pkg_resources
            info["python_packages"] = sorted([str(d) for d in pkg_resources.working_set])
        except Exception:
            info["python_packages"] = None
        return {"system_spec": info}
