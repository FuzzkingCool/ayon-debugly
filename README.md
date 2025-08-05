# AYON Debugly Addon

A comprehensive issue reporting and debugging addon for AYON that helps users and administrators track, collect, and manage system issues efficiently.

## Overview

The Debugly addon provides a user-friendly interface for reporting issues with automatic collection of system information, logs, and screenshots. It streamlines the debugging process by gathering all relevant data and presenting it in a structured format for easy analysis.

## Features

### **User-Friendly Issue Reporting**
- **WYSIWYG Editor**: Rich text editor with markdown support and code formatting
- **Screenshot Tools**: Full screen and area selection screenshot capabilities
- **Drag & Drop**: Easy file attachment support
- **Real-time Preview**: Live preview of formatted content
- **UTF-8 Support**: Full international character support for titles, messages, and filenames

### **Automatic Data Collection**
- **System Information**: OS, platform, and version details
- **Environment Variables**: System environment with sensitive data redaction
- **Software Detection**: Installed software and version information
- **Log Files**: Automatic collection from configured directories and patterns
- **Progress Tracking**: Visual progress indicators during data collection
- **User Information**: Current user and system context

### **Security & Privacy**
- **Data Redaction**: Automatic redaction of sensitive information (passwords, tokens, API keys)
- **Configurable Patterns**: Customizable redaction rules via server settings
- **Environment Redaction**: Automatic redaction of sensitive environment variables before storage/submission
- **Secure Storage**: Integration with AYON's secrets management system

### **Multiple Endpoints**
- **Shared Folder**: Save reports to network locations with organized file structure
- **Notion Integration**: Create structured issue pages in Notion databases
- **Extensible**: Plugin architecture for custom endpoints
- **Endpoint-Specific Success Information**: Custom success dialogs with clickable URLs and file paths

### **Advanced Features**
- **Markdown Parsing**: Automatic conversion of markdown links to clickable elements
- **File Upload Support**: Images, documents, and log files with automatic format conversion
- **Database Schema Adaptation**: Automatically adapts to existing Notion database properties
- **Success Dialog**: Endpoint-specific success information with direct links to created issues

## Configuration

### Server Settings

The addon can be configured through the AYON server admin interface:

#### **Endpoints**
- **Shared Folder**: Configure a shared network location for issue reports
  - Platform-specific paths (Windows, macOS, Linux)
  - Organized file structure with timestamps
- **Notion Integration**: Create issues in Notion databases
  - Database ID configuration
  - API key management via AYON secrets
  - Automatic schema detection and adaptation
  - File upload and attachment support

#### **Log Collection**
- **Log Directories**: Specify directories to scan for log files
- **Log Patterns**: Configure regex patterns for log file discovery
- **Platform-Specific**: Different settings for Windows, macOS, and Linux
- **Redacted Logs**: Automatic redaction of sensitive data in log files

#### **Data Redaction**
- **Environment Variables**: List of sensitive environment variables to redact
- **Log Patterns**: Regex patterns for redacting sensitive data from logs
- **Custom Rules**: Add custom redaction patterns as needed
- **Note**: Data is stored in standard JSON/ZIP format with redaction applied

#### **Software Detection**
- **Software List**: Configure software to detect and report versions
- **Platform Paths**: Specify installation paths for different platforms
- **Version Detection**: Automatic version extraction from executables

### Client Settings

The client automatically uses server-side configuration and requires no additional setup.

## Usage

### For Users

1. **Launch Debugly**: Access through the AYON Launcher in the notification tray menu
2. **Describe the Issue**: Use the WYSIWYG editor to describe the problem
3. **Add Context**: Include screenshots, attachments, or additional files
4. **Submit Report**: The system automatically collects all relevant data
5. **Track Progress**: Monitor the collection progress via the status bar
6. **View Results**: See endpoint-specific success information with direct links

### For Administrators

**Note**: This addon is designed to collect system information for debugging purposes. Data is stored in standard JSON/ZIP format with automatic redaction of sensitive information. Ensure compliance with your organization's data collection and privacy policies.

## File Structure

### Generated Issue Reports

Each issue report is packaged as a ZIP file with the following structure:

```
issue_report_YYYY-MM-DD_HH-MM-SS.zip/
├── issue.json                    # Main issue data and metadata
├── collected_data.json           # Detailed system information
├── attachments/                  # User-provided files
│   ├── screenshot.png
│   └── additional_files/
├── logs/                         # Collected log files (redacted)
│   ├── application_redacted.txt
│   └── system_redacted.txt
└── screenshot/                   # Screenshots
    └── screenshot.png
```

### Issue JSON Structure

```json
{
  "title": "Issue Title",
  "user_message": "User description with markdown support",
  "collected_data": {
    "env": { "environment": {...} },
    "os": { "platform": "...", "version": "..." },
    "user": { "username": "...", "home": "..." },
    "system_spec": { "cpu": "...", "memory": "..." },
    "software_checks": { "installed": [...] }
  },
  "attachments": ["path/to/files"],
  "screenshot": "path/to/screenshot",
  "log_files": ["path/to/logs"],
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Endpoints

### Shared Folder Endpoint

Saves issue reports to a configured network location:
- **Organized Structure**: Timestamped zips with clear naming
- **Complete Data**: All collected information and attachments
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Success Information**: Shows file path with "Open File" and "Show in Folder" options

### Notion Integration

Creates structured issue pages in Notion databases:
- **Automatic Schema Detection**: Adapts to existing database properties
- **Rich Content**: Markdown support with clickable links
- **File Uploads**: Automatic attachment upload and linking
- **Property Mapping**: Title, Status, Priority, Assign, Tags support
- **Success Information**: Direct link to created Notion page

#### Notion Setup

See [NOTION_SETUP.md](client/ayon_debugly/endpoints/NOTION_SETUP.md) for detailed setup instructions.

## Development

### Architecture

- **Client**: PyQt-based GUI with collector system
- **Server**: AYON addon with settings management
- **Collectors**: Modular data collection system
- **Endpoints**: Pluggable submission endpoints
- **UTF-8 Support**: Full international character support throughout

### Adding Custom Collectors

1. Create a new collector class inheriting from `CollectorBase`
2. Implement the `collect()` method
3. Register the collector in the collector system
4. Create and configure collection settings in `/server/settings/main.py`

### Adding Custom Endpoints

1. Create a new endpoint class inheriting from `EndpointBase`
2. Implement the `submit()` method
3. Implement the `get_success_info()` method for custom success dialogs
4. Create and configure endpoint settings in `/server/settings/main.py`

### UTF-8 Support

The codebase includes comprehensive UTF-8 support:
- All Python files have UTF-8 encoding declarations
- File I/O operations use explicit UTF-8 encoding
- Subprocess calls handle UTF-8 output correctly
- International characters supported in titles, messages, and filenames

---

## Privacy and Data Handling

This addon collects system information, environment variables, log files, and user-provided attachments for the purpose of debugging and issue reporting. While sensitive values (such as passwords, tokens, and API keys) are automatically redacted based on configurable patterns, all collected data is stored in standard JSON and ZIP files without additional encryption or secure storage.

**Administrators and users are responsible for ensuring that the use of this addon complies with all applicable data protection, privacy, and security regulations in their jurisdiction and organization.**

By using this addon, you acknowledge and accept that:

- Collected data may include sensitive or personally identifiable information (PII) if not properly redacted.
- The addon does not provide encryption or advanced security for stored data.
- It is your responsibility to configure redaction patterns and storage locations appropriately.
- UTF-8 encoded data may contain international characters that should be handled according to your organization's policies.

---

## Disclaimer and Indemnification

This addon is provided "as is" without warranty of any kind, express or implied. The author(s) and contributors shall not be held liable for any damages, loss of data, or privacy breaches resulting from the use, misuse, or inability to use this addon.

By installing or using this addon, you agree to indemnify and hold harmless the author(s), contributors, and maintainers from any claims, damages, liabilities, or expenses arising from your use of the addon, including but not limited to data loss, unauthorized data disclosure, or non-compliance with legal or organizational policies.

**If you do not agree with these terms, do not use this addon.**

---

