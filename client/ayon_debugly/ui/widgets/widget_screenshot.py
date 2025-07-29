from qtpy import QtWidgets, QtGui, QtCore
import os
import tempfile

class ScreenshotWidget(QtWidgets.QWidget):
    screenshotTaken = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        btn_layout = QtWidgets.QHBoxLayout()
        self.screenshot_btn = QtWidgets.QPushButton("Take Screenshot", self)
        self.capture_area_btn = QtWidgets.QPushButton("Capture Area", self)
        btn_layout.addWidget(self.screenshot_btn)
        btn_layout.addWidget(self.capture_area_btn)
        layout.addLayout(btn_layout)
        self.preview_label = QtWidgets.QLabel("No screenshot taken", self)
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        layout.addWidget(self.preview_label)
        self.screenshot_btn.clicked.connect(self.take_screenshot)
        self.capture_area_btn.clicked.connect(self.capture_area)
        self.screenshot_path = None

    def take_screenshot(self):
        try:
            from ayon_debugly.lib import take_screenshot
            tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmpfile.close()
            take_screenshot(tmpfile.name)
            self.set_preview(tmpfile.name)
            self.screenshotTaken.emit(tmpfile.name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Screenshot Failed", str(e))

    def capture_area(self):
        try:
            from ayon_debugly.ui.widgets.screenshot_marquee import ScreenMarquee
            path = ScreenMarquee.capture_to_file()
            if path:
                self.set_preview(path)
                self.screenshotTaken.emit(path)
            else:
                QtWidgets.QMessageBox.information(self, "Cancelled", "Screenshot cancelled.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Capture Area Failed", str(e))

    def set_preview(self, path):
        pixmap = QtGui.QPixmap(path)
        if not pixmap.isNull():
            self.preview_label.setPixmap(pixmap.scaled(200, 200, QtCore.Qt.KeepAspectRatio))
            self.preview_label.setText("")
            self.screenshot_path = path
        else:
            self.preview_label.setText("Failed to load screenshot")
            self.screenshot_path = None
