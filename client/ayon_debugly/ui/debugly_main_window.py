# -*- coding: utf-8 -*-
import getpass
import os
import tempfile
import traceback

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtGui import QFont

from ayon_debugly.collectors import get_collector_pairs
from ayon_debugly.collectors.collector_logs import CollectorLogs
from ayon_debugly.debugly_app import DebuglyApp
from ayon_debugly.logger import log
from ayon_debugly.models.issue_form_model import IssueFormModel
from ayon_debugly.ui.widgets.attachment_list import AttachmentListWidget
from ayon_debugly.ui.widgets.widget_upload import UploadWidget
from ayon_debugly.ui.widgets.wysiwyg import WysiwygWidget
from ayon_debugly.ui.dialogs import show_success_dialog

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
            log.info(f"Starting collector: {self.collector_name}")
            collector = self.collector_class()
            data = collector.collect()
            log.info(f"Collector {self.collector_name} completed successfully")
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
    
    def __init__(self, app, title, message_markdown, attachments, collected_metadata, log_files=None):
        super().__init__()
        self.app = app
        self.title = title
        self.message_markdown = message_markdown
        self.attachments = attachments
        self.collected_metadata = collected_metadata
        self.log_files = log_files or []
    
    def run(self):
        """Submit the report in the background thread"""
        try:
            log.info("Starting report submission...")
            
            # Debug: Log the collected metadata before submission
            log.debug(f"SubmissionWorker: Collected metadata keys: {list(self.collected_metadata.keys())}")
            
            results = self.app.submit_report(
                self.title,
                self.message_markdown,
                self.attachments,  # attachments parameter
                None,  # screenshot parameter
                self.log_files,  # log_files parameter
                self.collected_metadata,  # collected_data parameter
            )
            
            log.info(f"Report submitted successfully to {len(results)} endpoint(s)")
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
        # Email-like window dimensions
        self.setMinimumWidth(1200)
        self.setMinimumHeight(600)
        self.resize(1400, 700)  # Default size for email-like experience
        self.attachment_widget = AttachmentListWidget(self)
        self.setup_ui()
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
        
        # Setup collectors in background after UI is shown
        QtCore.QTimer.singleShot(100, self._setup_collectors_async)
        
        log.info("DebuglyMainWindow initialized")

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # Content area with email-like layout using QSplitter for resizable columns
        self.content_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        
        # Main editor panel (left)
        editor_widget = QtWidgets.QWidget()
        editor_panel = QtWidgets.QVBoxLayout(editor_widget)
        editor_panel.setSpacing(8)
        
        # Issue title field
        title_label = QtWidgets.QLabel("Issue Title")
        title_label.setObjectName("BoldSectionLabel")
        editor_panel.addWidget(title_label)
        
        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("Enter a brief title for your issue...")
        self.title_edit.setMinimumHeight(32)
        self.title_edit.setStyleSheet("""
            QLineEdit {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 8px 12px;
                color: #E0E0E0;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #888888;
                background-color: #3D3D3D;
            }
        """)
        editor_panel.addWidget(self.title_edit)
        
        # Issue Description label
        editor_label = QtWidgets.QLabel("Issue Description")
        editor_label.setObjectName("BoldSectionLabel")
        editor_panel.addWidget(editor_label)
        
        self.wysiwyg = WysiwygWidget(self)
        self.wysiwyg.setMinimumWidth(500)
        self.wysiwyg.setMinimumHeight(400)
        editor_panel.addWidget(self.wysiwyg, 1)
        
        # Submit button at bottom of editor panel
        self.submitButton = QtWidgets.QPushButton("Submit Report")
        self.submitButton.setMinimumHeight(32)
        self.submitButton.setMaximumHeight(32)
        editor_panel.addWidget(self.submitButton)
        
        # Right side vertical accordion panel
        self.accordion_panel = self._create_vertical_accordion()
        
        # Add widgets to splitter
        self.content_splitter.addWidget(editor_widget)
        self.content_splitter.addWidget(self.accordion_panel)
        
        # Set initial sizes (editor gets more space, attachments column wider)
        self.content_splitter.setSizes([600, 600])
        
        # Set minimum sizes
        self.content_splitter.setMinimumWidth(1200)
        self.content_splitter.setChildrenCollapsible(False)
        
        # Add the splitter to main layout
        main_layout.addWidget(self.content_splitter, 1)

        # Status bar with divider and box
        status_container = QtWidgets.QWidget()
        status_container.setObjectName("StatusBar")
        status_layout = QtWidgets.QHBoxLayout(status_container)
        status_layout.setContentsMargins(8, 4, 8, 4)
        
        self.statusLabel = QtWidgets.QLabel("Initializing...")
        status_layout.addWidget(self.statusLabel)
        
        # Add progress bar
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setVisible(False)  # Hidden by default
        self.progressBar.setMinimumWidth(200)
        self.progressBar.setMaximumWidth(300)
        status_layout.addWidget(self.progressBar)
        
        main_layout.addWidget(status_container)

    def _setup_collectors_async(self):
        """Setup and run all collectors asynchronously to populate UI widgets and metadata"""
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
            
            # Start all collectors in background threads
            for collector_name, collector_class in collector_pairs:
                self._start_collector_thread(collector_name, collector_class)
            
            log.info(f"Started {total_collectors} collectors in background threads")
            
        except Exception as e:
            log.error(f"Failed to setup collectors: {e}")
            log.error(traceback.format_exc())
            self.progressBar.setVisible(False)
            self.statusLabel.setText(f"Error collecting data: {e}")

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
        
        # Update the collected info widget
        self._update_collected_info_widget()
        
        log.info("All collectors completed successfully")

    def _update_log_list_from_data(self, data):
        """Update log list widget from collected data"""
        try:
            log_files = data.get("log_files", [])
            
            self.log_model = QtGui.QStandardItemModel(self.logListView)
            for log_file in log_files:
                item = QtGui.QStandardItem(os.path.basename(log_file["path"]))
                # Make logs non-editable - remove checkable property
                item.setData(log_file["path"], QtCore.Qt.UserRole)
                # Add tooltip with file info
                tooltip = f"Path: {log_file['path']}\nSize: {log_file['size']} bytes\nModified: {log_file['mtime']}"
                item.setToolTip(tooltip)
                self.log_model.appendRow(item)
            self.logListView.setModel(self.log_model)
            # Make the list view read-only
            self.logListView.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            log.info(f"Loaded {len(log_files)} log files into log list")
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
        accordion_layout.setContentsMargins(0, 0, 0, 0)
        accordion_layout.setSpacing(4)
        
        # Set minimum width for the accordion panel (resizable)
        accordion_widget.setMinimumWidth(400)
        
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
        self.screenshot_header.setFixedHeight(32)
        # Font Awesome camera icon (fa-camera)
        self.screenshot_header.setText("📷 Screenshots")
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)  # FontAwesome 7 requires Black weight
        self.screenshot_header.setFont(fa)
        self.screenshot_header.clicked.connect(self._toggle_screenshot_panel)
        
        # Content panel (initially hidden - will be opened by _initialize_accordion)
        self.screenshot_content = QtWidgets.QWidget()
        self.screenshot_content.setObjectName("AccordionContent")
        self.screenshot_content.setVisible(False)  # Start closed, will be opened by initialization
        self.screenshot_content.setStyleSheet("background-color: #1E1E1E;")  # Match app background
        content_layout = QtWidgets.QVBoxLayout(self.screenshot_content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(8)
        
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
        content_layout.addWidget(self.screenshot_carousel)
        
        # Screenshot buttons below preview (smaller with icons)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(8)
        button_layout.addStretch()  # Push buttons to the right
        
        # Full Screen button with icon
        self.screenshotButton = QtWidgets.QPushButton("🖥️ Full Screen")
        self.screenshotButton.setFixedSize(120, 28)  # Increased width to prevent text cutoff
        self.screenshotButton.setToolTip("Take a screenshot of the entire screen")
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
        self.captureAreaButton.setToolTip("Select a specific area to screenshot")
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
        self.attachments_header.clicked.connect(self._toggle_attachments_panel)
        
        # Create the attachments content widget
        self.attachments_content = QtWidgets.QWidget()
        self.attachments_content.setObjectName("AccordionContent")
        self.attachments_content.setVisible(True)
        self.attachments_content.setStyleSheet("background-color: #1E1E1E;")
        
        # Set minimum size for the entire attachments section
        self.attachments_content.setMinimumHeight(450)  # Minimum height to prevent layout breaking
        
        content_layout = QtWidgets.QVBoxLayout(self.attachments_content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(8)  # Natural spacing between elements
        
        # 1. Upload widget (drag & drop area)
        self.upload_widget = UploadWidget(self)
        self.upload_widget.filesDropped.connect(self.on_files_dropped)
        self.upload_widget.setMinimumHeight(120)  # Minimum height, can grow
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
        content_layout.addWidget(info_label)
        
        # Log list view
        self.logListView = QtWidgets.QListView()
        self.logListView.setMinimumHeight(120)
        self.logListView.setMaximumHeight(200)
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
                log.info(f"Full screenshot taken and added: {new_name}")
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
                
                log.info("=== AYON-STYLE SCREENSHOT ===")
                log.info(f"Marquee selection rect: {rect}")
                log.info(f"Screen geometry: {screen_rect}")
                log.info(f"Screen-relative coordinates: ({x}, {y}, {width}, {height})")
                log.info(f"Using screen.grabWindow(0, {x}, {y}, {width}, {height})")
                log.info(f"Cropped pixmap size: {cropped_pixmap.size()}")
                log.info("=== END DEBUG INFO ===")
                
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
                    log.info(f"Area screenshot taken and added: {new_name}")
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
        
        # Disable submit button to prevent double submission
        self.submitButton.setEnabled(False)
        
        # Start submission in background thread
        self._submit_report_async(title, attachments)

    def _submit_report_async(self, title, attachments):
        """Submit report in background thread"""
        # Setup progress bar for submission
        self.progressBar.setVisible(True)
        self.progressBar.setMinimum(0)
        self.progressBar.setMaximum(0)  # Indeterminate progress
        self.progressBar.setValue(0)
        self.statusLabel.setText("Preparing report...")
        QtWidgets.QApplication.processEvents()
        
        # Get log files from the log model
        log_files = []
        if hasattr(self, "log_model") and self.log_model:
            for row in range(self.log_model.rowCount()):
                item = self.log_model.item(row)
                if item and item.data(QtCore.Qt.UserRole):
                    log_files.append(item.data(QtCore.Qt.UserRole))
        
        # Start submission thread
        self._start_submission_thread(title, attachments, log_files)

    def _start_submission_thread(self, title, attachments, log_files):
        """Start submission in background thread using canonical Qt threading"""
        # Create worker and thread
        worker = SubmissionWorker(
            self.app,
            title,
            self.form_model.message_markdown,
            attachments,
            self.collected_metadata,
            log_files
        )
        thread = QtCore.QThread()
        
        # Move worker to thread
        worker.moveToThread(thread)
        
        # Connect signals
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_submission_finished)
        worker.error.connect(self._on_submission_error)
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

    def _on_submission_finished(self, results):
        """Handle successful submission"""
        # Complete submission
        self.progressBar.setVisible(False)
        
        # Show success dialog with endpoint-specific information
        show_success_dialog(results, self)
        
        self.statusLabel.setText(f"Report submitted to {len(results)} endpoint(s)")
        log.info(f"Report submitted to {len(results)} endpoint(s)")
        
        # Close the Debugly window after successful submission
        log.info("Closing Debugly window after successful submission")
        self.close()

    def _on_submission_error(self, error_message):
        """Handle submission error"""
        self.progressBar.setVisible(False)
        self.submitButton.setEnabled(True)  # Re-enable submit button
        
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
                font-size: 14px;
                font-weight: 700;
                color: {MATERIAL_COLORS["primary"]};
                margin-bottom: 4px;
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
            
            log.info(f"Updated collected info widget with {count} metadata sections")
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


