from abc import ABC, abstractmethod
import os
import json

REDACT_KEYS = ["password", "token", "secret", "key", "auth", "session", "cookie"]

def redact_dict(d):
    result = {}
    for k, v in d.items():
        if any(s in k.lower() for s in REDACT_KEYS):
            result[k] = "***REDACTED***"
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        else:
            result[k] = v
    return result

class CollectorBase(ABC):
    @abstractmethod
    def collect(self):
        """Collects and returns a dictionary of data."""
        pass
