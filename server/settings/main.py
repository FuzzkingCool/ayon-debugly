
from typing import List
from ayon_server.settings import BaseSettingsModel, SettingsField # type: ignore


class SharedDirectoryConfig(BaseSettingsModel):
    _layout = "expanded"
    enabled: bool = SettingsField(
        default=True,
        title="Enabled",
        description="Enable or disable shared directory endpoint.",
    )
    windows: str = SettingsField(
        default="P:\\Pipeline\\ayon_issues",
        title="Windows",
        description="Shared Directory for issue on Windows.",
    )
    macos: str = SettingsField(
        default="/Volumes/Projects/Pipeline/ayon_issues",
        title="macOS",
        description="Shared Directory for issue on macOS.",
    )
    linux: str = SettingsField(
        default="/mnt/Pipeline/ayon_issues",
        title="Linux",
        description="Shared Directory for reports on Linux.",
    )


class LogDirEntry(BaseSettingsModel):
    _layout = "expanded"
    windows: str = SettingsField(
        default_factory=lambda: "~/.ayon/logs",
        title="Windows",
        description="Log Directory for Windows.",
    )
    macos: str = SettingsField(
        default_factory=lambda: "~/.ayon/logs",
        title="macOS",
        description="Log Directory for macOS.",
    )
    linux: str = SettingsField(
        default_factory=lambda: "~/.ayon/logs",
        title="Linux",
        description="Log Directory for Linux.",
    )


class LogFileEntry(BaseSettingsModel):
    _layout = "expanded"
    windows: str = SettingsField(
        default="",
        title="Windows",
        description="Specific log file path for Windows.",
    )
    macos: str = SettingsField(
        default="",
        title="macOS",
        description="Specific log file path for macOS.",
    )
    linux: str = SettingsField(
        default="",
        title="Linux",
        description="Specific log file path for Linux.",
    )


class LogPatternEntry(BaseSettingsModel):
    _layout = "expanded"
    windows: str = SettingsField(
        default="",
        title="Windows",
        description="Regex pattern for log files on Windows.",
    )
    macos: str = SettingsField(
        default="",
        title="macOS",
        description="Regex pattern for log files on macOS.",
    )
    linux: str = SettingsField(
        default="",
        title="Linux",
        description="Regex pattern for log files on Linux.",
    )


class LogRedactionEntry(BaseSettingsModel):
    _layout = "expanded"
    pattern: str = SettingsField(
        default="",
        title="Redaction Pattern",
        description="Regex pattern to redact from log content (e.g., 'password=\\w+', 'token=[a-zA-Z0-9]+')",
    )
    replacement: str = SettingsField(
        default="***REDACTED***",
        title="Replacement Text",
        description="Text to replace matched patterns with.",
    )


class SoftwarePlatformCheckWindows(BaseSettingsModel):
    exe: str = SettingsField(
        default="",
        title="Windows Executable Name",
        description="Executable name for Windows (e.g. Photoshop.exe, Unity.exe, Harmony.exe)",
    )
    path: str = SettingsField(
        default="",
        title="Windows Install Path",
        description="Installation folder for Windows.",
    )


class SoftwarePlatformCheckMacOS(BaseSettingsModel):
    exe: str = SettingsField(
        default="",
        title="macOS Executable Name",
        description="Executable name for macOS (e.g. Adobe Photoshop, Unity, Harmony.app)",
    )
    path: str = SettingsField(
        default="",
        title="macOS Install Path",
        description="Installation folder for macOS.",
    )


class SoftwarePlatformCheckLinux(BaseSettingsModel):
    exe: str = SettingsField(
        default="",
        title="Linux Executable Name",
        description="Executable name for Linux (e.g. photoshop, unity-editor, harmony)",
    )
    path: str = SettingsField(
        default="",
        title="Linux Install Path",
        description="Installation folder for Linux.",
    )


class SoftwareCheckEntry(BaseSettingsModel):
    name: str = SettingsField(
        "",
        title="Software Name",
        description="Display name of the software (e.g. Photoshop)",
    )
    windows: SoftwarePlatformCheckWindows = SettingsField(
        default_factory=SoftwarePlatformCheckWindows,
        title="Windows",
        description="Windows-specific executable and install path.",
    )
    macos: SoftwarePlatformCheckMacOS = SettingsField(
        default_factory=SoftwarePlatformCheckMacOS,
        title="macOS",
        description="macOS-specific executable and install path.",
    )
    linux: SoftwarePlatformCheckLinux = SettingsField(
        default_factory=SoftwarePlatformCheckLinux,
        title="Linux",
        description="Linux-specific executable and install path.",
    )


class SharedDirSettings(BaseSettingsModel):
    """Shared directory endpoint configuration."""
    
    shared_dir: SharedDirectoryConfig = SettingsField(
        default_factory=SharedDirectoryConfig,
        title="Shared Directory",
        description="Directory where user reports will be stored, per platform.",
    )


class EndpointsSettings(BaseSettingsModel):
    """Endpoints configuration."""
    
    shared_dir: SharedDirSettings = SettingsField(
        default_factory=SharedDirSettings,
        title="Shared Dir",
        description="Shared directory endpoint for storing issue reports.",
    )


class LogsSettings(BaseSettingsModel):
    """Logs collection configuration."""
    
    log_dirs: List[LogDirEntry] = SettingsField(
        default_factory=lambda: [
            LogDirEntry(
                windows="C:\\Users\\Public\\Documents\\AYON\\logs",
                macos="~/Library/Logs/AYON",
                linux="/var/log/ayon",
            ),
            LogDirEntry(
                windows="C:\\ProgramData\\AppLogs",
                macos="/Library/Logs",
                linux="/var/log",
            ),
        ],
        title="Log Directories",
        description="List of log directories to search, per platform.",
    )
    log_files: List[LogFileEntry] = SettingsField(
        default_factory=lambda: [
            LogFileEntry(
                windows="C:\\Users\\Public\\Documents\\AYON\\ayon.log",
                macos="~/Library/Logs/AYON/ayon.log",
                linux="/var/log/ayon/ayon.log",
            ),
        ],
        title="Log Files",
        description="List of specific log files to collect, per platform.",
    )
    log_patterns: List[LogPatternEntry] = SettingsField(
        default_factory=lambda: [
            LogPatternEntry(
                windows=".*\\\\logs\\\\.*\\.log$",
                macos=".*/logs/.*\\.log$",
                linux="/var/log/.*\\.log$",
            ),
        ],
        title="Log Patterns",
        description="List of regex patterns to match log files, per platform.",
    )


class EnvironmentRedactionsSettings(BaseSettingsModel):
    """Environment redactions configuration."""
    
    enabled: bool = SettingsField(
        default=True,
        title="Enabled",
        description="Enable or disable environment variable redaction.",
    )
    
    env_redact_keys: List[str] = SettingsField(
        default_factory=lambda: [
            "PASSWORD", "TOKEN", "SECRET", "KEY", "AUTH", "SESSION", 
            "COOKIE", "KITSU_PWD", "API_KEY", "PRIVATE_KEY", "ACCESS_TOKEN"
        ],
        title="Environment Key Redactions",
        description="List of environment variable key names to redact from collected data.",
    )


class LogRedactionsSettings(BaseSettingsModel):
    """Log redactions configuration."""
    
    enabled: bool = SettingsField(
        default=True,
        title="Enabled",
        description="Enable or disable log content redaction.",
    )
    
    log_redactions: List[LogRedactionEntry] = SettingsField(
        default_factory=lambda: [
            LogRedactionEntry(
                pattern="password=([^\\s&;,\\n]+)",
                replacement="password=***REDACTED***"
            ),
            LogRedactionEntry(
                pattern="token=([a-zA-Z0-9_-]+)",
                replacement="token=***REDACTED***"
            ),
            LogRedactionEntry(
                pattern="secret=([^\\s&;,\\n]+)",
                replacement="secret=***REDACTED***"
            ),
            LogRedactionEntry(
                pattern="api_key=([^\\s&;,\\n]+)",
                replacement="api_key=***REDACTED***"
            ),
            LogRedactionEntry(
                pattern="auth_token=([^\\s&;,\\n]+)",
                replacement="auth_token=***REDACTED***"
            ),
        ],
        title="Log Redactions",
        description="List of regex patterns to redact from log content before submission.",
    )


class RedactionsSettings(BaseSettingsModel):
    """Redactions configuration."""
    
    environment: EnvironmentRedactionsSettings = SettingsField(
        default_factory=EnvironmentRedactionsSettings,
        title="Environment Redactions",
        description="Environment variable redaction settings.",
    )
    
    log: LogRedactionsSettings = SettingsField(
        default_factory=LogRedactionsSettings,
        title="Log Redactions",
        description="Log content redaction settings.",
    )





class IssueSettings(BaseSettingsModel):
    """Issue configuration."""
    
    issue_default_text: str = SettingsField(
        default="""# Problem
---
   
**Context & description:** Explain what you were trying to accomplish when the bug occurred

   
# Expected behavior
---
   
**Expected vs. actual behavior:** Clearly distinguish between what you expected to happen and what actually happened.
   
   
   
# How to reproduce
---
**Step-by-step reproduction:** List the exact steps someone else would need to follow to encounter the same issue

   
   
""",
        title="Issue Default Text",
        description="Default text template for new issue reports.",
        widget="textarea",
    )


class DebuglySettings(BaseSettingsModel):
    """Settings for the Debugly addon."""

    enabled: bool = SettingsField(
        True,
        title="Enabled",
        description="Enable or disable the Debugly addon.",
    )
    
    # Issue Settings
    issue_settings: IssueSettings = SettingsField(
        default_factory=IssueSettings,
        title="Issue Settings",
        description="Issue report configuration and templates.",
    )
    
    # Endpoints Settings
    endpoints: EndpointsSettings = SettingsField(
        default_factory=EndpointsSettings,
        title="Endpoints",
        description="Endpoint configurations for report submission.",
    )
    
    # Logs Settings
    logs: LogsSettings = SettingsField(
        default_factory=LogsSettings,
        title="Logs",
        description="Log collection and processing settings.",
    )
    
    # Redactions Settings
    redactions: RedactionsSettings = SettingsField(
        default_factory=RedactionsSettings,
        title="Redactions",
        description="Data redaction settings for privacy and security.",
    )
    software_checks: List[SoftwareCheckEntry] = SettingsField(
        default_factory=lambda: [
            SoftwareCheckEntry(
                name="Photoshop 2025",
                windows=SoftwarePlatformCheckWindows(
                    exe="Photoshop.exe",
                    path="C:\\Program Files\\Adobe\\Adobe Photoshop 2025",
                ),
                macos=SoftwarePlatformCheckMacOS(
                    exe="Adobe Photoshop",
                    path="/Applications/Adobe Photoshop 2025",
                ),
                linux=SoftwarePlatformCheckLinux(exe="", path=""),
            ),
            SoftwareCheckEntry(
                name="Unity 2021.3.5f1",
                windows=SoftwarePlatformCheckWindows(
                    exe="Unity.exe", path="C:\\Program Files\\Unity\\Editor\\2021.3.5f1"
                ),
                macos=SoftwarePlatformCheckMacOS(
                    exe="Unity", path="/Applications/Unity/Hub/Editor/"
                ),
                linux=SoftwarePlatformCheckLinux(
                    exe="unity-editor", path="/opt/Unity/Editor"
                ),
            ),
            SoftwareCheckEntry(
                name="Harmony 24",
                windows=SoftwarePlatformCheckWindows(
                    exe="Harmony.exe",
                    path="C:\\Program Files (x86)\\Toon Boom Animation\\Toon Boom Harmony 24 Premium",
                ),
                macos=SoftwarePlatformCheckMacOS(
                    exe="Harmony.app",
                    path="/Applications/Toon Boom Harmony 24",
                ),
                linux=SoftwarePlatformCheckLinux(
                    exe="harmony", path="/opt/Harmony"
                ),
            ),
        ],
        title="Software Checks",
        description="List of software/processes to check for, with platform-specific executable and install path.",
    )


def get_default_settings_model():
    return DebuglySettings


DEFAULT_DEBUGLY_SETTINGS = {
    "enabled": True,
    
    # Issue Settings
    "issue_settings": {
        "issue_default_text": """# Problem
---
   
**Context & description:** Explain what you were trying to accomplish when the bug occurred

   
# Expected behavior
---
   
**Expected vs. actual behavior:** Clearly distinguish between what you expected to happen and what actually happened.
   
   
   
# How to reproduce
---
**Step-by-step reproduction:** List the exact steps someone else would need to follow to encounter the same issue

   
   
""",
    },
    
    # Endpoints Settings
    "endpoints": {
        "shared_dir": {
            "shared_dir": {
                "enabled": True,
                "windows": "P:\\Pipeline\\ayon_issues",
                "macos": "/Volumes/Projects/Pipeline/ayon_issues",
                "linux": "/mnt/Pipeline/ayon_issues",
            },
        },
    },
    
    # Logs Settings
    "logs": {
        "log_dirs": [
            {
                "windows": "~\\.ayon\\logs",
                "macos": "~\\.ayon\\logs",
                "linux": "~\\.ayon\\logs",
            },
        ],
        "log_files": [
            {
                "windows": "C:\\Users\\Public\\Documents\\AYON\\ayon.log",
                "macos": "~/Library/Logs/AYON/ayon.log",
                "linux": "/var/log/ayon/ayon.log",
            },
        ],
        "log_patterns": [
            {
                "windows": ".*\\\\logs\\\\.*\\.log$",
                "macos": ".*/logs/.*\\.log$",
                "linux": "/var/log/.*\\.log$",
            },
        ],
    },
    
    # Redactions Settings
    "redactions": {
        "environment": {
            "enabled": True,
            "env_redact_keys": [
                "PASSWORD", "TOKEN", "SECRET", "KEY", "AUTH", "SESSION", 
                "COOKIE", "KITSU_PWD", "API_KEY", "PRIVATE_KEY", "ACCESS_TOKEN"
            ],
        },
        "log": {
            "enabled": True,
            "log_redactions": [
                {
                    "pattern": "password=([^\\s&;,\\n]+)",
                    "replacement": "password=***REDACTED***"
                },
                {
                    "pattern": "token=([a-zA-Z0-9_-]+)",
                    "replacement": "token=***REDACTED***"
                },
                {
                    "pattern": "secret=([^\\s&;,\\n]+)",
                    "replacement": "secret=***REDACTED***"
                },
                {
                    "pattern": "api_key=([^\\s&;,\\n]+)",
                    "replacement": "api_key=***REDACTED***"
                },
                {
                    "pattern": "auth_token=([^\\s&;,\\n]+)",
                    "replacement": "auth_token=***REDACTED***"
                },
            ],
        },
    },
    "software_checks": [
        {
            "name": "Photoshop 2025",
            "windows": {
                "exe": "Photoshop.exe",
                "path": "C:\\Program Files\\Adobe\\Adobe Photoshop 2025",
            },
            "macos": {
                "exe": "Adobe Photoshop",
                "path": "/Applications/Adobe Photoshop 2025",
            },
            "linux": {"exe": "", "path": ""},
        },
        {
            "name": "Unity 2021.3.5f1",
            "windows": {
                "exe": "Unity.exe",
                "path": "C:\\Program Files\\Unity\\Editor\\2021.3.5f1",
            },
            "macos": {
                "exe": "Unity",
                "path": "/Applications/Unity/Hub/Editor/",
            },
            "linux": {"exe": "unity-editor", "path": "/opt/Unity/Editor"},
        },
        {
            "name": "Harmony 24",
            "windows": {
                "exe": "Harmony.exe",
                "path": "C:\\Program Files (x86)\\Toon Boom Animation\\Toon Boom Harmony 24 Premium",
            },
            "macos": {
                "exe": "Harmony.app",
                "path": "/Applications/Toon Boom Harmony 24",
            },
            "linux": {"exe": "harmony", "path": "/opt/Harmony"},
        },
    ],
}
