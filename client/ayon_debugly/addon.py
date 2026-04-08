# -*- coding: utf-8 -*-
import os
import traceback

from ayon_core.addon import AYONAddon, ITrayAddon
from ayon_core.lib import run_detached_ayon_launcher_process
from qtpy import QtGui, QtWidgets

from ayon_debugly.desktop_shortcut import create_staging_desktop_shortcut
from ayon_debugly.lib import ADDON_ROOT
from ayon_debugly.logger import log
from ayon_debugly.ui.debugly_main_window import DebuglyMainWindow
from ayon_debugly.version import __version__


class DebuglyMenuBuilder:
    def __init__(self, addon):
        self.addon = addon

    def update_menu_contents(self, menu):
        menu.clear()
        # Add "Report an Issue" action
        report_icon_path = os.path.join(ADDON_ROOT, "resources", "report.png")
        if os.path.exists(report_icon_path):
            action = QtWidgets.QAction(
                QtGui.QIcon(report_icon_path), "Report an Issue", menu
            )
        else:
            action = QtWidgets.QAction("Report an Issue", menu)
        action.triggered.connect(self.addon.show_report_window)
        menu.addAction(action)

        # Add "Restart with DEBUG enabled" action
        debug_icon_path = os.path.join(ADDON_ROOT, "resources", "debug.png")
        if os.path.exists(debug_icon_path):
            debug_action = QtWidgets.QAction(
                QtGui.QIcon(debug_icon_path), "Restart with DEBUG enabled", menu
            )
        else:
            debug_action = QtWidgets.QAction("Restart with DEBUG enabled", menu)
        debug_action.triggered.connect(self.addon.restart_with_debug)
        menu.addAction(debug_action)

        # Add "Restart AYON to Staging Release" action
        staging_icon_path = os.path.join(ADDON_ROOT, "resources", "AYON_icon_staging.png")
        if os.path.exists(staging_icon_path):
            staging_action = QtWidgets.QAction(
                QtGui.QIcon(staging_icon_path), "Restart AYON to Staging Release", menu
            )
        else:
            staging_action = QtWidgets.QAction("Restart AYON to Staging Release", menu)
        staging_action.triggered.connect(self.addon.restart_to_staging)
        menu.addAction(staging_action)

        # Add "Create desktop shortcut (Staging)" action
        shortcut_icon_path = os.path.join(ADDON_ROOT, "resources", "AYON_icon_staging.png")
        if os.path.exists(shortcut_icon_path):
            shortcut_action = QtWidgets.QAction(
                QtGui.QIcon(shortcut_icon_path), "Create desktop shortcut (Staging)", menu
            )
        else:
            shortcut_action = QtWidgets.QAction("Create desktop shortcut (Staging)", menu)
        shortcut_action.triggered.connect(self.addon.create_staging_desktop_shortcut)
        menu.addAction(shortcut_action)

        menu.addSeparator()
        # Add more actions/settings here as needed

class DebuglyAddon(AYONAddon, ITrayAddon):
    """
    Debugly addon for AYON.

    This addon provides a way to report issues from the ayon launcher app.
    """

    name = "debugly"
    label = "Debugly"
    version = __version__

    _report_window = None
    _menu_builder = None
    _tray_icon = None
    _menu = None

    def initialize(self, settings):
        """Initialization of addon."""
        log.debug("Initializing Debugly addon")

        self.settings = settings.get("debugly", {})
        self._menu_builder = DebuglyMenuBuilder(self)
        self.tray_icon = None
        self._menu = None

    def tray_init(self):
        # Called when tray is initialized
        if not self.tray_icon:
            self.tray_icon = QtWidgets.QSystemTrayIcon(self.get_icon())
            self.tray_icon.setToolTip(self.label)
            self.tray_icon.show()

    def tray_start(self):
        # Called when tray is started
        self._update_menu()

    def tray_exit(self):
        # Called when tray is exiting
        if self.tray_icon:
            self.tray_icon.hide()
            self.tray_icon = None
        if self._report_window:
            self._report_window.close()
            self._report_window = None

    def tray_menu(self, tray_menu):
        menu = QtWidgets.QMenu(self.label, tray_menu)
        menu.setProperty("submenu", "off")
        menu.setProperty("parentTrayMenu", tray_menu)
        tray_menu.addMenu(menu)
        self._menu = menu
        self._menu_builder.update_menu_contents(menu)
        # Connect aboutToShow for dynamic updates
        menu.aboutToShow.connect(lambda: self._menu_builder.update_menu_contents(menu))
        # Store for notifications if needed
        if not hasattr(QtWidgets.QApplication, "_debugly_menu"):
            QtWidgets.QApplication._debugly_menu = menu

    def _update_menu(self):
        if self._menu:
            self._menu_builder.update_menu_contents(self._menu)

    def get_icon(self):
        icon_path = os.path.join(ADDON_ROOT, "resources", "icon.png")
        if os.path.exists(icon_path):
            return QtGui.QIcon(icon_path)
        return QtGui.QIcon()  # fallback

    def create_staging_desktop_shortcut(self):
        """Create a desktop shortcut that launches AYON with --use-staging --verbose DEBUG."""
        try:
            success, message = create_staging_desktop_shortcut(ADDON_ROOT)
            if success:
                QtWidgets.QMessageBox.information(
                    None,
                    "Shortcut created",
                    f"Desktop shortcut created:\n{message}",
                )
            else:
                QtWidgets.QMessageBox.warning(
                    None,
                    "Shortcut creation failed",
                    message,
                )
        except Exception as e:
            log.error("Create desktop shortcut failed: %s", e)
            log.error(traceback.format_exc())
            QtWidgets.QMessageBox.critical(
                None,
                "Shortcut creation failed",
                str(e),
            )

    def restart_to_staging(self):
        """Restart AYON in staging release: create/update desktop shortcut, then relaunch with --use-staging."""
        try:
            log.debug("Restart to staging: creating/updating desktop shortcut")
            success, message = create_staging_desktop_shortcut(ADDON_ROOT)
            if success:
                log.debug("Desktop shortcut created/updated: %s", message)
            else:
                log.warning("Desktop shortcut create/update failed (continuing): %s", message)

            warning_dialog = QtWidgets.QMessageBox()
            warning_dialog.setIcon(QtWidgets.QMessageBox.Warning)
            warning_dialog.setWindowTitle("Restart to Staging")
            warning_dialog.setText("AYON will close and reopen in staging release.")
            warning_dialog.setInformativeText(
                "Before proceeding, please save your work and close all AYON-integrated applications.\n\n"
                "The current AYON instance will close and restart with staging, "
                "--debug, and verbose DEBUG logging."
            )
            warning_dialog.setStandardButtons(
                QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
            )
            warning_dialog.setDefaultButton(QtWidgets.QMessageBox.Cancel)

            if warning_dialog.exec_() == QtWidgets.QMessageBox.Cancel:
                log.debug("User cancelled restart to staging")
                return

            run_detached_ayon_launcher_process(
                "--use-staging", "--debug", "--verbose", "DEBUG"
            )
            QtWidgets.QApplication.quit()
        except Exception as e:
            log.error("Failed to restart AYON to staging: %s", e)
            log.error(traceback.format_exc())
            QtWidgets.QMessageBox.critical(
                None,
                "Restart Failed",
                f"Failed to restart AYON to staging:\n{str(e)}",
            )

    def show_report_window(self):
        try:
            if self._report_window is None or not self._report_window.isVisible():
                self._report_window = DebuglyMainWindow()
            self._report_window.show()
            self._report_window.raise_()
            self._report_window.activateWindow()
            log.debug("Debugly report window shown")
        except Exception as e:
            log.error(f"Failed to show Debugly report window: {e}")
            log.error(traceback.format_exc())

    def restart_with_debug(self):
        """Restart AYON with debug flags enabled."""
        try:
            log.debug("Restarting AYON with DEBUG enabled")
            
            # Show warning dialog to user about saving work and closing applications
            warning_dialog = QtWidgets.QMessageBox()
            warning_dialog.setIcon(QtWidgets.QMessageBox.Warning)
            warning_dialog.setWindowTitle("AYON Restart Warning")
            warning_dialog.setText("AYON will restart with DEBUG logging enabled.")
            warning_dialog.setInformativeText(
                "⚠️  IMPORTANT: Before proceeding, please:\n\n"
                "• Save your work in all AYON-integrated applications\n"
                "• Close all AYON-integrated applications (Blender, Photoshop, Harmony etc.)\n"
                "• Close any other applications that may be using AYON\n\n"
                "The current AYON instance will close and restart with debug flags.\n"
                "Any unsaved work or open applications may be affected."
            )
            warning_dialog.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
            warning_dialog.setDefaultButton(QtWidgets.QMessageBox.Cancel)
            
            # Show the dialog and check user response
            user_response = warning_dialog.exec_()
            
            if user_response == QtWidgets.QMessageBox.Cancel:
                log.debug("User cancelled AYON restart")
                return
            
            # User clicked OK, proceed with restart
            log.debug("User confirmed AYON restart")
            
            # Use the existing tray manager restart method with debug flags
            if hasattr(self, '_tray_manager') and self._tray_manager:
                # Temporarily modify sys.argv to include debug flags
                import sys
                original_argv = sys.argv.copy()
                
                # Add debug flags to sys.argv
                sys.argv.extend(["--debug", "--verbose", "DEBUG"])
                
                try:
                    # Call the existing restart method
                    self._tray_manager.restart()
                finally:
                    # Restore original sys.argv
                    sys.argv = original_argv
            else:
                log.error("Tray manager not available for restart")
                QtWidgets.QMessageBox.critical(
                    None,
                    "Restart Failed",
                    "Tray manager not available for restart."
                )
            
        except Exception as e:
            log.error(f"Failed to restart AYON with DEBUG: {e}")
            log.error(traceback.format_exc())
            
            # Show error message to user
            QtWidgets.QMessageBox.critical(
                None,
                "Restart Failed",
                f"Failed to restart AYON with DEBUG enabled:\n{str(e)}"
            )
    
    def _exit_current_ayon(self):
        """Exit the current AYON instance after launching the new one."""
        try:
            log.debug("Exiting current AYON instance")
            
            # Use a more direct approach to exit the process
            # AYON tray application may not respond well to app.quit()
            import sys
            import os
            
            # Force exit the current process
            os._exit(0)
                
        except Exception as e:
            log.error(f"Failed to exit current AYON instance: {e}")
            log.error(traceback.format_exc())
            # Force exit as fallback
            import os
            os._exit(0)
    
    def _force_exit_current_ayon(self):
        """Force exit the current AYON instance if the first exit fails."""
        try:
            log.debug("Force exiting current AYON instance due to slow exit")
            import os
            os._exit(0)
        except Exception as e:
            log.error(f"Failed to force exit current AYON instance: {e}")
            log.error(traceback.format_exc())
    
    def _show_debug_relaunch_success(self):
        """Show success notification for debug relaunch."""
        try:
            log.debug("Showing debug relaunch success notification")
            
            # Use a simpler approach - just log the success message
            log.debug("AYON has been successfully restarted with DEBUG logging enabled!")
            log.debug("Next Steps:")
            log.debug("1. Try to recreate the problem you were experiencing")
            log.debug("2. The debug logs will now capture detailed information")
            log.debug("3. When ready, use 'Report an Issue' to submit your report")
            log.debug("4. The debug logs will be automatically included")
            
            # Show a simple message box without complex formatting
            QtWidgets.QMessageBox.information(
                None,
                "AYON Debug Mode Active",
                "AYON has been successfully restarted with DEBUG logging enabled!\n\n"
                "Next Steps:\n"
                "1. Try to recreate the problem you were experiencing\n"
                "2. The debug logs will now capture detailed information\n"
                "3. When ready, use 'Report an Issue' to submit your report\n"
                "4. The debug logs will be automatically included"
            )
            
            log.debug("Debug relaunch success notification shown and closed")
            
        except Exception as e:
            log.error(f"Failed to show debug relaunch success notification: {e}")
            log.error(traceback.format_exc())