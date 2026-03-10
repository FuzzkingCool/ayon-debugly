# Log Collection Features

The Debugly addon now supports three different ways to collect log files:

## 1. Log Directories

Collect all log files from specified directories:

```yaml
log_dirs:
  - windows: "C:\\Users\\Public\\Documents\\AYON\\logs"
    macos: "~/Library/Logs/AYON"
    linux: "/var/log/ayon"
  - windows: "C:\\ProgramData\\AppLogs"
    macos: "/Library/Logs"
    linux: "/var/log"
```

## 2. Specific Log Files

Collect specific log files by their full path:

```yaml
log_files:
  - windows: "C:\\Users\\Public\\Documents\\AYON\\ayon.log"
    macos: "~/Library/Logs/AYON/ayon.log"
    linux: "/var/log/ayon/ayon.log"
  - windows: "C:\\ProgramData\\MyApp\\app.log"
    macos: "/Applications/MyApp/logs/app.log"
    linux: "/var/log/myapp/app.log"
```

## 3. Log File Patterns

Collect log files matching regex patterns:

```yaml
log_patterns:
  - windows: ".*\\\\logs\\\\.*\\.log$"
    macos: ".*/logs/.*\\.log$"
    linux: "/var/log/.*\\.log$"
  - windows: ".*\\\\ayon.*\\.log$"
    macos: ".*/ayon.*\\.log$"
    linux: "/var/log/ayon.*\\.log$"
```

## How It Works

1. **Directories**: All files in the specified directories are collected
2. **Specific Files**: Only the exact files specified are collected (if they exist)
3. **Patterns**: Files matching the regex patterns are collected using glob patterns for discovery and regex for final matching

## Duplicate Handling

If the same log file is found through multiple methods (e.g., both in a directory and as a specific file), it will only be included once in the final collection.

## Platform-Specific Configuration

Each setting supports platform-specific paths:
- `windows`: Windows-specific paths
- `macos`: macOS-specific paths  
- `linux`: Linux-specific paths

## Example Configuration

```yaml
log_dirs:
  - windows: "C:\\Users\\Public\\Documents\\AYON\\logs"
    macos: "~/Library/Logs/AYON"
    linux: "/var/log/ayon"

log_files:
  - windows: "C:\\Users\\Public\\Documents\\AYON\\ayon.log"
    macos: "~/Library/Logs/AYON/ayon.log"
    linux: "/var/log/ayon/ayon.log"

log_patterns:
  - windows: ".*\\\\logs\\\\.*\\.log$"
    macos: ".*/logs/.*\\.log$"
    linux: "/var/log/.*\\.log$"
```

This configuration will:
1. Collect all files from the AYON logs directory
2. Collect the specific `ayon.log` file if it exists
3. Collect any log files matching the pattern `.*\.log$` in logs directories 