"""
This module is the controllerresponsible for managing the Debugly issue submission process.
It collects data from the system and submits it to the Debugly endpoint.
"""

import traceback

import ayon_api
from qtpy import QtCore, QtWidgets

from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.endpoints.endpoint_shared_dir import EndpointSharedDir
from ayon_debugly.logger import log

from .version import __version__


class DebuglyApp:
    def __init__(self):
        log.info("Initializing DebuglyApp...")
        self.settings = self.get_settings()
        self.endpoint = self.get_endpoint()
        log.info("DebuglyApp initialized with endpoint: %s", type(self.endpoint).__name__)

    def get_settings(self):
        log.info("Fetching settings from AYON server...")
        try:
            settings = ayon_api.get_addon_settings("debugly", __version__)
            log.info("Loaded settings from AYON server: %s", settings)
            return settings
        except Exception as e:
            log.warning(f"Could not load server settings: {e}. Using collector defaults.")
            return None



    def submit_report(self, title, user_message, attachments=None, screenshot=None, extra_attachments=None):
        log.info("Submitting report...")
        progress = QtWidgets.QProgressDialog("Submitting report...", None, 0, 0, None)
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.show()
        QtWidgets.QApplication.processEvents()
        try:
            all_attachments = (attachments or []) + (extra_attachments or [])
            log.info(f"Building DebuglyIssue with {len(all_attachments)} attachments.")
            issue = DebuglyIssue(title, user_message, {}, all_attachments, screenshot)
            progress.setLabelText("Submitting report...")
            QtWidgets.QApplication.processEvents()
            dest = self.endpoint.submit(issue)
            log.info(f"Report submitted to endpoint: {dest}")
            progress.close()
            QtWidgets.QMessageBox.information(None, "Success", "Report submitted!")
            return dest
        except Exception as e:
            progress.close()
            log.error(f"Failed to submit report: {e}")
            log.error(traceback.format_exc())
            QtWidgets.QMessageBox.critical(None, "Error", f"Failed to submit report: {e}")
            raise

    def get_endpoint(self):
        endpoint_type = getattr(self.settings, "endpoint", "shared_dir")
        log.info(f"Selecting endpoint: {endpoint_type}")
        if endpoint_type == "shared_dir":
            return EndpointSharedDir(settings=self.settings)
        # Add more endpoints as needed
        # elif endpoint_type == "server":
        #     return ServerEndpoint()
        else:
            log.warning(f"Unknown endpoint type: {endpoint_type}, defaulting to SharedDirEndpoint.")
            return EndpointSharedDir(settings=self.settings)
 