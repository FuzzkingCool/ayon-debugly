from qtpy import QtWidgets, QtCore, QtGui
import os
from ayon_debugly.logger import log

class ScreenshotCarousel(QtWidgets.QWidget):
    """Widget to display screenshot thumbnails in a carousel format"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.screenshots = []
        self.current_index = 0
        self.setup_ui()
        
    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Screenshot display area
        self.screenshot_label = QtWidgets.QLabel("No screenshots")
        self.screenshot_label.setAlignment(QtCore.Qt.AlignCenter)
        self.screenshot_label.setMinimumHeight(120)
        self.screenshot_label.setMaximumHeight(120)
        self.screenshot_label.setStyleSheet("""
            QLabel {
                border: 1px dashed #666666;
                background: #2D2D2D;
                color: #E0E0E0;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.screenshot_label)
        
        # Navigation controls
        nav_layout = QtWidgets.QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        
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
        
        self.info_label = QtWidgets.QLabel("0/0")
        self.info_label.setAlignment(QtCore.Qt.AlignCenter)
        self.info_label.setStyleSheet("color: #888888; font-size: 10px;")
        
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
        
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.info_label, 1)
        nav_layout.addWidget(self.next_btn)
        
        layout.addLayout(nav_layout)
        
        # Double-click to open
        self.screenshot_label.mouseDoubleClickEvent = self.open_current_screenshot
        
    def add_screenshot(self, file_path):
        """Add a screenshot to the carousel"""
        if file_path not in self.screenshots:
            self.screenshots.append(file_path)
            if len(self.screenshots) == 1:
                self.current_index = 0
                self.update_display()
            self.update_navigation()
            
    def remove_screenshot(self, file_path):
        """Remove a screenshot from the carousel"""
        if file_path in self.screenshots:
            index = self.screenshots.index(file_path)
            self.screenshots.remove(file_path)
            
            # Adjust current index if needed
            if len(self.screenshots) == 0:
                self.current_index = 0
            elif self.current_index >= len(self.screenshots):
                self.current_index = len(self.screenshots) - 1
            elif self.current_index >= index:
                self.current_index = max(0, self.current_index - 1)
                
            self.update_display()
            self.update_navigation()
            
    def update_display(self):
        """Update the current screenshot display"""
        if not self.screenshots:
            self.screenshot_label.setText("No screenshots")
            self.screenshot_label.setPixmap(QtGui.QPixmap())
            return
            
        current_path = self.screenshots[self.current_index]
        if os.path.exists(current_path):
            pixmap = QtGui.QPixmap(current_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    200, 120, 
                    QtCore.Qt.KeepAspectRatio, 
                    QtCore.Qt.SmoothTransformation
                )
                self.screenshot_label.setPixmap(scaled_pixmap)
                self.screenshot_label.setText("")
            else:
                self.screenshot_label.setText("Invalid image")
        else:
            self.screenshot_label.setText("File not found")
            
    def update_navigation(self):
        """Update navigation buttons and info"""
        count = len(self.screenshots)
        if count == 0:
            self.info_label.setText("0/0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
        else:
            self.info_label.setText(f"{self.current_index + 1}/{count}")
            self.prev_btn.setEnabled(self.current_index > 0)
            self.next_btn.setEnabled(self.current_index < count - 1)
            
    def previous_screenshot(self):
        """Show previous screenshot"""
        if self.current_index > 0:
            self.current_index -= 1
            self.update_display()
            self.update_navigation()
            
    def next_screenshot(self):
        """Show next screenshot"""
        if self.current_index < len(self.screenshots) - 1:
            self.current_index += 1
            self.update_display()
            self.update_navigation()
            
    def open_current_screenshot(self, event):
        """Open the current screenshot in default application"""
        if self.screenshots and 0 <= self.current_index < len(self.screenshots):
            current_path = self.screenshots[self.current_index]
            if os.path.exists(current_path):
                import subprocess
                import platform
                
                try:
                    if platform.system() == "Windows":
                        os.startfile(current_path)
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.run(["open", current_path], check=True)
                    else:  # Linux
                        subprocess.run(["xdg-open", current_path], check=True)
                except Exception as e:
                    log.debug(f"Failed to open screenshot: {e}")
                    
    def get_screenshots(self):
        """Get list of all screenshots"""
        return self.screenshots.copy()