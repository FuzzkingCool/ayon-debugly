import glob
import os
import re
import sys

import ayon_api

from ayon_debugly.collectors.collector_base import CollectorBase, redact_log_content


class CollectorLogs(CollectorBase):
    def __init__(self, tail_lines=20):
        """Collect logs from directories, specific files, and regex patterns specified in AYON server settings."""
        self.tail_lines = tail_lines
        self.log_dirs = []
        self.log_files = []
        self.log_patterns = []
        self._load_log_settings_from_ayon()

    def _load_log_settings_from_ayon(self):
        """Load all log settings from AYON server settings."""
        try:
            from ayon_debugly.version import __version__
            settings = ayon_api.get_addon_settings("debugly", __version__)
            
            plat = self._get_platform()
            print(f"Loading log settings for platform: {plat}")
            
            # Load log directories
            if hasattr(settings, "logs") and hasattr(settings.logs, "log_dirs"):
                for entry in settings.logs.log_dirs:
                    log_dir = getattr(entry, plat, None)
                    if log_dir:
                        expanded_path = os.path.expanduser(log_dir)
                        self.log_dirs.append(expanded_path)
                        if os.path.exists(expanded_path):
                            print(f"[OK] Log directory exists: {expanded_path}")
                        else:
                            print(f"[WARN] Log directory does not exist: {expanded_path}")
            elif isinstance(settings, dict) and "logs" in settings and "log_dirs" in settings["logs"]:
                for entry in settings["logs"]["log_dirs"]:
                    log_dir = entry.get(plat, None)
                    if log_dir:
                        expanded_path = os.path.expanduser(log_dir)
                        self.log_dirs.append(expanded_path)
                        if os.path.exists(expanded_path):
                            print(f"[OK] Log directory exists: {expanded_path}")
                        else:
                            print(f"[WARN] Log directory does not exist: {expanded_path}")
            
            # Load specific log files
            if hasattr(settings, "logs") and hasattr(settings.logs, "log_files"):
                for entry in settings.logs.log_files:
                    log_file = getattr(entry, plat, None)
                    if log_file:
                        expanded_path = os.path.expanduser(log_file)
                        self.log_files.append(expanded_path)
                        if os.path.exists(expanded_path):
                            print(f"[OK] Log file exists: {expanded_path}")
                        else:
                            print(f"[WARN] Log file does not exist: {expanded_path}")
            elif isinstance(settings, dict) and "logs" in settings and "log_files" in settings["logs"]:
                for entry in settings["logs"]["log_files"]:
                    log_file = entry.get(plat, None)
                    if log_file:
                        expanded_path = os.path.expanduser(log_file)
                        self.log_files.append(expanded_path)
                        if os.path.exists(expanded_path):
                            print(f"[OK] Log file exists: {expanded_path}")
                        else:
                            print(f"[WARN] Log file does not exist: {expanded_path}")
            
            # Load log patterns
            if hasattr(settings, "logs") and hasattr(settings.logs, "log_patterns"):
                for entry in settings.logs.log_patterns:
                    pattern = getattr(entry, plat, None)
                    if pattern:
                        self.log_patterns.append(pattern)
                        print(f"[OK] Log pattern added: {pattern}")
            elif isinstance(settings, dict) and "logs" in settings and "log_patterns" in settings["logs"]:
                for entry in settings["logs"]["log_patterns"]:
                    pattern = entry.get(plat, None)
                    if pattern:
                        self.log_patterns.append(pattern)
                        print(f"[OK] Log pattern added: {pattern}")
                        
        except Exception as e:
            print(f"Warning: Could not load log settings from AYON settings: {e}")

    def _get_platform(self):
        if sys.platform.startswith("win"):
            return "windows"
        if sys.platform == "darwin":
            return "macos"
        return "linux"

    def _collect_files_from_directories(self):
        """Collect log files from configured directories."""
        files = []
        for log_dir in self.log_dirs:
            if not log_dir:
                continue
            if not os.path.exists(log_dir):
                print(f"⚠ Skipping non-existent directory: {log_dir}")
                continue
            try:
                for f in os.listdir(log_dir):
                    path = os.path.join(log_dir, f)
                    if os.path.isfile(path):
                        files.append(self._read_log_file(path))
                print(f"[OK] Collected {len([f for f in os.listdir(log_dir) if os.path.isfile(os.path.join(log_dir, f))])} files from {log_dir}")
            except Exception as e:
                print(f"[WARN] Error reading directory {log_dir}: {e}")
        return files

    def _collect_specific_files(self):
        """Collect specific log files by path."""
        files = []
        for log_file in self.log_files:
            if not log_file:
                continue
            if os.path.exists(log_file) and os.path.isfile(log_file):
                files.append(self._read_log_file(log_file))
                print(f"[OK] Collected specific file: {log_file}")
            else:
                print(f"[WARN] Specific file not found: {log_file}")
        return files

    def _collect_files_by_patterns(self):
        """Collect log files matching regex patterns."""
        files = []
        for pattern in self.log_patterns:
            try:
                # Convert regex pattern to glob pattern for file discovery
                # This is a simplified approach - for more complex patterns,
                # we might need to scan directories recursively
                if sys.platform.startswith("win"):
                    # Windows: convert regex to glob pattern
                    glob_pattern = pattern.replace(".*", "*").replace("\\", "/")
                else:
                    # Unix: convert regex to glob pattern
                    glob_pattern = pattern.replace(".*", "*")
                
                # Find files matching the pattern
                matched_files = glob.glob(glob_pattern, recursive=True)
                pattern_files = []
                for file_path in matched_files:
                    if os.path.isfile(file_path):
                        # Double-check with regex
                        if re.match(pattern, file_path):
                            files.append(self._read_log_file(file_path))
                            pattern_files.append(file_path)
                
                if pattern_files:
                    print(f"[OK] Pattern '{pattern}' matched {len(pattern_files)} files")
                else:
                    print(f"[WARN] Pattern '{pattern}' matched no files")
                            
            except Exception as e:
                print(f"[WARN] Could not process log pattern '{pattern}': {e}")
        return files

    def _read_log_file(self, path):
        """Read a log file and return its metadata and tail content with redaction."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                lines = fp.readlines()
                tail = lines[-self.tail_lines:] if len(lines) > self.tail_lines else lines
                tail_content = "".join(tail)
            
            # Apply log redaction to the tail content
            redacted_tail = redact_log_content(tail_content)
            
            return {
                "path": path,
                "size": os.path.getsize(path),
                "mtime": os.path.getmtime(path),
                "tail": redacted_tail
            }
        except Exception:
            return {
                "path": path,
                "size": os.path.getsize(path),
                "mtime": os.path.getmtime(path),
                "tail": "<unreadable>"
            }

    def collect(self):
        """Collect all log files from directories, specific files, and patterns."""
        print("Starting log collection...")
        all_files = []
        
        # Collect from directories
        dir_files = self._collect_files_from_directories()
        all_files.extend(dir_files)
        
        # Collect specific files
        specific_files = self._collect_specific_files()
        all_files.extend(specific_files)
        
        # Collect files matching patterns
        pattern_files = self._collect_files_by_patterns()
        all_files.extend(pattern_files)
        
        # Remove duplicates based on path
        unique_files = {}
        for file_info in all_files:
            unique_files[file_info["path"]] = file_info
        
        result = list(unique_files.values())
        print(f"[OK] Total log files collected: {len(result)}")
        return {"log_files": result}
