
from typing import List
from ayon_server.settings import BaseSettingsModel, SettingsField # type: ignore


class PlatformPaths(BaseSettingsModel):
    windows: str = SettingsField(
        default="P:\\Pipeline\\ayon_issues",
        title="Windows",
        description="Shared Directory for issue on Windows.",
    )
    macos: str = SettingsField(
        default="/Volumes/Pipeline/ayon_issues",
        title="macOS",
        description="Shared Directory for issue on macOS.",
    )
    linux: str = SettingsField(
        default="/mnt/Pipeline/ayon_issues",
        title="Linux",
        description="Shared Directory for reports on Linux.",
    )


class LogDirEntry(BaseSettingsModel):
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


class SoftwarePlatformCheck(BaseSettingsModel):
    exe: str = SettingsField(
        default="",
        title="Executable Name",
        description="Executable name for this platform (e.g. Photoshop.exe, Unity, harmony)",
    )
    path: str = SettingsField(
        default="",
        title="Install Path",
        description="Installation folder for this platform.",
    )


class SoftwareCheckEntry(BaseSettingsModel):
    name: str = SettingsField(
        "",
        title="Software Name",
        description="Display name of the software (e.g. Photoshop)",
    )
    windows: SoftwarePlatformCheck = SettingsField(
        default_factory=SoftwarePlatformCheck,
        title="Windows",
        description="Windows-specific executable and install path.",
    )
    macos: SoftwarePlatformCheck = SettingsField(
        default_factory=SoftwarePlatformCheck,
        title="macOS",
        description="macOS-specific executable and install path.",
    )
    linux: SoftwarePlatformCheck = SettingsField(
        default_factory=SoftwarePlatformCheck,
        title="Linux",
        description="Linux-specific executable and install path.",
    )


class DebuglySettings(BaseSettingsModel):
    """Settings for the Debugly addon."""

    enabled: bool = SettingsField(
        True,
        title="Enabled",
        description="Enable or disable the Debugly addon.",
    )
    shared_dir: PlatformPaths = SettingsField(
        default_factory=PlatformPaths,
        title="Shared Directory",
        description="Directory where user reports will be stored, per platform.",
    )
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
    software_checks: List[SoftwareCheckEntry] = SettingsField(
        default_factory=lambda: [
            SoftwareCheckEntry(
                name="Photoshop",
                windows=SoftwarePlatformCheck(
                    exe="Photoshop.exe",
                    path="C:\\Program Files\\Adobe\\Adobe Photoshop 2024",
                ),
                macos=SoftwarePlatformCheck(
                    exe="Adobe Photoshop",
                    path="/Applications/Adobe Photoshop 2024",
                ),
                linux=SoftwarePlatformCheck(exe="", path=""),
            ),
            SoftwareCheckEntry(
                name="Unity",
                windows=SoftwarePlatformCheck(
                    exe="Unity.exe", path="C:\\Program Files\\Unity\\Editor"
                ),
                macos=SoftwarePlatformCheck(
                    exe="Unity", path="/Applications/Unity/Hub/Editor"
                ),
                linux=SoftwarePlatformCheck(
                    exe="unity-editor", path="/opt/Unity/Editor"
                ),
            ),
            SoftwareCheckEntry(
                name="Harmony",
                windows=SoftwarePlatformCheck(
                    exe="Harmony.exe",
                    path="C:\\Program Files\\Toon Boom Animation\\Harmony",
                ),
                macos=SoftwarePlatformCheck(
                    exe="Harmony.app",
                    path="/Applications/Toon Boom Harmony 22",
                ),
                linux=SoftwarePlatformCheck(
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
    "shared_dir": {
        "windows": "P:\\Pipeline\\ayon_issues",
        "macos": "/Volumes/Pipeline/ayon_issues",
        "linux": "/mnt/Pipeline/ayon_issues",
    },
    "log_dirs": [
        {
            "windows": "~\\.ayon\\logs",
            "macos": "~\\.ayon\\logs",
            "linux": "~\\.ayon\\logs",
        },
    ],
    "software_checks": [
        {
            "name": "Photoshop",
            "windows": {
                "exe": "Photoshop.exe",
                "path": "C:\\Program Files\\Adobe\\Adobe Photoshop 2024",
            },
            "macos": {
                "exe": "Adobe Photoshop",
                "path": "/Applications/Adobe Photoshop 2024",
            },
            "linux": {"exe": "", "path": ""},
        },
        {
            "name": "Unity",
            "windows": {
                "exe": "Unity.exe",
                "path": "C:\\Program Files\\Unity\\Editor",
            },
            "macos": {
                "exe": "Unity",
                "path": "/Applications/Unity/Hub/Editor",
            },
            "linux": {"exe": "unity-editor", "path": "/opt/Unity/Editor"},
        },
        {
            "name": "Harmony",
            "windows": {
                "exe": "Harmony.exe",
                "path": "C:\\Program Files\\Toon Boom Animation\\Harmony",
            },
            "macos": {
                "exe": "Harmony.app",
                "path": "/Applications/Toon Boom Harmony 22",
            },
            "linux": {"exe": "harmony", "path": "/opt/Harmony"},
        },
    ],
}
