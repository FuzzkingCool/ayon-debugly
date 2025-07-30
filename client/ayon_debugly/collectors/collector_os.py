from ayon_debugly.collectors.collector_base import CollectorBase
import platform
import socket
import time
import locale
import os

class CollectorOS(CollectorBase):
    def collect(self):
        info = {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": socket.gethostname(),
            "timezone": time.tzname,
            "locale": locale.getdefaultlocale(),
        }
        # Uptime
        try:
            if os.name == "posix":
                with open("/proc/uptime", "r") as f:
                    uptime_seconds = float(f.readline().split()[0])
                info["uptime_seconds"] = uptime_seconds
            elif os.name == "nt":
                import ctypes
                from ctypes import wintypes
                GetTickCount64 = ctypes.windll.kernel32.GetTickCount64
                GetTickCount64.restype = wintypes.ULONGLONG
                info["uptime_seconds"] = GetTickCount64() / 1000.0
        except Exception:
            info["uptime_seconds"] = None
        # Linux distribution
        if info["system"] == "Linux":
            try:
                import distro
                info["distro"] = distro.linux_distribution(full_distribution_name=True)
            except Exception:
                info["distro"] = platform.uname().system
        return {"os": info}
