import os
from qtpy import QtWidgets, QtGui

ADDON_ROOT = os.path.dirname(os.path.abspath(__file__))

def take_screenshot(filepath):
    """Take a full screen screenshot and save to filepath"""
    app = QtWidgets.QApplication.instance()
    if not app:
        return False
    
    screen = app.primaryScreen()
    if not screen:
        return False
    
    screenshot = screen.grabWindow(0)
    return screenshot.save(filepath, "PNG")

def norm_path(path):
    """Normalize a path by expanding environment variables and user home directory.
    Args:
        path (str): The path to normalize.
    Returns:
        str: The normalized path.
    """
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path))).replace("\\", "/")

def ensure_dir(path):
    """Ensure a directory exists.
    Args:
        path (str): The path to ensure exists.
    Returns:
        str: The path to ensure exists.
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path
