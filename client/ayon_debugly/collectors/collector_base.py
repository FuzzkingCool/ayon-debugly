# -*- coding: utf-8 -*-
import re
from abc import ABC, abstractmethod

import ayon_api


def get_redact_keys_from_settings():
    """Get redact keys from AYON server settings."""
    try:
        from ayon_debugly.version import __version__
        settings = ayon_api.get_addon_settings("debugly", __version__)
        if (hasattr(settings, "redactions") and 
            hasattr(settings.redactions, "environment") and 
            hasattr(settings.redactions.environment, "enabled") and
            settings.redactions.environment.enabled and
            hasattr(settings.redactions.environment, "env_redact_keys")):
            return settings.redactions.environment.env_redact_keys
        elif (isinstance(settings, dict) and 
              "redactions" in settings and
              "environment" in settings["redactions"] and
              "enabled" in settings["redactions"]["environment"] and
              settings["redactions"]["environment"]["enabled"] and
              "env_redact_keys" in settings["redactions"]["environment"]):
            return settings["redactions"]["environment"]["env_redact_keys"]
    except Exception:
        pass
    # Fallback to default keys
    return ["password", "token", "secret", "key", "auth", "session", "cookie", "kitsu_pwd"]

def get_log_redactions_from_settings():
    """Get log redaction patterns from AYON server settings."""
    try:
        from ayon_debugly.version import __version__
        settings = ayon_api.get_addon_settings("debugly", __version__)
        if (hasattr(settings, "redactions") and 
            hasattr(settings.redactions, "log") and 
            hasattr(settings.redactions.log, "enabled") and
            settings.redactions.log.enabled and
            hasattr(settings.redactions.log, "log_redactions")):
            return settings.redactions.log.log_redactions
        elif (isinstance(settings, dict) and 
              "redactions" in settings and
              "log" in settings["redactions"] and
              "enabled" in settings["redactions"]["log"] and
              settings["redactions"]["log"]["enabled"] and
              "log_redactions" in settings["redactions"]["log"]):
            return settings["redactions"]["log"]["log_redactions"]
    except Exception:
        pass
    # Fallback to default redactions
    return [
        {"pattern": "password=([^\\s&;,\\n]+)", "replacement": "password=***REDACTED***"},
        {"pattern": "token=([a-zA-Z0-9_-]+)", "replacement": "token=***REDACTED***"},
        {"pattern": "secret=([^\\s&;,\\n]+)", "replacement": "secret=***REDACTED***"},
        {"pattern": "api_key=([^\\s&;,\\n]+)", "replacement": "api_key=***REDACTED***"},
        {"pattern": "auth_token=([^\\s&;,\\n]+)", "replacement": "auth_token=***REDACTED***"},
    ]

def redact_dict(d):
    """Redact sensitive information from dictionary using settings."""
    redact_keys = get_redact_keys_from_settings()
    result = {}
    for k, v in d.items():
        if any(s.lower() in k.lower() for s in redact_keys):
            result[k] = "***REDACTED***"
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        else:
            result[k] = v
    return result

def redact_log_content(content):
    """Redact sensitive information from log content using settings."""
    if not content:
        return content
    
    redactions = get_log_redactions_from_settings()
    result = content
    
    for redaction in redactions:
        try:
            pattern = redaction.get("pattern", "")
            replacement = redaction.get("replacement", "***REDACTED***")
            if pattern:
                result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        except Exception:
            # Skip invalid regex patterns
            continue
    
    return result

class CollectorBase(ABC):
    @abstractmethod
    def collect(self):
        """Collects and returns a dictionary of data."""
        pass
