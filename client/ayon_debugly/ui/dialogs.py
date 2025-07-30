"""Methods for showing dialogs that can be imported from AYON Debugly."""

from qtpy import QtWidgets, QtCore


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