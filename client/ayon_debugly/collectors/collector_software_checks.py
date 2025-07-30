import os
import subprocess
import sys

import ayon_api

from ayon_debugly.collectors.collector_base import CollectorBase


class CollectorSoftwareChecks(CollectorBase):
    def __init__(self):
        """Check for running software/processes as specified in AYON server settings."""
        self.platform = self._get_platform()
        self.software_checks = self._get_software_checks_from_settings()

    def _get_software_checks_from_settings(self):
        """Get software checks from AYON server settings."""
        try:
            from ayon_debugly.version import __version__
            print(f"Loading software checks with version: {__version__}")
            settings = ayon_api.get_addon_settings("debugly", __version__)
            print(f"Settings object type: {type(settings)}")
            print(f"Settings attributes: {[attr for attr in dir(settings) if not attr.startswith('_')]}")
            
            if hasattr(settings, "software_checks"):
                software_checks = settings.software_checks
                print(f"[OK] Loaded {len(software_checks)} software checks from AYON settings")
                for i, check in enumerate(software_checks):
                    print(f"  {i+1}. {getattr(check, 'name', 'Unknown')}")
                return software_checks
            elif isinstance(settings, dict) and "software_checks" in settings:
                software_checks = settings["software_checks"]
                print(f"[OK] Loaded {len(software_checks)} software checks from AYON settings (dict)")
                for i, check in enumerate(software_checks):
                    print(f"  {i+1}. {check.get('name', 'Unknown')}")
                return software_checks
            print("[WARN] No software_checks found in AYON settings")
            return []
        except Exception as e:
            print(f"[ERROR] Could not load software checks from AYON settings: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _get_platform(self):
        if sys.platform.startswith("win"): return "windows"
        if sys.platform == "darwin": return "macos"
        return "linux"

    def _check_install_path(self, install_path, exe_name):
        """Check if software is installed at the specified path."""
        if not install_path or not exe_name:
            return False, None, None
        
        # Try to find the executable in the install path
        possible_exe_paths = []
        
        # Direct path to executable
        if sys.platform.startswith("win"):
            exe_path = os.path.join(install_path, exe_name)
            possible_exe_paths.append(exe_path)
            # Also try with .exe extension if not present
            if not exe_name.lower().endswith('.exe'):
                exe_path = os.path.join(install_path, f"{exe_name}.exe")
                possible_exe_paths.append(exe_path)
        else:
            exe_path = os.path.join(install_path, exe_name)
            possible_exe_paths.append(exe_path)
            # For macOS, also try .app bundles
            if not exe_name.lower().endswith('.app'):
                app_path = os.path.join(install_path, f"{exe_name}.app")
                possible_exe_paths.append(app_path)
        
        # Check if any of the possible paths exist
        for exe_path in possible_exe_paths:
            if os.path.exists(exe_path):
                version = self._get_version_from_exe(exe_path)
                return True, exe_path, version
        
        return False, None, None

    def _get_version_from_exe(self, exe_path):
        """Get version information from executable file using vanilla Python."""
        try:
            if sys.platform.startswith("win"):
                return self._get_windows_version(exe_path)
            elif sys.platform == "darwin":
                return self._get_macos_version(exe_path)
            else:
                return self._get_linux_version(exe_path)
        except Exception as e:
            print(f"[WARN] Could not get version from {exe_path}: {e}")
            return None

    def _get_windows_version(self, exe_path):
        """Get version from Windows executable using vanilla Python."""
        try:
            # Try to get version using PowerShell
            cmd = [
                'powershell', '-Command', 
                f'(Get-Item "{exe_path}").VersionInfo.FileVersion'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            
            # Fallback to file modification time
            return f"mtime:{os.path.getmtime(exe_path)}"
        except Exception:
            return None

    def _get_macos_version(self, exe_path):
        """Get version from macOS application using vanilla Python."""
        try:
            if exe_path.endswith('.app'):
                # For .app bundles, try to get version from Info.plist
                info_plist = os.path.join(exe_path, 'Contents', 'Info.plist')
                if os.path.exists(info_plist):
                    result = subprocess.run(['defaults', 'read', info_plist, 'CFBundleShortVersionString'], 
                                          capture_output=True, text=True)
                    if result.returncode == 0:
                        return result.stdout.strip()
            
            # Try to get version using mdls (metadata)
            result = subprocess.run(['mdls', '-name', 'kMDItemVersion', exe_path], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                version = result.stdout.strip()
                if version and 'kMDItemVersion = ' in version:
                    return version.split('=')[1].strip().strip('"')
            
            # Fallback to file modification time
            return f"mtime:{os.path.getmtime(exe_path)}"
        except Exception:
            return None

    def _get_linux_version(self, exe_path):
        """Get version from Linux executable using vanilla Python."""
        try:
            # Try to get version by running the executable with --version
            result = subprocess.run([exe_path, '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
            
            # Try -v flag
            result = subprocess.run([exe_path, '-v'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
            
            # Fallback to file modification time
            return f"mtime:{os.path.getmtime(exe_path)}"
        except Exception:
            return None

    def _check_running_process(self, exe_name):
        """Check if a process is currently running using vanilla Python."""
        if not exe_name:
            return False, None
        
        try:
            if sys.platform == "win32":
                # Use tasklist on Windows
                result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {exe_name}'], 
                                      capture_output=True, text=True)
                if result.returncode == 0 and exe_name.lower() in result.stdout.lower():
                    # Try to get the executable path using wmic
                    try:
                        wmic_result = subprocess.run([
                            'wmic', 'process', 'where', f'name="{exe_name}"', 'get', 'executablepath'
                        ], capture_output=True, text=True)
                        if wmic_result.returncode == 0:
                            lines = wmic_result.stdout.strip().split('\n')
                            if len(lines) > 1:
                                exe_path = lines[1].strip()
                                if exe_path and exe_path != 'ExecutablePath':
                                    return True, exe_path
                    except Exception:
                        pass
                    return True, None
            else:
                # Use ps on Unix systems
                result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
                if result.returncode == 0 and exe_name.lower() in result.stdout.lower():
                    # Try to get executable path
                    try:
                        ps_result = subprocess.run(['which', exe_name], capture_output=True, text=True)
                        if ps_result.returncode == 0:
                            exe_path = ps_result.stdout.strip()
                            if exe_path:
                                return True, exe_path
                    except Exception:
                        pass
                    return True, None
        except Exception as e:
            print(f"[WARN] Error checking running process {exe_name}: {e}")
        
        return False, None

    def collect(self):
        """Collect software check information."""
        print("Starting software checks collection...")
        results = []
        
        for sw in self.software_checks:
            # Handle both object and dictionary settings
            if hasattr(sw, 'name'):
                # Object-based settings
                name = getattr(sw, 'name', 'Unknown')
                plat = self.platform
                exe = None
                install_path = None
                
                # Get platform-specific settings
                if hasattr(sw, plat):
                    plat_obj = getattr(sw, plat)
                    exe = getattr(plat_obj, 'exe', None)
                    install_path = getattr(plat_obj, 'path', None)
            else:
                # Dictionary-based settings
                name = sw.get('name', 'Unknown')
                plat = self.platform
                exe = None
                install_path = None
                
                # Get platform-specific settings
                if plat in sw:
                    plat_obj = sw[plat]
                    exe = plat_obj.get('exe', None)
                    install_path = plat_obj.get('path', None)
            
            print(f"Checking {name} (platform: {plat})")
            print(f"  - Executable: {exe}")
            print(f"  - Install path: {install_path}")
            
            # Check if installed
            installed = False
            install_version = None
            actual_exe_path = None
            
            if install_path and exe:
                installed, actual_exe_path, install_version = self._check_install_path(install_path, exe)
                if installed:
                    print(f"  [OK] Installed at: {actual_exe_path}")
                    print(f"  [OK] Version: {install_version}")
                else:
                    print(f"  [WARN] Not found at install path: {install_path}")
            else:
                print("  [WARN] No install path or executable configured")
            
            # Check if running
            running = False
            running_exe_path = None
            
            if exe:
                running, running_exe_path = self._check_running_process(exe)
                if running:
                    print("  [OK] Currently running")
                    if running_exe_path:
                        print(f"  [OK] Running from: {running_exe_path}")
                else:
                    print("  [WARN] Not currently running")
            else:
                print("  [WARN] No executable configured for running check")
            
            results.append({
                "name": name,
                "platform": plat,
                "exe": exe,
                "install_path": install_path,
                "installed": installed,
                "install_version": install_version,
                "actual_exe_path": actual_exe_path,
                "running": running,
                "running_exe_path": running_exe_path
            })
        
        print(f"[OK] Software checks completed: {len(results)} applications checked")
        return {"software_checks": results}
