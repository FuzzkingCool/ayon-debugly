# -*- coding: utf-8 -*-
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


def log_display_name(log_path):
    """Display name for a collected log file in the UI."""
    norm = os.path.normpath(log_path)
    parts = norm.split(os.sep)
    if "sessions" in parts:
        return os.path.join("sessions", os.path.basename(log_path))
    return os.path.basename(log_path)


def log_redacted_archive_name(log_path):
    """Relative archive name for a redacted log under logs/ in issue zips."""
    rel = log_display_name(log_path)
    name, ext = os.path.splitext(rel)
    return f"{name}_redacted{ext}"
