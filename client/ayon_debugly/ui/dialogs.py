# -*- coding: utf-8 -*-
"""Methods for showing dialogs that can be imported from AYON Debugly."""

import os
import sys
from qtpy import QtCore, QtGui, QtWidgets


def get_main_window():
    """Get the main window widget."""
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.inherits("QMainWindow"):
            return widget
    return None


def show_confirmation_dialog(
    title: str,
    message: str,
    accept_button_text: str = "OK",
    reject_button_text: str = "Cancel",
) -> bool:
    """Show a confirmation dialog with custom sizing.

    Args:
        title: Dialog title
        message: Message text
        accept_button_text: Text for the accept/confirm button
        reject_button_text: Text for the reject/cancel button

    Returns:
        bool: True if accepted, False if rejected
    """
    parent = get_main_window()
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(QtCore.Qt.ApplicationModal)
    dialog.setMinimumWidth(400)  # Set minimum width
    dialog.setMinimumHeight(200)  # Set minimum height

    # Use a vertical layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)  # Add margins for better appearance

    # Add icon and message with proper wrapping
    message_layout = QtWidgets.QHBoxLayout()

    # Add warning icon
    icon_label = QtWidgets.QLabel()
    icon = QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.SP_MessageBoxWarning
    )
    icon_label.setPixmap(icon.pixmap(64, 64))
    message_layout.addWidget(icon_label)

    # Add message with word wrap
    message_label = QtWidgets.QLabel(message)
    message_label.setWordWrap(True)
    message_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
    message_layout.addWidget(message_label, 1)  # Give it stretch factor

    layout.addLayout(message_layout)

    # Add spacer
    layout.addSpacing(20)

    # Add buttons
    button_layout = QtWidgets.QHBoxLayout()
    button_layout.addStretch(1)  # Add stretch to push buttons to the right

    # Create custom buttons with appropriate styling
    accept_button = QtWidgets.QPushButton(accept_button_text)
    accept_button.setMinimumWidth(100)
    reject_button = QtWidgets.QPushButton(reject_button_text)
    reject_button.setMinimumWidth(100)

    button_layout.addWidget(accept_button)
    button_layout.addWidget(reject_button)

    layout.addLayout(button_layout)

    # Connect buttons
    accept_button.clicked.connect(dialog.accept)
    reject_button.clicked.connect(dialog.reject)

    # Execute dialog
    result = dialog.exec_()

    return result == QtWidgets.QDialog.Accepted


def show_message(message: str, title: str = "Message") -> None:
    """Show a properly sized message dialog.

    Args:
        message: The message to display
        title: Dialog title
    """
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle(title)
    dialog.setWindowModality(QtCore.Qt.WindowModal)
    dialog.setMinimumWidth(400)
    dialog.setMinimumHeight(150)

    # Use a vertical layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)

    # Message with icon
    message_layout = QtWidgets.QHBoxLayout()

    # Add info icon
    icon_label = QtWidgets.QLabel()
    icon = QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.SP_MessageBoxInformation
    )
    icon_label.setPixmap(icon.pixmap(48, 48))
    message_layout.addWidget(icon_label)

    # Message with word wrap
    message_label = QtWidgets.QLabel(message)
    message_label.setWordWrap(True)
    message_layout.addWidget(message_label, 1)

    layout.addLayout(message_layout)

    # Add spacer
    layout.addSpacing(20)

    # Add OK button
    button_layout = QtWidgets.QHBoxLayout()
    button_layout.addStretch(1)

    ok_button = QtWidgets.QPushButton("OK")
    ok_button.setMinimumWidth(100)
    button_layout.addWidget(ok_button)

    layout.addLayout(button_layout)

    # Connect button
    ok_button.clicked.connect(dialog.accept)

    # Make sure dialog is visible and on top
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

    # Execute dialog
    dialog.exec_()


def show_warning(message: str, title: str = "Warning") -> None:
    """Show a warning dialog with proper styling.

    Args:
        message: The warning message to display
        title: Dialog title
    """
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle(title)
    dialog.setWindowModality(QtCore.Qt.WindowModal)
    dialog.setMinimumWidth(450)
    dialog.setMinimumHeight(200)

    # Use a vertical layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)

    # Message with icon
    message_layout = QtWidgets.QHBoxLayout()

    # Add warning icon
    icon_label = QtWidgets.QLabel()
    icon = QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.SP_MessageBoxWarning
    )
    icon_label.setPixmap(icon.pixmap(64, 64))
    message_layout.addWidget(icon_label)

    # Message with word wrap
    message_label = QtWidgets.QLabel(message)
    message_label.setWordWrap(True)
    message_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
    message_layout.addWidget(message_label, 1)

    layout.addLayout(message_layout)

    # Add spacer
    layout.addSpacing(20)

    # Add OK button
    button_layout = QtWidgets.QHBoxLayout()
    button_layout.addStretch(1)

    ok_button = QtWidgets.QPushButton("OK")
    ok_button.setMinimumWidth(100)
    button_layout.addWidget(ok_button)

    layout.addLayout(button_layout)

    # Connect button
    ok_button.clicked.connect(dialog.accept)

    # Make sure dialog is visible and on top
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

    # Execute dialog
    dialog.exec_()


def show_error(message: str, title: str = "Error") -> None:
    """Show an error dialog with proper styling.

    Args:
        message: The error message to display
        title: Dialog title
    """
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle(title)
    dialog.setWindowModality(QtCore.Qt.WindowModal)
    dialog.setMinimumWidth(450)
    dialog.setMinimumHeight(200)

    # Use a vertical layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)

    # Message with icon
    message_layout = QtWidgets.QHBoxLayout()

    # Add error icon
    icon_label = QtWidgets.QLabel()
    icon = QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.SP_MessageBoxCritical
    )
    icon_label.setPixmap(icon.pixmap(64, 64))
    message_layout.addWidget(icon_label)

    # Message with word wrap
    message_label = QtWidgets.QLabel(message)
    message_label.setWordWrap(True)
    message_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
    message_layout.addWidget(message_label, 1)

    layout.addLayout(message_layout)

    # Add spacer
    layout.addSpacing(20)

    # Add OK button
    button_layout = QtWidgets.QHBoxLayout()
    button_layout.addStretch(1)

    ok_button = QtWidgets.QPushButton("OK")
    ok_button.setMinimumWidth(100)
    button_layout.addWidget(ok_button)

    layout.addLayout(button_layout)

    # Connect button
    ok_button.clicked.connect(dialog.accept)

    # Make sure dialog is visible and on top
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()

    # Execute dialog
    dialog.exec_() 


class SuccessDialog(QtWidgets.QDialog):
    def __init__(self, endpoint_results, parent=None):
        super().__init__(parent)
        self.endpoint_results = endpoint_results
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("Report Submitted Successfully")
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Success icon and title
        title_layout = QtWidgets.QHBoxLayout()
        icon_label = QtWidgets.QLabel("✅")
        icon_label.setStyleSheet("font-size: 24px;")
        title_layout.addWidget(icon_label)
        
        title_label = QtWidgets.QLabel("Report Submitted Successfully")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4CAF50;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # Add a separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout.addWidget(separator)
        
        # Endpoint results
        for endpoint, result in self.endpoint_results:
            try:
                success_info = endpoint.get_success_info(result)
                self.add_endpoint_result(layout, success_info)
            except Exception as e:
                # Fallback for endpoints that don't implement get_success_info
                self.add_fallback_result(layout, endpoint, result)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_button.setDefault(True)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        
    def add_endpoint_result(self, layout, success_info):
        """Add a result section for an endpoint"""
        # Create a group box for this endpoint
        group_box = QtWidgets.QGroupBox(success_info["title"])
        group_layout = QtWidgets.QVBoxLayout(group_box)
        group_layout.setSpacing(8)
        
        # Message
        message_label = QtWidgets.QLabel(success_info["message"])
        message_label.setWordWrap(True)
        group_layout.addWidget(message_label)
        
        # URL or file path with action button
        if success_info["url"]:
            url_layout = QtWidgets.QHBoxLayout()
            url_label = QtWidgets.QLabel("URL:")
            url_layout.addWidget(url_label)
            
            url_link = QtWidgets.QLabel(f'<a href="{success_info["url"]}">{success_info["url"]}</a>')
            url_link.setOpenExternalLinks(True)
            url_link.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
            url_layout.addWidget(url_link)
            url_layout.addStretch()
            
            open_button = QtWidgets.QPushButton("Open in Browser")
            url = success_info["url"]  # Capture the URL value
            open_button.clicked.connect(lambda checked, u=url: self.open_url(u))
            url_layout.addWidget(open_button)
            
            group_layout.addLayout(url_layout)
            
        elif success_info["file_path"]:
            file_layout = QtWidgets.QHBoxLayout()
            file_label = QtWidgets.QLabel("File:")
            file_layout.addWidget(file_label)
            
            file_path_label = QtWidgets.QLabel(success_info["file_path"])
            file_path_label.setWordWrap(True)
            file_layout.addWidget(file_path_label)
            file_layout.addStretch()
            
            if success_info["can_open"]:
                open_button = QtWidgets.QPushButton("Open File")
                file_path = success_info["file_path"]  # Capture the file path value
                open_button.clicked.connect(lambda checked, fp=file_path: self.open_file(fp))
                file_layout.addWidget(open_button)
                
                show_button = QtWidgets.QPushButton("Show in Folder")
                show_button.clicked.connect(lambda checked, fp=file_path: self.show_in_folder(fp))
                file_layout.addWidget(show_button)
            
            group_layout.addLayout(file_layout)
        
        layout.addWidget(group_box)
        
    def add_fallback_result(self, layout, endpoint, result):
        """Add a fallback result section for endpoints without get_success_info"""
        group_box = QtWidgets.QGroupBox(endpoint.__class__.__name__.replace("Endpoint", ""))
        group_layout = QtWidgets.QVBoxLayout(group_box)
        
        message_label = QtWidgets.QLabel(f"Successfully submitted to {endpoint.__class__.__name__.replace('Endpoint', '')}")
        group_layout.addWidget(message_label)
        
        if isinstance(result, str):
            if result.startswith(('http://', 'https://')):
                # It's a URL
                url_layout = QtWidgets.QHBoxLayout()
                url_label = QtWidgets.QLabel("URL:")
                url_layout.addWidget(url_label)
                
                url_link = QtWidgets.QLabel(f'<a href="{result}">{result}</a>')
                url_link.setOpenExternalLinks(True)
                url_link.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
                url_layout.addWidget(url_link)
                url_layout.addStretch()
                
                open_button = QtWidgets.QPushButton("Open in Browser")
                open_button.clicked.connect(lambda checked, u=result: self.open_url(u))
                url_layout.addWidget(open_button)
                
                group_layout.addLayout(url_layout)
            else:
                # It's a file path
                file_layout = QtWidgets.QHBoxLayout()
                file_label = QtWidgets.QLabel("File:")
                file_layout.addWidget(file_label)
                
                file_path_label = QtWidgets.QLabel(result)
                file_path_label.setWordWrap(True)
                file_layout.addWidget(file_path_label)
                file_layout.addStretch()
                
                open_button = QtWidgets.QPushButton("Open File")
                open_button.clicked.connect(lambda checked, fp=result: self.open_file(fp))
                file_layout.addWidget(open_button)
                
                show_button = QtWidgets.QPushButton("Show in Folder")
                show_button.clicked.connect(lambda checked, fp=result: self.show_in_folder(fp))
                file_layout.addWidget(show_button)
                
                group_layout.addLayout(file_layout)
        
        layout.addWidget(group_box)
        
    def open_url(self, url):
        """Open URL in default browser"""
        try:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not open URL: {e}")
            
    def open_file(self, file_path):
        """Open file with default application"""
        try:
            if sys.platform.startswith("win"):
                os.startfile(file_path)
            elif sys.platform == "darwin":
                from ayon_debugly.utils.subprocess_utils import run_silent_subprocess
                run_silent_subprocess(["open", file_path])
            else:
                from ayon_debugly.utils.subprocess_utils import run_silent_subprocess
                run_silent_subprocess(["xdg-open", file_path])
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not open file: {e}")
            
    def show_in_folder(self, file_path):
        """Show file in folder explorer"""
        try:
            folder_path = os.path.dirname(file_path)
            if sys.platform.startswith("win"):
                from ayon_debugly.utils.subprocess_utils import run_silent_subprocess
                run_silent_subprocess(["explorer", "/select,", file_path])
            elif sys.platform == "darwin":
                from ayon_debugly.utils.subprocess_utils import run_silent_subprocess
                run_silent_subprocess(["open", "-R", file_path])
            else:
                from ayon_debugly.utils.subprocess_utils import run_silent_subprocess
                run_silent_subprocess(["xdg-open", folder_path])
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not show in folder: {e}")


def show_success_dialog(endpoint_results, parent=None):
    """Show a success dialog with endpoint-specific information"""
    dialog = SuccessDialog(endpoint_results, parent)
    dialog.exec_() 