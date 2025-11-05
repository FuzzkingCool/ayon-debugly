# -*- coding: utf-8 -*-
"""
This module is the controllerresponsible for managing the Debugly issue submission process.
It collects data from the system and submits it to the Debugly endpoint.
"""

import traceback

import ayon_api

from ayon_debugly.debugly_issue_manager import DebuglyIssueManager
from ayon_debugly.logger import log
from ayon_debugly.version import __version__


class DebuglyApp:
    def __init__(self):
        log.debug("Initializing DebuglyApp...")
        self.settings = self.get_settings()
        self.issue_manager = DebuglyIssueManager(settings=self.settings)
        log.debug("DebuglyApp initialized with issue manager")

    def get_settings(self):
        log.debug("Fetching settings from AYON server...")
        try:
            settings = ayon_api.get_addon_settings("debugly", __version__)
            log.debug("Loaded settings from AYON server: %s", settings)

            # Debug: Check if notion settings are present
            if isinstance(settings, dict) and "endpoints" in settings:
                notion_settings = settings.get("endpoints", {}).get("notion", {})
                if notion_settings:
                    notion_config = notion_settings.get("notion", {})
                    database_id = notion_config.get("database_id", "")
                    log.debug(
                        f"Notion database_id from server: '{database_id}' (length: {len(database_id)})"
                    )
                    if not database_id:
                        log.warning("Notion database_id is empty in server settings!")
                else:
                    log.warning("No notion settings found in server response")
            else:
                log.warning("No endpoints found in server settings")

            return settings
        except Exception as e:
            log.warning(
                f"Could not load server settings: {e}. Using collector defaults."
            )
            return None

    def submit_report(
        self,
        title,
        user_message,
        attachments=None,
        screenshot=None,
        log_files=None,
        collected_data=None,
        progress_callback=None,
    ):
        log.debug("Submitting report...")
        try:
            log.debug(
                f"Building DebuglyIssue with {len(attachments or [])} attachments and {len(log_files or [])} log files."
            )

            # Use the issue manager to submit to all enabled endpoints
            results = self.issue_manager.submit_report(
                title,
                user_message,
                attachments,
                screenshot,
                log_files,
                collected_data,
                progress_callback,
            )

            log.debug(f"Report submitted to {len(results)} endpoint(s)")
            return results
        except Exception as e:
            log.error(f"Failed to submit report: {e}")
            log.error(traceback.format_exc())
            raise
