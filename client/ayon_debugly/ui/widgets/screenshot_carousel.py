# -*- coding: utf-8 -*-
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
        layout.setSpacing(8)
        
        # Main carousel area with thumbnails
        carousel_layout = QtWidgets.QHBoxLayout()
        carousel_layout.setContentsMargins(0, 0, 0, 0)
        carousel_layout.setSpacing(8)
        
        # Previous thumbnail (smaller and faded)
        self.prev_thumbnail = QtWidgets.QLabel()
        self.prev_thumbnail.setFixedSize(80, 60)
        self.prev_thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.prev_thumbnail.setStyleSheet("""
            QLabel {
                border: 1px solid #444444;
                background: #1D1D1D;
                border-radius: 4px;
                color: #888888;
            }
        """)
        self.prev_thumbnail.setText("")
        
        # Previous button
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
        
        # Current screenshot (main display)
        self.current_thumbnail = QtWidgets.QLabel("No screenshots")
        self.current_thumbnail.setFixedSize(200, 120)
        self.current_thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.current_thumbnail.setStyleSheet("""
            QLabel {
                border: 2px solid #666666;
                background: #2D2D2D;
                color: #E0E0E0;
                border-radius: 4px;
            }
        """)
        
        # Next button
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
        
        # Next thumbnail (smaller and faded)
        self.next_thumbnail = QtWidgets.QLabel()
        self.next_thumbnail.setFixedSize(80, 60)
        self.next_thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.next_thumbnail.setStyleSheet("""
            QLabel {
                border: 1px solid #444444;
                background: #1D1D1D;
                border-radius: 4px;
                color: #888888;
            }
        """)
        self.next_thumbnail.setText("")
        
        # Add widgets to carousel layout
        carousel_layout.addWidget(self.prev_thumbnail)
        carousel_layout.addWidget(self.prev_btn)
        carousel_layout.addWidget(self.current_thumbnail, 1)  # Give it stretch
        carousel_layout.addWidget(self.next_btn)
        carousel_layout.addWidget(self.next_thumbnail)
        
        layout.addLayout(carousel_layout)
        
        # Filename display (centered)
        self.filename_label = QtWidgets.QLabel("")
        self.filename_label.setAlignment(QtCore.Qt.AlignCenter)
        self.filename_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 10px;
                padding: 2px;
            }
        """)
        layout.addWidget(self.filename_label)
        
        # Double-click to open
        self.current_thumbnail.mouseDoubleClickEvent = self.open_current_screenshot
        
    def add_screenshot(self, file_path):
        """Add a screenshot to the carousel"""
        if file_path not in self.screenshots:
            self.screenshots.append(file_path)
            # Select the latest screenshot
            self.current_index = len(self.screenshots) - 1
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
        """Update the current screenshot display with side thumbnails"""
        if not self.screenshots:
            self.current_thumbnail.setText("No screenshots")
            self.current_thumbnail.setPixmap(QtGui.QPixmap())
            self.prev_thumbnail.setPixmap(QtGui.QPixmap())
            self.next_thumbnail.setPixmap(QtGui.QPixmap())
            self.filename_label.setText("")
            return
            
        # Update current thumbnail
        current_path = self.screenshots[self.current_index]
        if os.path.exists(current_path):
            pixmap = QtGui.QPixmap(current_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    200, 120, 
                    QtCore.Qt.KeepAspectRatio, 
                    QtCore.Qt.SmoothTransformation
                )
                self.current_thumbnail.setPixmap(scaled_pixmap)
                self.current_thumbnail.setText("")
                
                # Update filename
                filename = os.path.basename(current_path)
                self.filename_label.setText(filename)
            else:
                self.current_thumbnail.setText("Invalid image")
                self.filename_label.setText("")
        else:
            self.current_thumbnail.setText("File not found")
            self.filename_label.setText("")
            
        # Update previous thumbnail
        if self.current_index > 0:
            prev_path = self.screenshots[self.current_index - 1]
            if os.path.exists(prev_path):
                pixmap = QtGui.QPixmap(prev_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(
                        80, 60, 
                        QtCore.Qt.KeepAspectRatio, 
                        QtCore.Qt.SmoothTransformation
                    )
                    # Create faded version
                    faded_pixmap = QtGui.QPixmap(scaled_pixmap.size())
                    faded_pixmap.fill(QtCore.Qt.transparent)
                    painter = QtGui.QPainter(faded_pixmap)
                    painter.setOpacity(0.4)  # Fade to 40% opacity
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
            
        # Update next thumbnail
        if self.current_index < len(self.screenshots) - 1:
            next_path = self.screenshots[self.current_index + 1]
            if os.path.exists(next_path):
                pixmap = QtGui.QPixmap(next_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(
                        80, 60, 
                        QtCore.Qt.KeepAspectRatio, 
                        QtCore.Qt.SmoothTransformation
                    )
                    # Create faded version
                    faded_pixmap = QtGui.QPixmap(scaled_pixmap.size())
                    faded_pixmap.fill(QtCore.Qt.transparent)
                    painter = QtGui.QPainter(faded_pixmap)
                    painter.setOpacity(0.4)  # Fade to 40% opacity
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
        """Update navigation buttons"""
        count = len(self.screenshots)
        if count == 0:
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
        else:
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
                import platform
                
                try:
                    if platform.system() == "Windows":
                        os.startfile(current_path)
                    elif platform.system() == "Darwin":  # macOS
                        from ayon_debugly.utils.subprocess_utils import run_silent_subprocess
                        run_silent_subprocess(["open", current_path])
                    else:  # Linux
                        from ayon_debugly.utils.subprocess_utils import run_silent_subprocess
                        run_silent_subprocess(["xdg-open", current_path])
                except Exception as e:
                    log.debug(f"Failed to open screenshot: {e}")
                    
    def get_screenshots(self):
        """Get list of all screenshots"""
        return self.screenshots.copy()