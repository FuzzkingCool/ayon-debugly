# Log Collection Features

The Debugly addon supports three different ways to collect log files:

## 1. Log Directories

Collect log files from specified directories:

```yaml
log_dirs:
  - windows: "C:\\Users\\Public\\Documents\\AYON\\logs"
    macos: "~/Library/Logs/AYON"
    linux: "/var/log/ayon"
  - windows: "C:\\ProgramData\\AppLogs"
    macos: "/Library/Logs"
    linux: "/var/log"
```

For each configured directory, Debugly collects:

- All top-level `*.log` files (shared/aggregate logs)
- The latest 10 `*.log` files from `{dir}/sessions/` (per-process session logs)

Session metadata (`.meta.json`) and merge lock files are skipped.

When `AYON_LOCAL_SANDBOX` is set, `$AYON_LOCAL_SANDBOX/logs` is searched automatically in addition to configured directories.

### Harmony dual-log layout (example)

Host addons such as Harmony may write both:

- **Aggregate:** `{log_dir}/ayon_harmony_debug.log` (+ rolled `ayon_harmony_debugNNN.log`)
- **Session:** `{log_dir}/sessions/ayon_harmony_debug_{timestamp}_{pid}.log`

With the default `~/.ayon/logs` directory entry, Debugly collects both layers without extra configuration.

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

1. **Directories**: Top-level `*.log` files plus the latest 10 session logs from `sessions/` under each configured directory
2. **Specific Files**: Only the exact files specified are collected (if they exist)
3. **Patterns**: Files matching the regex patterns are collected using glob patterns for discovery and regex for final matching

Paths support `~` and environment variables (for example `$AYON_LOCAL_SANDBOX/logs`).

## Duplicate Handling

If the same log file is found through multiple methods (e.g., both in a directory and as a specific file), it will only be included once in the final collection.

## Issue Archives

Redacted logs in issue ZIPs preserve the `sessions/` segment when applicable:

- `logs/ayon_harmony_debug_redacted.log` (aggregate)
- `logs/sessions/ayon_harmony_debug_20260805T120000_1234_redacted.log` (session)

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
1. Collect top-level and recent session logs from the AYON logs directory
2. Collect the specific `ayon.log` file if it exists
3. Collect any log files matching the pattern `.*\.log$` in logs directories
