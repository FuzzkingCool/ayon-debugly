# -*- coding: utf-8 -*-
import getpass
import os
import tempfile
import traceback

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtGui import QFont

from ayon_debugly.collectors import get_collector_pairs
from ayon_debugly.debugly_app import DebuglyApp
from ayon_debugly.lib import log_display_name
from ayon_debugly.logger import log
from ayon_debugly.notion_issue_fields import (
    ISSUE_TYPE_OPTIONS,
    PIPELINE_RELEASE_OPTIONS,
    PROJECT_SELECT_STUDIO,
    default_pipeline_release_label,
    load_accessible_project_names,
)
from ayon_debugly.models.issue_form_model import IssueFormModel
from ayon_debugly.ui.widgets.attachment_list import AttachmentListWidget
from ayon_debugly.ui.widgets.widget_upload import UploadWidget
from ayon_debugly.ui.widgets.wysiwyg import WysiwygWidget
from ayon_debugly.ui.dialogs import show_success_dialog

# Default report window size and initial left/right pane ratio (~58% / 42%).
DEFAULT_REPORT_WIDTH = 1812
DEFAULT_REPORT_HEIGHT = 1090
SPLITTER_LEFT_RATIO = 0.58

MATERIAL_COLORS = {
    "primary": "#E0E0E0",
    "on_primary": "#1E1E1E",
    "surface": "#1E1E1E",
    "surface_container": "#2D2D2D",
    "on_surface": "#E0E0E0",
    "outline": "#666666",
    "border_radius_m": "4px",
    "padding_m": "6px",
    "padding_l": "8px",
}

# Denser input surfaces (line edits, combos) and dropdown popup
FORM_FIELD_BG = "#151515"
FORM_FIELD_BG_FOCUS = "#1E1E1E"
FORM_FIELD_BORDER = "#4A4A4A"
FORM_FIELD_BORDER_FOCUS = "#7A7A7A"
COMBO_POPUP_BG = "#121212"
COMBO_POPUP_BORDER = "#888888"
COMBO_POPUP_SELECTION = "#2A3A4A"

# Centralized hover help for the report form (left pane, status, accordions).
UI_TOOLTIPS = {
    "title": (
        "Short summary of the problem or request. "
        "This becomes the issue title in Notion and in any exported report."
    ),
    "issue_type": (
        "Pick the category that best matches your issue so it can be routed "
        "and triaged correctly."
    ),
    "project": (
        "Choose the AYON project this relates to, or Studio if it is "
        "not tied to a single project."
    ),
    "pipeline_release": (
        "Pipeline track: production, studio, or all releases. "
        "Helps reproduce environment-specific problems."
    ),
    "submit_wait": (
        "Wait until system information collection finishes (status shows Ready), "
        "then click to send the report."
    ),
    "submit_ready": (
        "Send this issue with the description, attachments, and collected "
        "system information to the configured endpoints."
    ),
    "status": (
        "Shows whether collectors have finished (Ready), are still running, "
        "or if submission is in progress."
    ),
    "progress": (
        "Progress while collectors run or while the report is being submitted."
    ),
    "accordion_screenshots": (
        "Capture screenshots of your screen or a region and attach them to "
        "this report. Open this section to use the capture buttons and preview."
    ),
    "accordion_attachments": (
        "Add files by drag-and-drop, or browse. These are bundled with your "
        "issue when you submit."
    ),
    "accordion_collected": (
        "Read-only snapshot of system and environment data gathered for this "
        "report. Expand sections to review what will be sent."
    ),
    "accordion_logs": (
        "Log files that are automatically included with the report. "
        "The list is informational; selection cannot be changed."
    ),
    "screenshot_full": (
        "Hide this window and capture the entire primary screen as a PNG, "
        "then attach it to the report."
    ),
    "screenshot_area": (
        "Minimize this window and draw a rectangle to capture only that region; "
        "the image is attached automatically."
    ),
    "browse_files": (
        "Open a file dialog to attach one or more files to this report."
    ),
    "attached_files_label": (
        "Files and screenshots that will be submitted with this issue. "
        "Remove items from the list if you do not want them included."
    ),
    "collected_scroll": (
        "Scroll to read each collected metadata section. "
        "This data is sent with your submission."
    ),
    "logs_list": (
        "Paths of log files included automatically. Hover an item for details."
    ),
    "section_header": (
        "Click to expand or collapse this collected data section. "
        "Content is read-only."
    ),
    "issue_description": (
        "Describe the problem, expected behavior, and steps to reproduce. "
        "Use the toolbar for headings and lists; this text is sent as the issue body."
    ),
}


class CollectorWorker(QtCore.QObject):
    """Worker class for running collectors in background threads"""
    finished = QtCore.Signal(str, dict)  # collector_name, data
    error = QtCore.Signal(str, str)  # collector_name, error_message
    
    def __init__(self, collector_name, collector_class):
        super().__init__()
        self.collector_name = collector_name
        self.collector_class = collector_class
    
    def run(self):
        """Run the collector in the background thread"""
        log.debug(f"Worker.run() called for {self.collector_name}")
        try:
            log.debug(f"Starting collector: {self.collector_name}")
            collector = self.collector_class()
            data = collector.collect()
            log.debug(f"Collector {self.collector_name} completed successfully")
            log.debug(f"Emitting finished signal for {self.collector_name}")
            self.finished.emit(self.collector_name, data)
        except Exception as e:
            log.error(f"Collector {self.collector_name} failed: {e}")
            log.error(traceback.format_exc())
            log.debug(f"Emitting error signal for {self.collector_name}")
            self.error.emit(self.collector_name, str(e))


class SubmissionWorker(QtCore.QObject):
    """Worker class for submitting reports in background threads"""
    finished = QtCore.Signal(list)  # results
    error = QtCore.Signal(str)  # error_message
    progress = QtCore.Signal(str, int, int)  # message, current, total
    
    def __init__(
        self,
        app,
        title,
        message_markdown,
        attachments,
        collected_metadata,
        log_files=None,
        issue_type=None,
        project=None,
        pipeline_release=None,
    ):
        super().__init__()
        self.app = app
        self.title = title
        self.message_markdown = message_markdown
        self.attachments = attachments
        self.collected_metadata = collected_metadata
        self.log_files = log_files or []
        self.issue_type = issue_type
        self.project = project
        self.pipeline_release = pipeline_release
    
    def run(self):
        """Submit the report in the background thread"""
        try:
            log.debug("Starting report submission...")
            self.progress.emit("Starting report submission...", 0, 100)
            
            # Debug: Log the collected metadata before submission
            log.debug(f"SubmissionWorker: Collected metadata keys: {list(self.collected_metadata.keys())}")
            
            results = self.app.submit_report(
                self.title,
                self.message_markdown,
                self.attachments,  # attachments parameter
                None,  # screenshot parameter
                self.log_files,  # log_files parameter
                self.collected_metadata,  # collected_data parameter
                progress_callback=self.progress.emit,  # Pass progress callback
                tags=[],
                issue_type=self.issue_type,
                project=self.project,
                pipeline_release=self.pipeline_release,
            )
            
            endpoint_failures = [
                res.get("error")
                for _, res in results
                if isinstance(res, dict) and res.get("failed")
            ]
            attachment_issues = any(
                isinstance(res, dict) and res.get("attachments_ok") is False
                for _, res in results
            )
            if endpoint_failures:
                log.warning(
                    "Report submitted with endpoint failure(s): %s",
                    "; ".join(endpoint_failures),
                )
                self.progress.emit(
                    "Report partially submitted — see warnings", 100, 100
                )
            elif attachment_issues:
                log.warning(
                    "Report submitted to %s endpoint(s) with attachment failures",
                    len(results),
                )
                self.progress.emit(
                    "Report submitted with attachment warnings", 100, 100
                )
            else:
                log.debug(f"Report submitted successfully to {len(results)} endpoint(s)")
                self.progress.emit("Report submitted successfully!", 100, 100)
            self.finished.emit(results)
        except Exception as e:
            log.error(f"Report submission failed: {e}")
            log.error(traceback.format_exc())
            self.error.emit(str(e))


class DebuglyMainWindow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_fontawesome()
        self.setWindowTitle("Debugly - Report an Issue")
        self._min_report_width = 1180
        self.setMinimumWidth(self._min_report_width)
        self.setMinimumHeight(600)
        ag = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = min(DEFAULT_REPORT_WIDTH, max(self._min_report_width, ag.width() - 40))
        h = min(DEFAULT_REPORT_HEIGHT, max(600, ag.height() - 40))
        self.resize(w, h)
        self._pending_splitter_layout = True
        self.attachment_widget = AttachmentListWidget(self)
        self.setup_ui()
        self.attachment_widget.setToolTip(UI_TOOLTIPS["attached_files_label"])
        self.form_model = IssueFormModel()
        self.app = DebuglyApp()
        self.collected_metadata = {}
        self.submitButton.clicked.connect(self.submit_report)
        self.apply_material_theme()
        self.attachment_widget.attachmentRemoved.connect(
            self.on_attachment_removed
        )
        
        # Connect attachment changes to header updates
        self.attachment_widget.attachmentAdded.connect(self._update_attachments_header)
        
        # Connect screenshot removal to carousel
        self.attachment_widget.screenshotRemoved.connect(
            self.screenshot_carousel.remove_screenshot
        )
        
        # Connect screenshot addition to carousel
        self.attachment_widget.screenshotAdded.connect(
            self.screenshot_carousel.add_screenshot
        )
        
        # Add fallback methods if carousel is not available
        if not hasattr(self.screenshot_carousel, 'add_screenshot'):
            self.screenshot_carousel.add_screenshot = lambda path: None
        if not hasattr(self.screenshot_carousel, 'remove_screenshot'):
            self.screenshot_carousel.remove_screenshot = lambda path: None
        
        # Initialize accordion with screenshots open by default
        self._initialize_accordion()
        
        # Thread management - store references to prevent garbage collection
        self.collector_workers = []
        self.collector_threads = []
        self.submission_worker = None
        self.submission_thread = None
        self._collectors_ready = False

        # Setup collectors in background after UI is shown
        QtCore.QTimer.singleShot(100, self._setup_collectors_async)
        
        log.debug("DebuglyMainWindow initialized")

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_pending_splitter_layout", False) and hasattr(
            self, "content_splitter"
        ):
            sw = self.content_splitter.width()
            if sw > 0:
                left = int(round(sw * SPLITTER_LEFT_RATIO))
                right = max(1, sw - left)
                self.content_splitter.setSizes([left, right])
                self._pending_splitter_layout = False

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Content area with email-like layout using QSplitter for resizable columns
        self.content_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        
        # Main editor panel (left)
        editor_widget = QtWidgets.QWidget()
        editor_panel = QtWidgets.QVBoxLayout(editor_widget)
        editor_panel.setSpacing(6)
        editor_panel.setContentsMargins(0, 0, 14, 0)

        # Issue title field
        title_label = QtWidgets.QLabel("Issue Title")
        title_label.setObjectName("BoldSectionLabel")
        title_label.setToolTip(UI_TOOLTIPS["title"])
        editor_panel.addWidget(title_label)

        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("Enter a brief title for your issue...")
        self.title_edit.setMinimumHeight(26)
        self.title_edit.setToolTip(UI_TOOLTIPS["title"])
        self.title_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {FORM_FIELD_BG};
                border: 1px solid {FORM_FIELD_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                color: #E0E0E0;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {FORM_FIELD_BORDER_FOCUS};
                background-color: {FORM_FIELD_BG_FOCUS};
            }}
        """)
        editor_panel.addWidget(self.title_edit)

        meta_style = f"""
            QComboBox {{
                background-color: {FORM_FIELD_BG};
                border: 1px solid {FORM_FIELD_BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                color: #E0E0E0;
                font-size: 12px;
                min-height: 24px;
            }}
            QComboBox:focus {{
                border-color: {FORM_FIELD_BORDER_FOCUS};
                background-color: {FORM_FIELD_BG_FOCUS};
            }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QComboBox QAbstractItemView {{
                background-color: {COMBO_POPUP_BG};
                color: #E0E0E0;
                border: 1px solid {COMBO_POPUP_BORDER};
                outline: 1px solid {COMBO_POPUP_BORDER};
                selection-background-color: {COMBO_POPUP_SELECTION};
                selection-color: #F0F0F0;
                padding: 2px;
            }}
        """

        meta_grid = QtWidgets.QGridLayout()
        meta_grid.setHorizontalSpacing(10)
        meta_grid.setVerticalSpacing(2)
        meta_grid.setColumnStretch(0, 1)
        meta_grid.setColumnStretch(1, 1)
        meta_grid.setColumnStretch(2, 1)

        it_label = QtWidgets.QLabel("Issue Type")
        it_label.setObjectName("BoldSectionLabel")
        it_label.setToolTip(UI_TOOLTIPS["issue_type"])
        pr_label = QtWidgets.QLabel("Project")
        pr_label.setObjectName("BoldSectionLabel")
        pr_label.setToolTip(UI_TOOLTIPS["project"])
        pl_label = QtWidgets.QLabel("Pipeline release")
        pl_label.setObjectName("BoldSectionLabel")
        pl_label.setToolTip(UI_TOOLTIPS["pipeline_release"])
        meta_grid.addWidget(it_label, 0, 0)
        meta_grid.addWidget(pr_label, 0, 1)
        meta_grid.addWidget(pl_label, 0, 2)

        self.issue_type_combo = QtWidgets.QComboBox()
        self.issue_type_combo.setStyleSheet(meta_style)
        self.issue_type_combo.setToolTip(UI_TOOLTIPS["issue_type"])
        for opt in ISSUE_TYPE_OPTIONS:
            self.issue_type_combo.addItem(opt, opt)

        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.setStyleSheet(meta_style)
        self.project_combo.setToolTip(UI_TOOLTIPS["project"])

        self.pipeline_combo = QtWidgets.QComboBox()
        self.pipeline_combo.setStyleSheet(meta_style)
        self.pipeline_combo.setToolTip(UI_TOOLTIPS["pipeline_release"])
        for opt in PIPELINE_RELEASE_OPTIONS:
            self.pipeline_combo.addItem(opt, opt)
        dpl = default_pipeline_release_label()
        di = self.pipeline_combo.findData(dpl)
        if di >= 0:
            self.pipeline_combo.setCurrentIndex(di)

        meta_grid.addWidget(self.issue_type_combo, 1, 0)
        meta_grid.addWidget(self.project_combo, 1, 1)
        meta_grid.addWidget(self.pipeline_combo, 1, 2)
        editor_panel.addLayout(meta_grid)

        # Issue Description label
        editor_label = QtWidgets.QLabel("Issue Description")
        editor_label.setObjectName("BoldSectionLabel")
        editor_label.setToolTip(UI_TOOLTIPS["issue_description"])
        editor_panel.addWidget(editor_label)

        self.wysiwyg = WysiwygWidget(self)
        self.wysiwyg.setMinimumWidth(420)
        self.wysiwyg.setMinimumHeight(220)
        editor_panel.addWidget(self.wysiwyg, 1)

        footer_rule = QtWidgets.QFrame()
        footer_rule.setFrameShape(QtWidgets.QFrame.HLine)
        footer_rule.setFrameShadow(QtWidgets.QFrame.Plain)
        footer_rule.setFixedHeight(1)
        footer_rule.setStyleSheet("QFrame { background-color: #444444; border: none; }")
        editor_panel.addWidget(footer_rule)

        # Submit button at bottom of editor panel
        self.submitButton = QtWidgets.QPushButton("Submit Report")
        self.submitButton.setMinimumHeight(30)
        self.submitButton.setMaximumHeight(30)
        self.submitButton.setEnabled(False)
        self.submitButton.setToolTip(UI_TOOLTIPS["submit_wait"])
        editor_panel.addWidget(self.submitButton)
        
        # Right side vertical accordion panel
        self.accordion_panel = self._create_vertical_accordion()
        
        # Add widgets to splitter
        self.content_splitter.addWidget(editor_widget)
        self.content_splitter.addWidget(self.accordion_panel)
        
        # Initial splitter sizes; refined on first showEvent to ~58/42 of inner width.
        self.content_splitter.setSizes([1040, 752])
        
        self.content_splitter.setMinimumWidth(self._min_report_width)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 1)
        
        # Add the splitter to main layout
        main_layout.addWidget(self.content_splitter, 1)

        # Status bar with divider and box
        status_container = QtWidgets.QWidget()
        status_container.setObjectName("StatusBar")
        status_layout = QtWidgets.QHBoxLayout(status_container)
        status_layout.setContentsMargins(8, 4, 8, 4)
        
        self.statusLabel = QtWidgets.QLabel("Initializing...")
        self.statusLabel.setToolTip(UI_TOOLTIPS["status"])
        status_layout.addWidget(self.statusLabel)

        # Add progress bar
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setVisible(False)  # Hidden by default
        self.progressBar.setMinimumWidth(200)
        self.progressBar.setMaximumWidth(300)
        self.progressBar.setToolTip(UI_TOOLTIPS["progress"])
        status_layout.addWidget(self.progressBar)
        
        main_layout.addWidget(status_container)

    def _setup_collectors_async(self):
        """Setup and run all collectors asynchronously to populate UI widgets and metadata"""
        self._collectors_ready = False
        self.submitButton.setEnabled(False)
        self.submitButton.setToolTip(UI_TOOLTIPS["submit_wait"])
        try:
            self.statusLabel.setText("Collecting system information...")
            self.progressBar.setVisible(True)
            self.progressBar.setMinimum(0)
            self.progressBar.setMaximum(0)  # Indeterminate progress
            self.progressBar.setValue(0)
            QtWidgets.QApplication.processEvents()
            
            # Get all collectors dynamically
            collector_pairs = get_collector_pairs()
            
            # Setup progress bar for total collectors
            total_collectors = len(collector_pairs)
            self.progressBar.setMaximum(total_collectors)
            self.progressBar.setValue(0)
            
            # Track completed collectors
            self.completed_collectors = 0
            self.collected_metadata = {}

            if total_collectors == 0:
                log.warning("No collectors registered; enabling submit without async collection")
                self._on_all_collectors_finished()
                return

            # Start all collectors in background threads
            for collector_name, collector_class in collector_pairs:
                self._start_collector_thread(collector_name, collector_class)
            
            log.debug(f"Started {total_collectors} collectors in background threads")
            
        except Exception as e:
            log.error(f"Failed to setup collectors: {e}")
            log.error(traceback.format_exc())
            self.progressBar.setVisible(False)
            self.statusLabel.setText(f"Error collecting data: {e}")
            self._collectors_ready = True
            self.submitButton.setEnabled(True)
            self.submitButton.setToolTip(UI_TOOLTIPS["submit_ready"])
            self._populate_project_combo()

    def _start_collector_thread(self, collector_name, collector_class):
        """Start a single collector in a background thread using canonical Qt threading"""
        # Create worker and thread
        worker = CollectorWorker(collector_name, collector_class)
        thread = QtCore.QThread()
        
        # Move worker to thread
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_collector_finished)
        worker.error.connect(self._on_collector_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        
        # Cleanup when thread finishes
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Store references to prevent garbage collection
        self.collector_workers.append(worker)
        self.collector_threads.append(thread)
        
        # Start the thread
        thread.start()
        
        log.debug(f"Started collector thread for {collector_name}")
        log.debug(f"Thread is running: {thread.isRunning()}")

    def _on_collector_finished(self, collector_name, data):
        """Handle collector completion"""
        log.debug(f"Received finished signal for collector: {collector_name}")
        self.collected_metadata[collector_name] = data
        self.completed_collectors += 1
        
        # Update progress
        self.progressBar.setValue(self.completed_collectors)
        self.statusLabel.setText(f"Collected {collector_name.lower()}... ({self.completed_collectors}/{self.progressBar.maximum()})")
        
        # Update UI if this is the logs collector
        if "Log" in collector_name:
            self._update_log_list_from_data(data)
        
        # Check if all collectors are done
        if self.completed_collectors >= self.progressBar.maximum():
            self._on_all_collectors_finished()

    def _on_collector_error(self, collector_name, error_message):
        """Handle collector error"""
        log.debug(f"Received error signal for collector: {collector_name}")
        self.completed_collectors += 1
        
        # Add error info to metadata
        self.collected_metadata[f"{collector_name}_error"] = error_message
        
        # Update progress
        self.progressBar.setValue(self.completed_collectors)
        self.statusLabel.setText(f"Error collecting {collector_name.lower()}... ({self.completed_collectors}/{self.progressBar.maximum()})")
        
        # Check if all collectors are done
        if self.completed_collectors >= self.progressBar.maximum():
            self._on_all_collectors_finished()

    def _on_all_collectors_finished(self):
        """Handle completion of all collectors"""
        # Complete progress bar
        self.progressBar.setVisible(False)
        self.statusLabel.setText("Ready")
        self._collectors_ready = True
        self.submitButton.setEnabled(True)
        self.submitButton.setToolTip(UI_TOOLTIPS["submit_ready"])

        self._populate_project_combo()

        # Update the collected info widget
        self._update_collected_info_widget()
        
        log.debug("All collectors completed successfully")

    def _populate_project_combo(self):
        """Fill Project with AYON user-accessible projects plus Studio (cross-project)."""
        prev = self.project_combo.currentData()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("Select project…", None)
        try:
            for name in load_accessible_project_names():
                self.project_combo.addItem(name, name)
        except Exception as e:
            log.warning(f"Could not load AYON project list: {e}")
        self.project_combo.addItem(PROJECT_SELECT_STUDIO, PROJECT_SELECT_STUDIO)
        self.project_combo.blockSignals(False)
        if prev:
            idx = self.project_combo.findData(prev)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)

    def _update_log_list_from_data(self, data):
        """Update log list widget from collected data"""
        try:
            log_files = data.get("log_files", [])
            
            self.log_model = QtGui.QStandardItemModel(self.logListView)
            for log_file in log_files:
                item = QtGui.QStandardItem(log_display_name(log_file["path"]))
                # Make logs non-editable - remove checkable property
                item.setData(log_file["path"], QtCore.Qt.UserRole)
                # Add tooltip with file info
                tooltip = f"Path: {log_file['path']}\nSize: {log_file['size']} bytes\nModified: {log_file['mtime']}"
                item.setToolTip(tooltip)
                self.log_model.appendRow(item)
            self.logListView.setModel(self.log_model)
            # Make the list view read-only
            self.logListView.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            log.debug(f"Loaded {len(log_files)} log files into log list")
        except Exception as e:
            log.error(f"Failed to update log list: {e}")
            log.error(traceback.format_exc())

    def _setup_collectors(self):
        """Legacy method - now calls async version"""
        self._setup_collectors_async()

    def _setup_metadata_collectors(self):
        """Legacy method - now handled by async version"""
        pass

    def _create_vertical_accordion(self):
        """Create the vertical accordion panel on the right side"""
        # Main container widget
        accordion_widget = QtWidgets.QWidget()
        accordion_layout = QtWidgets.QVBoxLayout(accordion_widget)
        accordion_layout.setContentsMargins(14, 0, 0, 0)
        accordion_layout.setSpacing(4)
        
        # Set minimum width for the accordion panel (resizable)
        accordion_widget.setMinimumWidth(360)
        
        # Create screenshot tools accordion section
        self.screenshot_accordion = self._create_screenshot_accordion()
        accordion_layout.addWidget(self.screenshot_accordion)
        
        # Create attachments accordion section
        self.attachments_accordion = self._create_attachments_accordion()
        accordion_layout.addWidget(self.attachments_accordion)
        
        # Create collected info accordion section
        self.collected_info_accordion = self._create_collected_info_accordion()
        accordion_layout.addWidget(self.collected_info_accordion)
        
        # Create logs accordion section (at bottom)
        self.logs_accordion = self._create_logs_accordion()
        accordion_layout.addWidget(self.logs_accordion)
        
        # Add stretch to push everything to the top
        accordion_layout.addStretch()
        
        return accordion_widget

    def _create_screenshot_accordion(self):
        """Create the screenshot tools accordion section"""
        # Main container widget
        accordion_widget = QtWidgets.QWidget()
        accordion_layout = QtWidgets.QVBoxLayout(accordion_widget)
        accordion_layout.setContentsMargins(0, 0, 0, 0)
        accordion_layout.setSpacing(0)
        
        # Accordion header button
        self.screenshot_header = QtWidgets.QPushButton()
        self.screenshot_header.setObjectName("AccordionHeader")
        self.screenshot_header.setFixedHeight(28)
        # Font Awesome camera icon (fa-camera)
        self.screenshot_header.setText("📷 Screenshots")
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)  # FontAwesome 7 requires Black weight
        self.screenshot_header.setFont(fa)
        self.screenshot_header.setToolTip(UI_TOOLTIPS["accordion_screenshots"])
        self.screenshot_header.clicked.connect(self._toggle_screenshot_panel)
        
        # Content panel (initially hidden - will be opened by _initialize_accordion)
        self.screenshot_content = QtWidgets.QWidget()
        self.screenshot_content.setObjectName("AccordionContent")
        self.screenshot_content.setVisible(False)  # Start closed, will be opened by initialization
        self.screenshot_content.setStyleSheet("background-color: #1E1E1E;")  # Match app background
        content_layout = QtWidgets.QVBoxLayout(self.screenshot_content)
        content_layout.setContentsMargins(8, 6, 8, 8)
        content_layout.setSpacing(6)

        # Screenshot carousel
        try:
            from ayon_debugly.ui.widgets.screenshot_carousel import ScreenshotCarousel
            self.screenshot_carousel = ScreenshotCarousel(self)
        except ImportError as e:
            log.warning(f"Could not import ScreenshotCarousel: {e}")
            # Fallback to simple label
            self.screenshot_carousel = QtWidgets.QLabel("Screenshot preview not available")
            self.screenshot_carousel.setAlignment(QtCore.Qt.AlignCenter)
            self.screenshot_carousel.setMinimumHeight(120)
            self.screenshot_carousel.setMaximumHeight(120)
            self.screenshot_carousel.setStyleSheet("border: 1px dashed #666666; background: #2D2D2D; color: #E0E0E0;")
        self.screenshot_carousel.setToolTip(UI_TOOLTIPS["accordion_screenshots"])
        content_layout.addWidget(self.screenshot_carousel)
        
        # Screenshot buttons below preview (smaller with icons)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(8)
        button_layout.addStretch()  # Push buttons to the right
        
        # Full Screen button with icon
        self.screenshotButton = QtWidgets.QPushButton("🖥️ Full Screen")
        self.screenshotButton.setFixedSize(120, 28)  # Increased width to prevent text cutoff
        self.screenshotButton.setToolTip(UI_TOOLTIPS["screenshot_full"])
        self.screenshotButton.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                color: #E0E0E0;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
            }
            QPushButton:pressed {
                background-color: #1D1D1D;
            }
        """)
        self.screenshotButton.clicked.connect(self.take_screenshot)
        
        # Select Area button with icon
        self.captureAreaButton = QtWidgets.QPushButton("✂️ Select Area")
        self.captureAreaButton.setFixedSize(120, 28)  # Increased width to prevent text cutoff
        self.captureAreaButton.setToolTip(UI_TOOLTIPS["screenshot_area"])
        self.captureAreaButton.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                color: #E0E0E0;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
            }
            QPushButton:pressed {
                background-color: #1D1D1D;
            }
        """)
        self.captureAreaButton.clicked.connect(self.capture_area)
        
        button_layout.addWidget(self.screenshotButton)
        button_layout.addWidget(self.captureAreaButton)
        content_layout.addLayout(button_layout)
        
        # Add widgets to accordion
        accordion_layout.addWidget(self.screenshot_header)
        accordion_layout.addWidget(self.screenshot_content)
        
        return accordion_widget

    def _create_attachments_accordion(self):
        """Create the collapsible attachments panel with accordion style"""
        # Main container widget
        accordion_widget = QtWidgets.QWidget()
        accordion_layout = QtWidgets.QVBoxLayout(accordion_widget)
        accordion_layout.setContentsMargins(0, 0, 0, 0)
        accordion_layout.setSpacing(0)
        
        # Accordion header button
        self.attachments_header = QtWidgets.QPushButton()
        self.attachments_header.setObjectName("AccordionHeader")
        self.attachments_header.setFixedHeight(32)
        self.attachments_header.setText("📎 Attachments")
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)
        self.attachments_header.setFont(fa)
        self.attachments_header.setToolTip(UI_TOOLTIPS["accordion_attachments"])
        self.attachments_header.clicked.connect(self._toggle_attachments_panel)
        
        # Create the attachments content widget
        self.attachments_content = QtWidgets.QWidget()
        self.attachments_content.setObjectName("AccordionContent")
        self.attachments_content.setVisible(True)
        self.attachments_content.setStyleSheet("background-color: #1E1E1E;")
        
        # Set minimum size for the entire attachments section
        self.attachments_content.setMinimumHeight(320)
        
        content_layout = QtWidgets.QVBoxLayout(self.attachments_content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(8)  # Natural spacing between elements
        
        # 1. Upload widget (drag & drop area)
        self.upload_widget = UploadWidget(self)
        self.upload_widget.filesDropped.connect(self.on_files_dropped)
        self.upload_widget.setMinimumHeight(100)
        content_layout.addWidget(self.upload_widget)
        
        # 2. Divider line
        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.HLine)
        divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        divider.setFixedHeight(1)
        divider.setStyleSheet("QFrame { background-color: #666666; }")
        content_layout.addWidget(divider)
        
        # 3. Attached Files label
        attachments_label = QtWidgets.QLabel("Attached Files")
        attachments_label.setAlignment(QtCore.Qt.AlignCenter)
        attachments_label.setFixedHeight(24)
        attachments_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 11px;
                font-weight: 500;
                background: transparent;
            }
        """)
        attachments_label.setToolTip(UI_TOOLTIPS["attached_files_label"])
        content_layout.addWidget(attachments_label)
        
        # 4. Attachment list widget
        self.attachment_widget.setMinimumHeight(180)  # Minimum height for 5+ lines
        content_layout.addWidget(self.attachment_widget)
        
        # 5. Browse button container
        browse_container = QtWidgets.QWidget()
        browse_container.setStyleSheet("background-color: transparent;")
        browse_layout = QtWidgets.QHBoxLayout(browse_container)
        browse_layout.setContentsMargins(0, 0, 0, 0)
        browse_layout.setSpacing(8)
        browse_layout.addStretch()  # Push button to the right
        
        self.attachmentsButton = QtWidgets.QPushButton("Browse Files")
        self.attachmentsButton.setFixedSize(110, 28)
        self.attachmentsButton.setToolTip(UI_TOOLTIPS["browse_files"])
        self.attachmentsButton.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                color: #E0E0E0;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
            }
            QPushButton:pressed {
                background-color: #1D1D1D;
            }
        """)
        self.attachmentsButton.clicked.connect(self.open_attachments)
        browse_layout.addWidget(self.attachmentsButton)
        
        content_layout.addWidget(browse_container)
        
        # Add widgets to accordion
        accordion_layout.addWidget(self.attachments_header)
        accordion_layout.addWidget(self.attachments_content)
        
        return accordion_widget

    def _create_logs_accordion(self):
        """Create the logs accordion section (default closed)"""
        # Main container widget
        accordion_widget = QtWidgets.QWidget()
        accordion_layout = QtWidgets.QVBoxLayout(accordion_widget)
        accordion_layout.setContentsMargins(0, 0, 0, 0)
        accordion_layout.setSpacing(0)
        
        # Accordion header button
        self.logs_header = QtWidgets.QPushButton()
        self.logs_header.setObjectName("AccordionHeader")
        self.logs_header.setFixedHeight(32)
        # Font Awesome file-alt icon (fa-file-alt) - more appropriate for logs
        self.logs_header.setText("📄 Log Files (Auto-included)")
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)  # FontAwesome 7 requires Black weight
        self.logs_header.setFont(fa)
        self.logs_header.setToolTip(UI_TOOLTIPS["accordion_logs"])
        self.logs_header.clicked.connect(self._toggle_logs_panel)
        
        # Content panel (initially hidden)
        self.logs_content = QtWidgets.QWidget()
        self.logs_content.setObjectName("AccordionContent")
        self.logs_content.setVisible(False)
        self.logs_content.setStyleSheet("background-color: #1E1E1E;")  # Match app background
        content_layout = QtWidgets.QVBoxLayout(self.logs_content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(8)
        
        # Info label about automatic inclusion
        info_label = QtWidgets.QLabel("Log files are automatically included in the report. You cannot modify this selection.")
        info_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 11px;
                font-style: italic;
                padding: 4px 0px;
            }
        """)
        info_label.setToolTip(UI_TOOLTIPS["accordion_logs"])
        content_layout.addWidget(info_label)

        # Log list view
        self.logListView = QtWidgets.QListView()
        self.logListView.setMinimumHeight(120)
        self.logListView.setMaximumHeight(200)
        self.logListView.setToolTip(UI_TOOLTIPS["logs_list"])
        content_layout.addWidget(self.logListView)
        
        # Add widgets to accordion
        accordion_layout.addWidget(self.logs_header)
        accordion_layout.addWidget(self.logs_content)
        
        return accordion_widget

    def _create_collected_info_accordion(self):
        """Create the collected info accordion section (default closed)"""
        # Main container widget
        accordion_widget = QtWidgets.QWidget()
        accordion_layout = QtWidgets.QVBoxLayout(accordion_widget)
        accordion_layout.setContentsMargins(0, 0, 0, 0)
        accordion_layout.setSpacing(0)
        
        # Accordion header button
        self.collected_info_header = QtWidgets.QPushButton()
        self.collected_info_header.setObjectName("AccordionHeader")
        self.collected_info_header.setFixedHeight(32)
        # Font Awesome info-circle icon (fa-info-circle)
        self.collected_info_header.setText("ℹ️ Collected Info")
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)  # FontAwesome 7 requires Black weight
        self.collected_info_header.setFont(fa)
        self.collected_info_header.setToolTip(UI_TOOLTIPS["accordion_collected"])
        self.collected_info_header.clicked.connect(self._toggle_collected_info_panel)
        
        # Content panel (initially hidden)
        self.collected_info_content = QtWidgets.QWidget()
        self.collected_info_content.setObjectName("AccordionContent")
        self.collected_info_content.setVisible(False)
        self.collected_info_content.setStyleSheet("background-color: #1E1E1E;")  # Match app background
        content_layout = QtWidgets.QVBoxLayout(self.collected_info_content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(8)
        
        # Scrollable area for metadata display
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(150)
        scroll_area.setMaximumHeight(300)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll_area.setToolTip(UI_TOOLTIPS["collected_scroll"])

        # Container widget for the metadata fields
        self.collected_info_container = QtWidgets.QWidget()
        self.collected_info_layout = QtWidgets.QVBoxLayout(self.collected_info_container)
        self.collected_info_layout.setSpacing(4)
        self.collected_info_layout.setContentsMargins(8, 8, 8, 8)  # Add padding
        
        # Placeholder text
        placeholder = QtWidgets.QLabel("Collecting system information...")
        placeholder.setAlignment(QtCore.Qt.AlignCenter)
        placeholder.setStyleSheet("color: #888888; font-style: italic;")
        self.collected_info_layout.addWidget(placeholder)
        
        scroll_area.setWidget(self.collected_info_container)
        content_layout.addWidget(scroll_area)
        
        # Add widgets to accordion
        accordion_layout.addWidget(self.collected_info_header)
        accordion_layout.addWidget(self.collected_info_content)
        
        return accordion_widget

    def _update_attachments_header(self):
        """Update the attachments header with current count and icon"""
        count = len(self.attachment_widget.attachments)
        if count == 0:
            text = "Attachments"
        elif count == 1:
            text = "1 Attachment"
        else:
            text = f"{count} Attachments"
        
        # Use Font Awesome paperclip icon
        self.attachments_header.setText(f"📎 {text}")
        
        # Ensure font weight is maintained
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)
        self.attachments_header.setFont(fa)

    def _toggle_screenshot_panel(self):
        """Toggle the visibility of the screenshot panel"""
        is_visible = self.screenshot_content.isVisible()
        
        if not is_visible:
            # Opening this panel - close all others first
            self._close_all_other_panels('screenshots')
            self.screenshot_content.setVisible(True)
            self.screenshot_header.setObjectName("AccordionHeaderExpanded")
        else:
            # Closing this panel
            self.screenshot_content.setVisible(False)
            self.screenshot_header.setObjectName("AccordionHeader")
        
        # Force style update
        self.screenshot_header.style().unpolish(self.screenshot_header)
        self.screenshot_header.style().polish(self.screenshot_header)
        
        # Ensure font weight is maintained
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)
        self.screenshot_header.setFont(fa)

    def _toggle_attachments_panel(self):
        """Toggle the visibility of the attachments panel"""
        is_visible = self.attachments_content.isVisible()
        
        if not is_visible:
            # Opening this panel - close all others first
            self._close_all_other_panels('attachments')
            self.attachments_content.setVisible(True)
            self.attachments_header.setObjectName("AccordionHeaderExpanded")
        else:
            # Closing this panel
            self.attachments_content.setVisible(False)
            self.attachments_header.setObjectName("AccordionHeader")
        
        # Force style update
        self.attachments_header.style().unpolish(self.attachments_header)
        self.attachments_header.style().polish(self.attachments_header)
        
        # Ensure font weight is maintained
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)
        self.attachments_header.setFont(fa)

    def _toggle_logs_panel(self):
        """Toggle the visibility of the logs panel"""
        is_visible = self.logs_content.isVisible()
        
        if not is_visible:
            # Opening this panel - close all others first
            self._close_all_other_panels('logs')
            self.logs_content.setVisible(True)
            self.logs_header.setObjectName("AccordionHeaderExpanded")
        else:
            # Closing this panel
            self.logs_content.setVisible(False)
            self.logs_header.setObjectName("AccordionHeader")
        
        # Force style update
        self.logs_header.style().unpolish(self.logs_header)
        self.logs_header.style().polish(self.logs_header)
        
        # Ensure font weight is maintained
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)
        self.logs_header.setFont(fa)

    def _toggle_collected_info_panel(self):
        """Toggle the visibility of the collected info panel"""
        is_visible = self.collected_info_content.isVisible()
        
        if not is_visible:
            # Opening this panel - close all others first
            self._close_all_other_panels('collected_info')
            self.collected_info_content.setVisible(True)
            self.collected_info_header.setObjectName("AccordionHeaderExpanded")
        else:
            # Closing this panel
            self.collected_info_content.setVisible(False)
            self.collected_info_header.setObjectName("AccordionHeader")
        
        # Force style update
        self.collected_info_header.style().unpolish(self.collected_info_header)
        self.collected_info_header.style().polish(self.collected_info_header)
        
        # Ensure font weight is maintained
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)
        self.collected_info_header.setFont(fa)
        
        # Update the header text to reflect current state
        if not is_visible:
            count = len([k for k in self.collected_metadata.keys() if k != "log_files"])
            self.collected_info_header.setText(f"ℹ️ Collected Info ({count} sections)")
        else:
            self.collected_info_header.setText("ℹ️ Collected Info")

    def _close_all_other_panels(self, current_panel):
        """Close all accordion panels except the specified one"""
        panels = {
            'screenshots': (self.screenshot_content, self.screenshot_header),
            'attachments': (self.attachments_content, self.attachments_header),
            'logs': (self.logs_content, self.logs_header),
            'collected_info': (self.collected_info_content, self.collected_info_header)
        }
        
        for panel_name, (content, header) in panels.items():
            if panel_name != current_panel:
                content.setVisible(False)
                header.setObjectName("AccordionHeader")
                # Force style update
                header.style().unpolish(header)
                header.style().polish(header)
                
                # Ensure font weight is maintained
                fa = QFont(self.fontawesome_family, 11)
                fa.setWeight(QtGui.QFont.Black)
                header.setFont(fa)



    def take_screenshot(self):
        # Hide the main window completely
        self.hide()
        QtWidgets.QApplication.processEvents()
        
        # Wait a moment for window to hide
        QtCore.QTimer.singleShot(200, self._take_screenshot_after_hide)
        
    def _take_screenshot_after_hide(self):
        """Take screenshot after window is hidden"""
        try:
            # Take screenshot
            screen = QtWidgets.QApplication.primaryScreen()
            pixmap = screen.grabWindow(0)
            
            # Generate unique filename
            new_name = self._generate_screenshot_name()
            
            # Save screenshot
            if pixmap.save(new_name, "PNG"):
                # Add to attachment list
                self.attachment_widget.add_attachment(new_name)
                
                self.statusLabel.setText(
                    f"Full screenshot taken and added: {os.path.basename(new_name)}"
                )
                log.debug(f"Full screenshot taken and added: {new_name}")
            else:
                self.statusLabel.setText("Failed to save screenshot")
                log.error("Failed to save screenshot")
                
        except Exception as e:
            self.statusLabel.setText(f"Failed to take screenshot: {str(e)}")
            log.error(f"Failed to take screenshot: {e}")
        finally:
            # Show window again
            self.show()
            self.activateWindow()

    def _generate_screenshot_name(self, base_name="issue"):
        """Generate a unique screenshot filename"""
        import os
        
        # Get title for naming
        title = self.title_edit.text().strip()
        if title:
            # Clean title for filename
            clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            clean_title = clean_title.replace(' ', '-')[:30]  # Limit length
            base_name = clean_title
        
        # Find next available number
        counter = 1
        while True:
            filename = f"{base_name}-screenshot-{counter:02d}.png"
            temp_path = os.path.join(tempfile.gettempdir(), filename)
            if not os.path.exists(temp_path):
                return temp_path
            counter += 1

    def _is_image_file(self, path):
        """Check if the file is an image based on extension"""
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
        return os.path.splitext(path.lower())[1] in image_extensions

    def capture_area(self):
        try:
            log.debug("Starting area capture...")
            # Minimize the main window (canonical approach)
            self.setWindowState(QtCore.Qt.WindowMinimized)
            QtWidgets.QApplication.processEvents()
            
            # Wait a moment for window to minimize, then show marquee
            QtCore.QTimer.singleShot(300, self._show_marquee)
            
        except Exception as e:
            log.debug(f"Error starting area capture: {e}")
            self.setWindowState(QtCore.Qt.WindowActive)
            self.show()
            self.activateWindow()
            QtWidgets.QMessageBox.critical(self, "Area Capture Failed", str(e))
            
    def _show_marquee(self):
        try:
            log.debug("Showing marquee...")
            from ayon_debugly.ui.widgets.screenshot_marquee import ScreenMarquee
            
            # Create and show marquee
            self.marquee = ScreenMarquee()
            self.marquee.finished.connect(self._on_marquee_finished)
            self.marquee.show()
            
            log.debug("Marquee should be visible now")
            
        except Exception as e:
            log.debug(f"Error showing marquee: {e}")
            self.show()
            QtWidgets.QMessageBox.critical(self, "Marquee Failed", str(e))

    def _on_marquee_finished(self, rect):
        """Handle screenshot area selection completion"""
        if rect and rect.isValid():
            try:
                # Minimize the app to prevent it from appearing in the screenshot
                self.setWindowState(QtCore.Qt.WindowMinimized)
                QtWidgets.QApplication.processEvents()
                
                # Get the screen where the marquee was positioned
                marquee_screen = getattr(self.marquee, 'target_screen', None)
                if not marquee_screen:
                    marquee_screen = QtWidgets.QApplication.screenAt(QtGui.QCursor.pos())
                if not marquee_screen:
                    marquee_screen = QtWidgets.QApplication.primaryScreen()
                
                # Use screen.grabWindow with coordinates relative to screen
                # This handles multi-monitor setups correctly
                screen_rect = marquee_screen.geometry()
                
                # The selection rectangle is already in the marquee widget's coordinate system
                # which is positioned at the screen's origin, so we can use it directly
                x = rect.x()
                y = rect.y()
                width = rect.width()
                height = rect.height()
                
                # Take screenshot using screen-specific coordinates
                cropped_pixmap = marquee_screen.grabWindow(0, x, y, width, height)
                
                log.debug("=== AYON-STYLE SCREENSHOT ===")
                log.debug(f"Marquee selection rect: {rect}")
                log.debug(f"Screen geometry: {screen_rect}")
                log.debug(f"Screen-relative coordinates: ({x}, {y}, {width}, {height})")
                log.debug(f"Using screen.grabWindow(0, {x}, {y}, {width}, {height})")
                log.debug(f"Cropped pixmap size: {cropped_pixmap.size()}")
                log.debug("=== END DEBUG INFO ===")
                
                # Generate unique filename
                new_name = self._generate_screenshot_name()
                
                # Save screenshot
                if cropped_pixmap.save(new_name, "PNG"):
                    # Add to attachment list
                    self.attachment_widget.add_attachment(new_name)
                    
                    # Update carousel to show the latest screenshot
                    if hasattr(self, 'screenshot_carousel'):
                        self.screenshot_carousel.add_screenshot(new_name)
                    
                    self.statusLabel.setText(f"Area screenshot added: {os.path.basename(new_name)}")
                    log.debug(f"Area screenshot taken and added: {new_name}")
                else:
                    self.statusLabel.setText("Failed to save area screenshot")
                    log.error("Failed to save area screenshot")
                    
            except Exception as e:
                self.statusLabel.setText(f"Failed to take area screenshot: {str(e)}")
                log.error(f"Failed to take area screenshot: {e}")
        else:
            self.statusLabel.setText("Screenshot area selection cancelled")
            
        # Restore the main window from minimized state
        self.setWindowState(QtCore.Qt.WindowActive)
        self.show()
        self.activateWindow()
        self.raise_()
        
        # Center the window if it's not in a reasonable position
        if self.x() < 100 or self.y() < 100:
            screen = QtWidgets.QApplication.primaryScreen()
            screen_rect = screen.geometry()
            window_rect = self.geometry()
            x = (screen_rect.width() - window_rect.width()) // 2
            y = (screen_rect.height() - window_rect.height()) // 2
            self.move(x, y)

    def submit_report(self):
        # Get title and message
        title = self.title_edit.text().strip()
        self.form_model.message_markdown = self.wysiwyg.toMarkdown().strip()
        self.form_model.message_html = self.wysiwyg.toHtml().strip()
        self.form_model.selected_logs = getattr(
            self, "log_model", None
        )  # update as needed
        
        # Get attachments from the attachment widget
        attachments = self.attachment_widget.attachments
        
        if not title:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Title",
                "Please enter a title for your issue.",
            )
            self.title_edit.setFocus()
            return
        
        if not self.form_model.message_markdown and not attachments:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Info",
                "Please enter a message or add an attachment.",
            )
            log.warning("Submission blocked: missing message and attachments")
            return

        if not getattr(self, "_collectors_ready", False):
            QtWidgets.QMessageBox.warning(
                self,
                "Still collecting",
                "Please wait until system information collection finishes "
                "(status shows Ready), then try again.",
            )
            return

        issue_type = (self.issue_type_combo.currentData() or "").strip()
        if not issue_type:
            issue_type = self.issue_type_combo.currentText().strip()
        if not issue_type:
            QtWidgets.QMessageBox.warning(
                self, "Issue Type", "Please select an issue type."
            )
            self.issue_type_combo.setFocus()
            return

        if self.project_combo.currentData() is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Project(s)",
                "Please select a project (or 'all releases').",
            )
            self.project_combo.setFocus()
            return
        project = str(self.project_combo.currentData()).strip()

        pipeline_release = self.pipeline_combo.currentData() or self.pipeline_combo.currentText()
        pipeline_release = str(pipeline_release).strip()
        if not pipeline_release:
            QtWidgets.QMessageBox.warning(
                self,
                "Pipeline release",
                "Please select a pipeline release.",
            )
            self.pipeline_combo.setFocus()
            return

        # Disable submit button to prevent double submission
        self.submitButton.setEnabled(False)

        # Start submission in background thread
        self._submit_report_async(
            title,
            attachments,
            issue_type=issue_type,
            project=project,
            pipeline_release=pipeline_release,
        )

    def _submit_report_async(
        self,
        title,
        attachments,
        issue_type=None,
        project=None,
        pipeline_release=None,
    ):
        """Submit report in background thread"""
        # Setup progress bar for submission
        self.progressBar.setVisible(True)
        self.progressBar.setMinimum(0)
        self.progressBar.setMaximum(0)  # Indeterminate progress
        self.progressBar.setValue(0)
        self.statusLabel.setText("Preparing report...")
        QtWidgets.QApplication.processEvents()

        try:
            fresh = self.app.issue_manager.collect_data()
            self.collected_metadata = fresh
            log_files_meta = fresh.get("log_files") or []
            if log_files_meta:
                self._update_log_list_from_data({"log_files": log_files_meta})
            self._update_collected_info_widget()
        except Exception as e:
            log.warning(
                "Submit-time collect_data failed; using cached metadata: %s", e
            )
            log.debug(traceback.format_exc())
        
        # Get log files from the log model
        log_files = []
        if hasattr(self, "log_model") and self.log_model:
            for row in range(self.log_model.rowCount()):
                item = self.log_model.item(row)
                if item and item.data(QtCore.Qt.UserRole):
                    log_files.append(item.data(QtCore.Qt.UserRole))
        
        # Start submission thread
        self._start_submission_thread(
            title,
            attachments,
            log_files,
            issue_type=issue_type,
            project=project,
            pipeline_release=pipeline_release,
        )

    def _start_submission_thread(
        self,
        title,
        attachments,
        log_files,
        issue_type=None,
        project=None,
        pipeline_release=None,
    ):
        """Start submission in background thread using canonical Qt threading"""
        # Create worker and thread
        worker = SubmissionWorker(
            self.app,
            title,
            self.form_model.message_markdown,
            attachments,
            self.collected_metadata,
            log_files,
            issue_type=issue_type,
            project=project,
            pipeline_release=pipeline_release,
        )
        thread = QtCore.QThread()
        
        # Move worker to thread
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_submission_finished)
        worker.error.connect(self._on_submission_error)
        worker.progress.connect(self._on_submission_progress)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        
        # Cleanup when thread finishes
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Store references to prevent garbage collection
        self.submission_worker = worker
        self.submission_thread = thread
        
        # Start the thread
        thread.start()

    def _on_submission_progress(self, message, current, total):
        """Handle submission progress updates"""
        self.statusLabel.setText(message)
        if total > 0:
            self.progressBar.setMaximum(total)
            self.progressBar.setValue(current)
        else:
            self.progressBar.setMaximum(0)  # Indeterminate progress
        QtWidgets.QApplication.processEvents()

    def _on_submission_finished(self, results):
        """Handle successful submission"""
        # Complete submission
        self.progressBar.setVisible(False)
        
        # Show success dialog with endpoint-specific information
        show_success_dialog(results, self)

        endpoint_failures = [
            res.get("error")
            for _, res in results
            if isinstance(res, dict) and res.get("failed")
        ]
        attachment_issues = any(
            isinstance(res, dict) and res.get("attachments_ok") is False
            for _, res in results
        )
        if endpoint_failures:
            self.statusLabel.setText(
                f"Partial submit: {len(endpoint_failures)} endpoint(s) failed"
            )
        elif attachment_issues:
            self.statusLabel.setText(
                f"Report submitted to {len(results)} endpoint(s) "
                "(attachments incomplete — deploy server addon or see Notion page)"
            )
        else:
            self.statusLabel.setText(f"Report submitted to {len(results)} endpoint(s)")
        log.debug(f"Report submitted to {len(results)} endpoint(s)")
        
        # Close the Debugly window after successful submission
        log.debug("Closing Debugly window after successful submission")
        self.close()

    def _on_submission_error(self, error_message):
        """Handle submission error"""
        self.progressBar.setVisible(False)
        self.submitButton.setEnabled(True)  # Re-enable submit button
        self.submitButton.setToolTip(UI_TOOLTIPS["submit_ready"])

        QtWidgets.QMessageBox.critical(self, "Submission Failed", error_message)
        self.statusLabel.setText(f"Error: {error_message}")
        log.error(f"Submission failed: {error_message}")
        log.error(traceback.format_exc())
        
        # Cleanup temporary files from UI components
        try:
            if hasattr(self, 'screenshot_widget'):
                self.screenshot_widget.cleanup()
        except Exception as e:
            log.warning(f"Failed to cleanup screenshot widget: {e}")
    def apply_material_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {MATERIAL_COLORS["surface"]};
                color: {MATERIAL_COLORS["on_surface"]};
                font-family: 'Segoe UI', 'Roboto', 'Arial', sans-serif;
                font-size: 11pt;
            }}
            QTextEdit, QPlainTextEdit {{
                font-size: 11pt;
            }}
            
            QLabel#BoldSectionLabel {{
                font-size: 12px;
                font-weight: 700;
                color: {MATERIAL_COLORS["primary"]};
                margin-bottom: 2px;
            }}
            
            QPushButton#AccordionHeader {{
                background-color: {MATERIAL_COLORS["surface_container"]};
                color: {MATERIAL_COLORS["on_surface"]};
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                padding: 8px 16px;
                font-weight: 500;
                text-align: left;
                font-size: 13px;
            }}
            
            QPushButton#AccordionHeader:hover {{
                background-color: #3D3D3D;
                border-color: #888888;
            }}
            
            QPushButton#AccordionHeaderExpanded {{
                background-color: #3D3D3D;
                color: {MATERIAL_COLORS["primary"]};
                border: 1px solid #888888;
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                padding: 8px 16px;
                font-weight: 500;
                text-align: left;
                font-size: 13px;
            }}
            
            QWidget#AccordionContent {{
                background-color: {MATERIAL_COLORS["surface_container"]};
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-top: none;
                border-radius: 0 0 {MATERIAL_COLORS["border_radius_m"]} {MATERIAL_COLORS["border_radius_m"]};
            }}
            
            QPushButton {{
                background-color: {MATERIAL_COLORS["surface_container"]};
                color: {MATERIAL_COLORS["on_surface"]};
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                padding: {MATERIAL_COLORS["padding_m"]} {MATERIAL_COLORS["padding_l"]};
                font-weight: 400;
                min-height: 24px;
                max-height: 28px;
            }}
            
            QPushButton:hover {{
                background-color: #3D3D3D;
                border-color: #888888;
            }}
            
            QPushButton:pressed {{
                background-color: #1D1D1D;
                border-color: #555555;
            }}
            
            QPushButton:disabled {{
                background-color: #1D1D1D;
                color: #666666;
                border-color: #444444;
            }}
            
            QTextEdit {{
                background-color: {MATERIAL_COLORS["surface_container"]};
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                padding: {MATERIAL_COLORS["padding_m"]};
                selection-background-color: #4D4D4D;
                color: {MATERIAL_COLORS["on_surface"]};
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 11px;
            }}
            QTextEdit#IssueDescriptionEditor,
            QTextEdit#IssueDescriptionEditor:hover {{
                background-color: #151515;
                border: 1px solid #4A4A4A;
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                padding: 6px;
                selection-background-color: #4D4D4D;
                color: #E0E0E0;
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: 12px;
            }}
            QTextEdit#IssueDescriptionEditor:focus {{
                background-color: #151515;
                border-color: #7A7A7A;
            }}
            
            QListView {{
                background-color: {MATERIAL_COLORS["surface_container"]};
                
            QProgressBar {{
                background-color: {MATERIAL_COLORS["surface_container"]};
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                text-align: center;
                color: {MATERIAL_COLORS["on_surface"]};
                font-size: 10px;
            }}
            
            QProgressBar::chunk {{
                background-color: {MATERIAL_COLORS["primary"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
            }}
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                selection-background-color: #4D4D4D;
                color: {MATERIAL_COLORS["on_surface"]};
                font-size: 12px;
                padding: 4px;
            }}
            
            QListView::item {{
                padding: 4px 8px;
                border-radius: 2px;
            }}
            
            QListView::item:hover {{
                background-color: #3D3D3D;
            }}
            
            QListView::item:selected {{
                background-color: #4D4D4D;
            }}
            
            QScrollArea {{
                background-color: {MATERIAL_COLORS["surface_container"]};
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
            }}
            
            QScrollBar:vertical {{
                background-color: {MATERIAL_COLORS["surface"]};
                width: 12px;
                border-radius: 6px;
            }}
            
            QScrollBar::handle:vertical {{
                background-color: {MATERIAL_COLORS["outline"]};
                border-radius: 6px;
                min-height: 20px;
            }}
            
            QScrollBar::handle:vertical:hover {{
                background-color: #888888;
            }}
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            
            QScrollBar:horizontal {{
                background-color: {MATERIAL_COLORS["surface"]};
                height: 12px;
                border-radius: 6px;
            }}
            
            QScrollBar::handle:horizontal {{
                background-color: {MATERIAL_COLORS["outline"]};
                border-radius: 6px;
                min-width: 20px;
            }}
            
            QScrollBar::handle:horizontal:hover {{
                background-color: #888888;
            }}
            
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            
            QSplitter::handle {{
                background-color: #444444;
                width: 1px;
                margin: 0px 12px;
            }}
            
            QSplitter::handle:hover {{
                background-color: #888888;
            }}
            
            QSplitter::handle:pressed {{
                background-color: {MATERIAL_COLORS["primary"]};
            }}
            
            QGroupBox {{
                font-weight: 400;
                border: 1px solid {MATERIAL_COLORS["outline"]};
                border-radius: {MATERIAL_COLORS["border_radius_m"]};
                margin-top: 6px;
                padding-top: 6px;
                color: {MATERIAL_COLORS["on_surface"]};
            }}
            
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 4px 0 4px;
                color: {MATERIAL_COLORS["primary"]};
                font-weight: 500;
            }}
            
            QFrame[frameShape="5"] {{
                color: {MATERIAL_COLORS["outline"]};
            }}
            
            QLabel {{
                color: {MATERIAL_COLORS["on_surface"]};
            }}
            
            QWidget#StatusBar {{
                background-color: #2D2D2D;
                border-top: 1px solid #444444;
                border-radius: 0px;
                color: #888888;
                font-size: 10px;
            }}
            
            QWidget#StatusBar QLabel {{
                color: #888888;
                font-size: 10px;
                background: transparent;
            }}
            
            QPushButton#SectionHeaderButton {{
                background-color: #3D3D3D;
                color: #E0E0E0;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: 500;
                text-align: left;
                font-size: 12px;
            }}
            
            QPushButton#SectionHeaderButton:hover {{
                background-color: #4D4D4D;
                border-color: #888888;
            }}
            
            QWidget#SectionContent {{
                background-color: transparent;
                border: none;
            }}
        """)
        # Set wysiwyg font size
        self.wysiwyg.setStyleSheet("font-size: 11pt;")

    def on_files_dropped(self, file_paths):
        """Handle files dropped onto the upload widget"""
        for file_path in file_paths:
            self.attachment_widget.add_attachment(file_path)
        self.statusLabel.setText(f"Added {len(file_paths)} file(s)")
        self._update_attachments_header()

    def on_attachment_removed(self, file_path):
        """Handle attachment removal"""
        self.statusLabel.setText(f"Removed attachment: {os.path.basename(file_path)}")
        self._update_attachments_header()

    def open_attachments(self):
        """Open file dialog to add attachments"""
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select Files to Attach", "", "All Files (*.*)"
        )
        if file_paths:
            self.on_files_dropped(file_paths)

    def _update_collected_info_widget(self):
        """Update the collected info widget with the metadata"""
        try:
            # Clear existing content
            for i in reversed(range(self.collected_info_layout.count())):
                child = self.collected_info_layout.itemAt(i).widget()
                if child:
                    child.deleteLater()
            
            if not self.collected_metadata:
                placeholder = QtWidgets.QLabel("No system information collected")
                placeholder.setAlignment(QtCore.Qt.AlignCenter)
                placeholder.setStyleSheet("color: #888888; font-style: italic;")
                self.collected_info_layout.addWidget(placeholder)
                return
            
            # Create sections for each metadata category
            for section_name, section_data in self.collected_metadata.items():
                if section_name == "log_files":
                    continue  # Skip log files as they're handled separately
                
                # Create collapsible section
                section_widget = self._create_collapsible_section(section_name, section_data)
                self.collected_info_layout.addWidget(section_widget)
            
            # Update the header to show data was collected
            count = len([k for k in self.collected_metadata.keys() if k != "log_files"])
            self.collected_info_header.setText(f"ℹ️ Collected Info ({count} sections)")
            
            log.debug(f"Updated collected info widget with {count} metadata sections")
        except Exception as e:
            log.error(f"Failed to update collected info widget: {e}")
            error_label = QtWidgets.QLabel(f"Error displaying metadata: {e}")
            error_label.setStyleSheet("color: #ff6b6b;")
            self.collected_info_layout.addWidget(error_label)

    def _create_collapsible_section(self, section_name, section_data):
        """Create a collapsible section for metadata"""
        # Main container widget
        section_widget = QtWidgets.QWidget()
        section_layout = QtWidgets.QVBoxLayout(section_widget)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(0)
        
        # Section header button (collapsible)
        header_button = QtWidgets.QPushButton()
        header_button.setObjectName("SectionHeaderButton")
        header_button.setFixedHeight(28)
        
        # Format section name for display
        display_name = section_name.replace("_", " ").title()
        header_button.setText(f"▼ {display_name}")
        header_button.setToolTip(UI_TOOLTIPS["section_header"])
        header_button.clicked.connect(lambda: self._toggle_section(header_button, content_widget))
        
        # Content panel (initially visible)
        content_widget = QtWidgets.QWidget()
        content_widget.setObjectName("SectionContent")
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setContentsMargins(8, 4, 8, 8)
        content_layout.setSpacing(4)
        
        # Create fields for this section
        self._add_metadata_fields(section_data, section_name, "", content_layout)
        
        # Add widgets to section
        section_layout.addWidget(header_button)
        section_layout.addWidget(content_widget)
        
        return section_widget

    def _toggle_section(self, header_button, content_widget):
        """Toggle the visibility of a collapsible section"""
        is_visible = content_widget.isVisible()
        
        if is_visible:
            content_widget.setVisible(False)
            # Change arrow to right (collapsed)
            current_text = header_button.text()
            header_button.setText(current_text.replace("▼", "▶"))
        else:
            content_widget.setVisible(True)
            # Change arrow to down (expanded)
            current_text = header_button.text()
            header_button.setText(current_text.replace("▶", "▼"))

    def _add_metadata_fields(self, data, section_name, parent_key="", layout=None):
        """Recursively add metadata fields to the layout"""
        if layout is None:
            layout = self.collected_info_layout
            
        if isinstance(data, dict):
            for key, value in data.items():
                full_key = f"{parent_key}.{key}" if parent_key else key
                
                if isinstance(value, dict):
                    # Create subsection header
                    subsection_header = QtWidgets.QLabel(key.replace("_", " ").title())
                    subsection_header.setStyleSheet("""
                        QLabel {
                            font-weight: 500;
                            color: #CCCCCC;
                            margin-top: 4px;
                            margin-bottom: 2px;
                        }
                    """)
                    layout.addWidget(subsection_header)
                    self._add_metadata_fields(value, section_name, full_key, layout)
                else:
                    self._add_field(full_key, value, layout)
        elif isinstance(data, list):
            # Handle lists (like environment variables, etc.)
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    self._add_metadata_fields(item, section_name, f"{parent_key}[{i}]", layout)
                else:
                    self._add_field(f"{parent_key}[{i}]", item, layout)
        else:
            self._add_field(parent_key or section_name, data, layout)

    def _add_field(self, key, value, layout=None):
        """Add a single field to the layout"""
        if layout is None:
            layout = self.collected_info_layout
            
        # Skip certain keys that are too verbose or not useful
        skip_keys = ['python_path', 'python_packages']
        if key in skip_keys:
            return
        
        # Create container widget
        field_widget = QtWidgets.QWidget()
        field_layout = QtWidgets.QHBoxLayout(field_widget)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(8)
        
        # Create label - preserve original case for environment variables
        if key.startswith("Environment Variables."):
            # For environment variables, use the original key name
            original_key = key.replace("Environment Variables.", "")
            label_text = original_key
        elif key.startswith("env."):
            # For environment variables, use the original key name
            original_key = key.replace("env.", "")
            label_text = original_key
        elif "." in key:
            # For nested keys, use the last part as the label
            label_text = key.split(".")[-1]
            # Clean up some common labels
            label_text = label_text.replace("_", " ").title()
            label_text = label_text.replace("Cwd", "Working Directory")
            label_text = label_text.replace("Uid", "User ID")
            label_text = label_text.replace("Gpu", "GPU")
            label_text = label_text.replace("Cpu", "CPU")
            label_text = label_text.replace("Ram", "RAM")
        else:
            label_text = key.replace("_", " ").title()
            # Clean up some common labels
            label_text = label_text.replace("Cwd", "Working Directory")
            label_text = label_text.replace("Uid", "User ID")
            label_text = label_text.replace("Gpu", "GPU")
            label_text = label_text.replace("Cpu", "CPU")
            label_text = label_text.replace("Ram", "RAM")
        
        label = QtWidgets.QLabel(label_text)
        label.setMinimumWidth(140)
        label.setMaximumWidth(180)
        label.setStyleSheet("""
            QLabel {
                color: #CCCCCC;
                font-size: 11px;
            }
        """)
        field_layout.addWidget(label)
        
        # Format the value
        if value is None:
            display_value = "N/A"
        elif isinstance(value, bool):
            display_value = "Yes" if value else "No"
        elif isinstance(value, (int, float)):
            # Format numbers nicely
            if isinstance(value, int) and value > 1000000:
                display_value = f"{value:,}"
            elif isinstance(value, float):
                display_value = f"{value:.2f}"
            else:
                display_value = str(value)
        else:
            display_value = str(value)
        
        # Create value display
        if isinstance(display_value, str) and len(display_value) > 80:
            # For long strings, use a text edit
            value_widget = QtWidgets.QTextEdit()
            value_widget.setPlainText(display_value)
            value_widget.setMaximumHeight(50)
            value_widget.setReadOnly(True)
            value_widget.setStyleSheet("""
                QTextEdit {
                    background-color: #2D2D2D;
                    border: 1px solid #666666;
                    border-radius: 4px;
                    padding: 4px;
                    color: #E0E0E0;
                    font-size: 11px;
                    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                }
            """)
        else:
            # For shorter values, use a label
            value_widget = QtWidgets.QLabel(display_value)
            value_widget.setWordWrap(True)
            value_widget.setStyleSheet("""
                QLabel {
                    color: #E0E0E0;
                    background-color: #2D2D2D;
                    border: 1px solid #666666;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                }
            """)
        
        field_layout.addWidget(value_widget, 1)  # 1 = stretch factor
        layout.addWidget(field_widget)

    def _setup_fontawesome(self):
        """Load FontAwesome 7 Free Solid font and store the family name."""
        font_path = os.path.join(os.path.dirname(__file__), "..", "vendor", "fontawesome", "FontAwesome7Free-Solid-900.otf")
        font_path = os.path.abspath(font_path)
        self.fontawesome_family = None
        if os.path.exists(font_path):
            font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                font_families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    self.fontawesome_family = font_families[0]
        if not self.fontawesome_family:
            self.fontawesome_family = "FontAwesome"

    def _initialize_accordion(self):
        """Initialize the accordion to have only the screenshots panel open by default."""
        # Close all panels first
        self.screenshot_content.setVisible(False)
        self.attachments_content.setVisible(False)
        self.collected_info_content.setVisible(False)
        self.logs_content.setVisible(False)
        
        # Reset all headers to collapsed state
        self.screenshot_header.setObjectName("AccordionHeader")
        self.attachments_header.setObjectName("AccordionHeader")
        self.collected_info_header.setObjectName("AccordionHeader")
        self.logs_header.setObjectName("AccordionHeader")
        
        # Force style updates
        for header in [self.screenshot_header, self.attachments_header, 
                      self.collected_info_header, self.logs_header]:
            header.style().unpolish(header)
            header.style().polish(header)
            
            # Ensure font weight is maintained
            fa = QFont(self.fontawesome_family, 11)
            fa.setWeight(QtGui.QFont.Black)
            header.setFont(fa)
        
        # Open screenshots panel by default
        self.screenshot_content.setVisible(True)
        self.screenshot_header.setObjectName("AccordionHeaderExpanded")
        self.screenshot_header.style().unpolish(self.screenshot_header)
        self.screenshot_header.style().polish(self.screenshot_header)

    def closeEvent(self, event):
        """Clean up temporary files when window is closed"""
        try:
            # Clean up collector threads
            if hasattr(self, 'collector_threads'):
                for thread in self.collector_threads:
                    if thread.isRunning():
                        thread.quit()
                        thread.wait(1000)
            
            # Clean up submission thread
            if hasattr(self, 'submission_thread') and self.submission_thread and self.submission_thread.isRunning():
                self.submission_thread.quit()
                self.submission_thread.wait(1000)
            
            if hasattr(self, 'screenshot_widget'):
                self.screenshot_widget.cleanup()
        except Exception as e:
            log.warning(f"Failed to cleanup during window close: {e}")
        super().closeEvent(event)


