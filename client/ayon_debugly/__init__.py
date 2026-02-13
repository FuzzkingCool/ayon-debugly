# -*- coding: utf-8 -*-
import traceback
try:
    from ayon_debugly.logger import log
    from ayon_debugly.version import __version__
    from ayon_debugly.addon import DebuglyAddon
    from ayon_debugly.debugly_app import DebuglyApp
    from ayon_debugly.debugly_issue import DebuglyIssue
    from ayon_debugly.debugly_issue_manager import DebuglyIssueManager

    # log.debug(f"Successfully loaded ayon_debugly {__version__}")

    __all__ = (
        "__version__",
        "log",
        "DebuglyAddon",
        "DebuglyApp",
        "DebuglyIssue",
        "DebuglyIssueManager",
    )
except Exception as e:
    # If logger import failed, use print instead
    print(f"ERROR loading ayon_debugly: {e}")
    print(traceback.format_exc())
    
