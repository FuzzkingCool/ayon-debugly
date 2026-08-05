import glob
import os
import re
import sys

import ayon_api

from ayon_debugly.collectors.collector_base import CollectorBase, redact_log_content
from ayon_debugly.lib import norm_path
from ayon_debugly.logger import log

MAX_SESSION_LOGS = 10


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
            log.debug(f"Loading log settings for platform: {plat}")

            # Load log directories
            if hasattr(settings, "logs") and hasattr(settings.logs, "log_dirs"):
                for entry in settings.logs.log_dirs:
                    log_dir = getattr(entry, plat, None)
                    if log_dir:
                        expanded_path = norm_path(log_dir)
                        self.log_dirs.append(expanded_path)
                        if os.path.exists(expanded_path):
                            log.debug(f"[OK] Log directory exists: {expanded_path}")
                        else:
                            log.debug(f"[WARN] Log directory does not exist: {expanded_path}")
            elif isinstance(settings, dict) and "logs" in settings and "log_dirs" in settings["logs"]:
                for entry in settings["logs"]["log_dirs"]:
                    log_dir = entry.get(plat, None)
                    if log_dir:
                        expanded_path = norm_path(log_dir)
                        self.log_dirs.append(expanded_path)
                        if os.path.exists(expanded_path):
                            log.debug(f"[OK] Log directory exists: {expanded_path}")
                        else:
                            log.debug(f"[WARN] Log directory does not exist: {expanded_path}")

            # Load specific log files
            if hasattr(settings, "logs") and hasattr(settings.logs, "log_files"):
                for entry in settings.logs.log_files:
                    log_file = getattr(entry, plat, None)
                    if log_file:
                        expanded_path = norm_path(log_file)
                        self.log_files.append(expanded_path)
                        if os.path.exists(expanded_path):
                            log.debug(f"[OK] Log file exists: {expanded_path}")
                        else:
                            log.debug(f"[WARN] Log file does not exist: {expanded_path}")
            elif isinstance(settings, dict) and "logs" in settings and "log_files" in settings["logs"]:
                for entry in settings["logs"]["log_files"]:
                    log_file = entry.get(plat, None)
                    if log_file:
                        expanded_path = norm_path(log_file)
                        self.log_files.append(expanded_path)
                        if os.path.exists(expanded_path):
                            log.debug(f"[OK] Log file exists: {expanded_path}")
                        else:
                            log.debug(f"[WARN] Log file does not exist: {expanded_path}")

            # Load log patterns
            if hasattr(settings, "logs") and hasattr(settings.logs, "log_patterns"):
                for entry in settings.logs.log_patterns:
                    pattern = getattr(entry, plat, None)
                    if pattern:
                        self.log_patterns.append(pattern)
                        log.debug(f"[OK] Log pattern added: {pattern}")
            elif isinstance(settings, dict) and "logs" in settings and "log_patterns" in settings["logs"]:
                for entry in settings["logs"]["log_patterns"]:
                    pattern = entry.get(plat, None)
                    if pattern:
                        self.log_patterns.append(pattern)
                        log.debug(f"[OK] Log pattern added: {pattern}")

            self._append_sandbox_log_dir()

        except Exception as e:
            log.debug(f"Warning: Could not load log settings from AYON settings: {e}")

    def _append_sandbox_log_dir(self):
        """Append $AYON_LOCAL_SANDBOX/logs when set (matches host addon log roots)."""
        sandbox = os.environ.get("AYON_LOCAL_SANDBOX")
        if not sandbox:
            return
        sandbox_logs = norm_path(os.path.join(sandbox, "logs"))
        normalized_dirs = {norm_path(d) for d in self.log_dirs}
        if sandbox_logs not in normalized_dirs:
            self.log_dirs.append(sandbox_logs)
            if os.path.exists(sandbox_logs):
                log.debug(f"[OK] Sandbox log directory exists: {sandbox_logs}")
            else:
                log.debug(f"[WARN] Sandbox log directory does not exist: {sandbox_logs}")

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
                log.debug(f"⚠ Skipping non-existent directory: {log_dir}")
                continue
            try:
                top_level_count = 0
                for f in os.listdir(log_dir):
                    path = os.path.join(log_dir, f)
                    if os.path.isfile(path) and f.endswith(".log"):
                        files.append(self._read_log_file(path))
                        top_level_count += 1

                sessions_dir = os.path.join(log_dir, "sessions")
                session_count = 0
                if os.path.isdir(sessions_dir):
                    session_paths = []
                    for f in os.listdir(sessions_dir):
                        if not f.endswith(".log"):
                            continue
                        path = os.path.join(sessions_dir, f)
                        if os.path.isfile(path):
                            session_paths.append(path)
                    session_paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                    for path in session_paths[:MAX_SESSION_LOGS]:
                        files.append(self._read_log_file(path))
                        session_count += 1

                log.debug(
                    f"[OK] Collected {top_level_count} top-level and "
                    f"{session_count} session files from {log_dir}"
                )
            except Exception as e:
                log.debug(f"[WARN] Error reading directory {log_dir}: {e}")
        return files

    def _collect_specific_files(self):
        """Collect specific log files by path."""
        files = []
        for log_file in self.log_files:
            if not log_file:
                continue
            if os.path.exists(log_file) and os.path.isfile(log_file):
                files.append(self._read_log_file(log_file))
                log.debug(f"[OK] Collected specific file: {log_file}")
            else:
                log.debug(f"[WARN] Specific file not found: {log_file}")
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
                    log.debug(f"[OK] Pattern '{pattern}' matched {len(pattern_files)} files")
                else:
                    log.debug(f"[WARN] Pattern '{pattern}' matched no files")

            except Exception as e:
                log.debug(f"[WARN] Could not process log pattern '{pattern}': {e}")
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
        log.debug("Starting log collection...")
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
        log.debug(f"[OK] Total log files collected: {len(result)}")
        return {"log_files": result}
