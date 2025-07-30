# AYON Debugly Addon

A comprehensive issue reporting and debugging addon for AYON that helps users and administrators track, collect, and manage system issues efficiently.

## Overview

The Debugly addon provides a user-friendly interface for reporting issues with automatic collection of system information, logs, and screenshots. It streamlines the debugging process by gathering all relevant data and presenting it in a structured format for easy analysis.

## Features

### **User-Friendly Issue Reporting**
- **WYSIWYG Editor**: Rich text editor with code formatting support
- **User Story Template**: Guided issue reporting with structured questions
- **Screenshot Tools**: Full screen and area selection screenshot capabilities
- **Drag & Drop**: Easy file attachment support

### **Automatic Data Collection**
- **System Information**: OS, platform, and version details
- **Environment Variables**: System environment with sensitive data redaction
- **Software Detection**: Installed software and version information
- **Log Files**: Automatic collection from configured directories and patterns
- **Progress Tracking**: Visual progress indicators during data collection

### **Security & Privacy**
- **Data Redaction**: Automatic redaction of sensitive information (passwords, tokens, API keys)
- **Configurable Patterns**: Customizable redaction rules via server settings
- **Environment Redaction**: Automatic redaction of sensitive environment variables before storage / submission to endpoints

### **Flexible Output**
- **Structured ZIP Archives**: Organized file structure with metadata
- **Multiple Endpoints**: Configurable submission endpoints (shared directory, etc.)
- **Email Integration**: Optional email notifications for issue reports

## Configuration

### Server Settings

The addon can be configured through the AYON server admin interface:

#### **Endpoints**
- **Shared Directory**: Configure a shared network location for issue reports
- **Email Notifications**: Set up email alerts for new issues

#### **Log Collection**
- **Log Directories**: Specify directories to scan for log files
- **Log Patterns**: Configure regex patterns for log file discovery
- **Platform-Specific**: Different settings for Windows, macOS, and Linux

#### **Data Redaction**
- **Environment Variables**: List of sensitive environment variables to redact before storage
- **Log Patterns**: Regex patterns for redacting sensitive data from logs
- **Custom Rules**: Add custom redaction patterns as needed
- **Note**: Data is stored in standard JSON/ZIP format with redaction applied. No additional encryption is provided.

#### **Software Detection**
- **Software List**: Configure software to detect and report versions
- **Platform Paths**: Specify installation paths for different platforms

### Client Settings

The client automatically uses server-side configuration and requires no additional setup.

## Usage

### For Users

1. **Launch Debugly**: Access through the AYON client interface
2. **Describe the Issue**: Use the WYSIWYG editor to describe the problem
3. **Add Context**: Include screenshots, attachments, or additional files
4. **Submit Report**: The system automatically collects all relevant data
5. **Track Progress**: Monitor the collection progress via the status bar

### For Administrators

**Note**: This addon is designed to collect system information for debugging purposes. Data is stored in standard JSON/ZIP format with automatic redaction of sensitive information. Ensure compliance with your organization's data collection and privacy policies. No additional encryption or secure storage is provided beyond the redaction features.

## File Structure

### Generated Issue Reports

Each issue report is packaged as a ZIP file with the following structure:

```
issue_report_YYYY-MM-DD_HH-MM-SS.zip/
├── issue.json                    # Main issue data and metadata
├── attachments/                  # User-provided files
│   ├── screenshot.png
│   └── additional_files/
├── logs/                         # Collected log files
│   ├── application.log
│   └── system.log
```

### Issue JSON Structure

```json
{
  "title": "Issue Title",
  "user_message": "User description",
  "collected_data": {
    "Environment": { "env": {...} },
    "System": { "platform": "...", "version": "..." },
    "Software": { "installed": [...] }
  },
  "attachments": ["path/to/files"],
  "log_files": ["path/to/logs"],
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Development

### Architecture

- **Client**: PyQt-based GUI with collector system
- **Server**: AYON addon with settings management
- **Collectors**: Modular data collection system
- **Endpoints**: Pluggable submission endpoints

### Adding Custom Collectors

1. Create a new collector class inheriting from `CollectorBase`
2. Implement the `collect()` method
3. Register the collector in the collector system
4. Create and Configure collection settings in /server/settings/main.py

### Adding Custom Endpoints

1. Create a new endpoint class inheriting from `EndpointBase`
2. Implement the `submit()` method
3. Create and Configure endpoint settings in /server/settings/main.py

---

## Privacy and Data Handling


This addon collects system information, environment variables, log files, and user-provided attachments for the purpose of debugging and issue reporting. While sensitive values (such as passwords, tokens, and API keys) are automatically redacted based on configurable patterns, all collected data is stored in standard JSON and ZIP files without additional encryption or secure storage.

**Administrators and users are responsible for ensuring that the use of this addon complies with all applicable data protection, privacy, and security regulations in their jurisdiction and organization.**

By using this addon, you acknowledge and accept that:

- Collected data may include sensitive or personally identifiable information (PII) if not properly redacted.
- The addon does not provide encryption or advanced security for stored data.
- It is your responsibility to configure redaction patterns and storage locations appropriately.

---

## Disclaimer and Indemnification

This addon is provided “as is” without warranty of any kind, express or implied. The author(s) and contributors shall not be held liable for any damages, loss of data, or privacy breaches resulting from the use, misuse, or inability to use this addon.

By installing or using this addon, you agree to indemnify and hold harmless the author(s), contributors, and maintainers from any claims, damages, liabilities, or expenses arising from your use of the addon, including but not limited to data loss, unauthorized data disclosure, or non-compliance with legal or organizational policies.

**If you do not agree with these terms, do not use this addon.**

---

