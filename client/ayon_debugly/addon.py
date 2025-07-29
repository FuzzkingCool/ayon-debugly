import os
import traceback
from qtpy import QtWidgets, QtGui
from ayon_core.addon import AYONAddon, ITrayAddon
from ayon_debugly.version import __version__
from ayon_debugly.logger import log
from ayon_debugly.ui.debugly_main_window import DebuglyMainWindow
from ayon_debugly.lib import ADDON_ROOT

class DebuglyMenuBuilder:
    def __init__(self, addon):
        self.addon = addon

    def update_menu_contents(self, menu):
        menu.clear()
        # Add "Report an Issue" action
        action = QtWidgets.QAction("Report an Issue", menu)
        action.triggered.connect(self.addon.show_report_window)
        menu.addAction(action)
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

    def show_report_window(self):
        try:
            if self._report_window is None or not self._report_window.isVisible():
                self._report_window = DebuglyMainWindow()
            self._report_window.show()
            self._report_window.raise_()
            self._report_window.activateWindow()
            log.info("Debugly report window shown")
        except Exception as e:
            log.error(f"Failed to show Debugly report window: {e}")
            log.error(traceback.format_exc())