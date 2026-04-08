# -*- coding: utf-8 -*-
import os

from qtpy import QtCore, QtGui, QtWidgets

from ayon_debugly.logger import log


class ScreenshotCarousel(QtWidgets.QWidget):
    """Preview current screenshot on its own row; prev/next thumbs and buttons on a row below."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.screenshots = []
        self.current_index = 0
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Main preview: full width of carousel, grows when the splitter resizes (no overlap with nav)
        self.current_thumbnail = QtWidgets.QLabel("No screenshots")
        self.current_thumbnail.setMinimumSize(200, 120)
        self.current_thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.current_thumbnail.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        self.current_thumbnail.setStyleSheet("""
            QLabel {
                border: 2px solid #666666;
                background: #151515;
                color: #E0E0E0;
                border-radius: 4px;
            }
        """)

        # Navigation row: side thumbs + arrows stay below the main image
        nav_layout = QtWidgets.QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(8)

        self.prev_thumbnail = QtWidgets.QLabel()
        self.prev_thumbnail.setFixedSize(80, 60)
        self.prev_thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.prev_thumbnail.setStyleSheet("""
            QLabel {
                border: 1px solid #444444;
                background: #121212;
                border-radius: 4px;
                color: #888888;
            }
        """)
        self.prev_thumbnail.setText("")

        self.prev_btn = QtWidgets.QPushButton("◀")
        self.prev_btn.setFixedSize(24, 24)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 12px;
                color: #E0E0E0;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
            }
            QPushButton:disabled {
                color: #666666;
                background-color: #1D1D1D;
            }
        """)
        self.prev_btn.clicked.connect(self.previous_screenshot)

        self.next_btn = QtWidgets.QPushButton("▶")
        self.next_btn.setFixedSize(24, 24)
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 12px;
                color: #E0E0E0;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
            }
            QPushButton:disabled {
                color: #666666;
                background-color: #1D1D1D;
            }
        """)
        self.next_btn.clicked.connect(self.next_screenshot)

        self.next_thumbnail = QtWidgets.QLabel()
        self.next_thumbnail.setFixedSize(80, 60)
        self.next_thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.next_thumbnail.setStyleSheet("""
            QLabel {
                border: 1px solid #444444;
                background: #121212;
                border-radius: 4px;
                color: #888888;
            }
        """)
        self.next_thumbnail.setText("")

        self.filename_label = QtWidgets.QLabel("")
        self.filename_label.setAlignment(QtCore.Qt.AlignCenter)
        self.filename_label.setWordWrap(True)
        self.filename_label.setMinimumHeight(22)
        self.filename_label.setStyleSheet("""
            QLabel {
                color: #C8C8C8;
                font-size: 12px;
                padding: 0 6px;
                background: transparent;
            }
        """)

        nav_layout.addWidget(self.prev_thumbnail, 0, QtCore.Qt.AlignVCenter)
        nav_layout.addWidget(self.prev_btn, 0, QtCore.Qt.AlignVCenter)
        nav_layout.addWidget(self.filename_label, 1, QtCore.Qt.AlignVCenter)
        nav_layout.addWidget(self.next_btn, 0, QtCore.Qt.AlignVCenter)
        nav_layout.addWidget(self.next_thumbnail, 0, QtCore.Qt.AlignVCenter)

        layout.addWidget(self.current_thumbnail, 1)
        layout.addLayout(nav_layout)

        self.current_thumbnail.mouseDoubleClickEvent = self.open_current_screenshot

    def _main_preview_pixel_size(self):
        """Scale factor for the large preview from current label geometry."""
        w = self.current_thumbnail.width() - 8
        h = self.current_thumbnail.height() - 8
        if w < 80:
            w = 200
        if h < 60:
            h = 120
        return w, h

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.screenshots:
            self.update_display()

    def add_screenshot(self, file_path):
        if file_path not in self.screenshots:
            self.screenshots.append(file_path)
            self.current_index = len(self.screenshots) - 1
            self.update_display()
            self.update_navigation()

    def remove_screenshot(self, file_path):
        if file_path in self.screenshots:
            index = self.screenshots.index(file_path)
            self.screenshots.remove(file_path)

            if len(self.screenshots) == 0:
                self.current_index = 0
            elif self.current_index >= len(self.screenshots):
                self.current_index = len(self.screenshots) - 1
            elif self.current_index >= index:
                self.current_index = max(0, self.current_index - 1)

            self.update_display()
            self.update_navigation()

    def update_display(self):
        if not self.screenshots:
            self.current_thumbnail.setText("No screenshots")
            self.current_thumbnail.setPixmap(QtGui.QPixmap())
            self.prev_thumbnail.setPixmap(QtGui.QPixmap())
            self.next_thumbnail.setPixmap(QtGui.QPixmap())
            self.filename_label.setText("")
            return

        pw, ph = self._main_preview_pixel_size()
        current_path = self.screenshots[self.current_index]
        if os.path.exists(current_path):
            pixmap = QtGui.QPixmap(current_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    pw,
                    ph,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
                self.current_thumbnail.setPixmap(scaled_pixmap)
                self.current_thumbnail.setText("")
                self.filename_label.setText(os.path.basename(current_path))
            else:
                self.current_thumbnail.setText("Invalid image")
                self.current_thumbnail.setPixmap(QtGui.QPixmap())
                self.filename_label.setText("")
        else:
            self.current_thumbnail.setText("File not found")
            self.current_thumbnail.setPixmap(QtGui.QPixmap())
            self.filename_label.setText("")

        if self.current_index > 0:
            prev_path = self.screenshots[self.current_index - 1]
            if os.path.exists(prev_path):
                pixmap = QtGui.QPixmap(prev_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(
                        80,
                        60,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                    faded_pixmap = QtGui.QPixmap(scaled_pixmap.size())
                    faded_pixmap.fill(QtCore.Qt.transparent)
                    painter = QtGui.QPainter(faded_pixmap)
                    painter.setOpacity(0.4)
                    painter.drawPixmap(0, 0, scaled_pixmap)
                    painter.end()
                    self.prev_thumbnail.setPixmap(faded_pixmap)
                    self.prev_thumbnail.setText("")
                else:
                    self.prev_thumbnail.setText("")
            else:
                self.prev_thumbnail.setText("")
        else:
            self.prev_thumbnail.setText("")

        if self.current_index < len(self.screenshots) - 1:
            next_path = self.screenshots[self.current_index + 1]
            if os.path.exists(next_path):
                pixmap = QtGui.QPixmap(next_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(
                        80,
                        60,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation,
                    )
                    faded_pixmap = QtGui.QPixmap(scaled_pixmap.size())
                    faded_pixmap.fill(QtCore.Qt.transparent)
                    painter = QtGui.QPainter(faded_pixmap)
                    painter.setOpacity(0.4)
                    painter.drawPixmap(0, 0, scaled_pixmap)
                    painter.end()
                    self.next_thumbnail.setPixmap(faded_pixmap)
                    self.next_thumbnail.setText("")
                else:
                    self.next_thumbnail.setText("")
            else:
                self.next_thumbnail.setText("")
        else:
            self.next_thumbnail.setText("")

    def update_navigation(self):
        count = len(self.screenshots)
        if count == 0:
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
        else:
            self.prev_btn.setEnabled(self.current_index > 0)
            self.next_btn.setEnabled(self.current_index < count - 1)

    def previous_screenshot(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.update_display()
            self.update_navigation()

    def next_screenshot(self):
        if self.current_index < len(self.screenshots) - 1:
            self.current_index += 1
            self.update_display()
            self.update_navigation()

    def open_current_screenshot(self, event):
        if self.screenshots and 0 <= self.current_index < len(self.screenshots):
            current_path = self.screenshots[self.current_index]
            if os.path.exists(current_path):
                import platform

                try:
                    if platform.system() == "Windows":
                        os.startfile(current_path)
                    elif platform.system() == "Darwin":
                        from ayon_debugly.utils.subprocess_utils import run_silent_subprocess

                        run_silent_subprocess(["open", current_path])
                    else:
                        from ayon_debugly.utils.subprocess_utils import run_silent_subprocess

                        run_silent_subprocess(["xdg-open", current_path])
                except Exception as e:
                    log.debug(f"Failed to open screenshot: {e}")

    def get_screenshots(self):
        return self.screenshots.copy()
