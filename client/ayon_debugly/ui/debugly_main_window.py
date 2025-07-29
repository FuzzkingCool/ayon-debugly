import getpass
import os
import tempfile
import traceback
import json

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtGui import QFont

from ayon_debugly.collectors.collector_logs import CollectorLogs
from ayon_debugly.collectors.collector_env import CollectorEnv
from ayon_debugly.collectors.collector_os import CollectorOS
from ayon_debugly.collectors.collector_system_spec import CollectorSystemSpec
from ayon_debugly.collectors.collector_user import CollectorUser
from ayon_debugly.collectors.collector_production_apps import CollectorProductionApps
from ayon_debugly.debugly_app import DebuglyApp
from ayon_debugly.debugly_issue import DebuglyIssue
from ayon_debugly.logger import log
from ayon_debugly.models.issue_form_model import IssueFormModel
from ayon_debugly.ui.widgets.attachment_list import AttachmentListWidget
from ayon_debugly.ui.widgets.widget_upload import UploadWidget
from ayon_debugly.ui.widgets.wysiwyg import WysiwygWidget

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
        self._setup_collectors()
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
        
        self.statusLabel = QtWidgets.QLabel("Ready")
        status_layout.addWidget(self.statusLabel)
        
        main_layout.addWidget(status_container)

    def _setup_collectors(self):
        """Setup and run all collectors to populate UI widgets and metadata"""
        try:
            # Setup logs collector to populate logs widget
            self._setup_log_list()
            
            # Setup other collectors for metadata
            self._setup_metadata_collectors()
            
        except Exception as e:
            log.error(f"Failed to setup collectors: {e}")
            log.error(traceback.format_exc())

    def _setup_metadata_collectors(self):
        """Run all collectors except logs and combine into metadata JSON"""
        collectors = [
            CollectorEnv(),
            CollectorOS(),
            CollectorSystemSpec(),
            CollectorUser(),
            CollectorProductionApps(settings=getattr(self.app, 'settings', None))
        ]
        
        for collector in collectors:
            try:
                collector_name = collector.__class__.__name__
                log.info(f"Running collector: {collector_name}")
                data = collector.collect()
                self.collected_metadata.update(data)
                log.info(f"Collector {collector_name} completed successfully")
            except Exception as e:
                log.error(f"Collector {collector_name} failed: {e}")
                log.error(traceback.format_exc())
                # Add error info to metadata
                self.collected_metadata[f"{collector_name}_error"] = str(e)
        
        # Update the collected info widget
        self._update_collected_info_widget()

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
        
        # Content panel (initially visible)
        self.screenshot_content = QtWidgets.QWidget()
        self.screenshot_content.setObjectName("AccordionContent")
        self.screenshot_content.setVisible(True)
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
        
        # Full Screen button with icon
        self.screenshotButton = QtWidgets.QPushButton("🖥️ Full Screen")
        self.screenshotButton.setFixedSize(110, 28)
        self.screenshotButton.setToolTip("Take a screenshot of the entire screen")
        self.screenshotButton.clicked.connect(self.take_screenshot)
        
        # Select Area button with icon
        self.captureAreaButton = QtWidgets.QPushButton("✂️ Select Area")
        self.captureAreaButton.setFixedSize(110, 28)
        self.captureAreaButton.setToolTip("Select a specific area to screenshot")
        self.captureAreaButton.clicked.connect(self.capture_area)
        
        button_layout.addWidget(self.screenshotButton)
        button_layout.addWidget(self.captureAreaButton)
        button_layout.addStretch()  # Push buttons to the left
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
        # Font Awesome paperclip icon (fa-paperclip)
        self.attachments_header.setText("📎 Attachments")
        fa = QFont(self.fontawesome_family, 11)
        fa.setWeight(QtGui.QFont.Black)  # FontAwesome 7 requires Black weight
        self.attachments_header.setFont(fa)
        self.attachments_header.clicked.connect(self._toggle_attachments_panel)
        
        # Content panel (initially visible)
        self.attachments_content = QtWidgets.QWidget()
        self.attachments_content.setObjectName("AccordionContent")
        self.attachments_content.setVisible(True)
        self.attachments_content.setStyleSheet("background-color: #1E1E1E;")  # Match app background
        content_layout = QtWidgets.QVBoxLayout(self.attachments_content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(12)  # Increased spacing between elements
        
        # Drag and drop section at top
        self.upload_widget = UploadWidget(self)
        self.upload_widget.filesDropped.connect(self.on_files_dropped)
        self.upload_widget.setMinimumHeight(100)
        self.upload_widget.setMaximumHeight(120)
        content_layout.addWidget(self.upload_widget)
        
        # Divider line
        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.HLine)
        divider.setFrameShadow(QtWidgets.QFrame.Sunken)
        divider.setStyleSheet("QFrame { color: #666666; margin: 4px 0px; }")
        content_layout.addWidget(divider)
        
        # Attached Files label
        attachments_label = QtWidgets.QLabel("Attached Files")
        attachments_label.setAlignment(QtCore.Qt.AlignCenter)
        attachments_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 11px;
                font-weight: 500;
                background: transparent;
                padding: 4px 0px;
            }
        """)
        content_layout.addWidget(attachments_label)
        
        # Attachment list widget with proper sizing
        self.attachment_widget.setMinimumHeight(120)
        self.attachment_widget.setMaximumHeight(200)
        content_layout.addWidget(self.attachment_widget)
        
        # Browse button (right aligned) - moved outside the list widget
        browse_container = QtWidgets.QWidget()
        browse_layout = QtWidgets.QHBoxLayout(browse_container)
        browse_layout.setContentsMargins(0, 4, 0, 0)  # Add top margin
        browse_layout.setSpacing(0)
        browse_layout.addStretch()  # Push button to the right
        self.attachmentsButton = QtWidgets.QPushButton("Browse Files")
        self.attachmentsButton.setFixedHeight(28)
        self.attachmentsButton.setMaximumWidth(100)
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
        self.logs_header.setText("📄 Log Files")
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
        self.screenshot_content.setVisible(not is_visible)
        
        # Update header appearance based on state
        if not is_visible:
            self.screenshot_header.setObjectName("AccordionHeaderExpanded")
        else:
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
        self.attachments_content.setVisible(not is_visible)
        
        # Update header appearance based on state
        if not is_visible:
            self.attachments_header.setObjectName("AccordionHeaderExpanded")
        else:
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
        self.logs_content.setVisible(not is_visible)
        
        # Update header appearance based on state
        if not is_visible:
            self.logs_header.setObjectName("AccordionHeaderExpanded")
        else:
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
        self.collected_info_content.setVisible(not is_visible)
        
        # Update header appearance based on state
        if not is_visible:
            self.collected_info_header.setObjectName("AccordionHeaderExpanded")
        else:
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

    def _setup_log_list(self):
        """Setup logs collector and populate logs widget"""
        try:
            # Use the app's settings for the logs collector
            logs_collector = CollectorLogs(settings=getattr(self.app, 'settings', None))
            log_files_data = logs_collector.collect()
            log_files = log_files_data.get("log_files", [])
            
            self.log_model = QtGui.QStandardItemModel(self.logListView)
            for log_file in log_files:
                item = QtGui.QStandardItem(os.path.basename(log_file["path"]))
                item.setCheckable(True)
                item.setCheckState(QtCore.Qt.Checked)
                item.setData(log_file["path"], QtCore.Qt.UserRole)
                # Add tooltip with file info
                tooltip = f"Path: {log_file['path']}\nSize: {log_file['size']} bytes\nModified: {log_file['mtime']}"
                item.setToolTip(tooltip)
                self.log_model.appendRow(item)
            self.logListView.setModel(self.log_model)
            log.info(f"Loaded {len(log_files)} log files into log list")
        except Exception as e:
            log.error(f"Failed to setup log list: {e}")
            log.error(traceback.format_exc())

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
        import tempfile
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
            print("Starting area capture...")
            # Hide main window temporarily
            self.hide()
            QtWidgets.QApplication.processEvents()
            
            # Wait a moment for window to hide, then show marquee
            QtCore.QTimer.singleShot(200, self._show_marquee)
            
        except Exception as e:
            self.show()  # Make sure to show window again
            log.error(f"Failed to capture area: {e}")
            log.error(traceback.format_exc())
            QtWidgets.QMessageBox.critical(self, "Capture Area Failed", str(e))

    def _show_marquee(self):
        try:
            print("Showing marquee...")
            from ayon_debugly.ui.widgets.screenshot_marquee import ScreenMarquee
            
            # Create and show marquee
            self.marquee = ScreenMarquee()
            self.marquee.finished.connect(self._on_marquee_finished)
            self.marquee.show()
            
            print("Marquee should be visible now")
            
        except Exception as e:
            print(f"Error showing marquee: {e}")
            self.show()
            QtWidgets.QMessageBox.critical(self, "Marquee Failed", str(e))

    def _on_marquee_finished(self, rect):
        """Handle screenshot area selection completion"""
        # Always show the main window again
        self.show()
        self.activateWindow()
        
        if rect and rect.isValid():
            try:
                # Take screenshot of selected area
                screen = QtWidgets.QApplication.primaryScreen()
                pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
                
                # Generate unique filename
                new_name = self._generate_screenshot_name()
                
                # Save screenshot
                if pixmap.save(new_name, "PNG"):
                    # Add to attachment list
                    self.attachment_widget.add_attachment(new_name)
                    
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
        try:
            user = getpass.getuser()
            
            # Update form model with title
            self.form_model.title = title
            
            # Create metadata file for submission
            metadata_file = None
            if self.collected_metadata:
                try:
                    # Create temporary metadata file
                    metadata_fd, metadata_file = tempfile.mkstemp(suffix=".json", prefix="debugly_metadata_")
                    os.close(metadata_fd)
                    with open(metadata_file, 'w', encoding='utf-8') as f:
                        json.dump(self.collected_metadata, f, indent=2, default=str)
                    log.info(f"Created metadata file: {metadata_file}")
                except Exception as e:
                    log.error(f"Failed to create metadata file: {e}")
                    metadata_file = None
            
            # Add metadata file to attachments if created
            all_attachments = attachments.copy()
            if metadata_file:
                all_attachments.append(metadata_file)
            
            # Create issue object
            issue = DebuglyIssue(
                title=title,
                user_message=self.form_model.message_markdown,
                collected_data=self.collected_metadata,
                attachments=all_attachments
            )

            log.info(f"Issue: {issue}")

            dest = self.app.submit_report(
                title,
                self.form_model.message_markdown,
                getattr(self.form_model, "selected_logs", []),
                None,  # No separate screenshot path
                all_attachments,
            )
            QtWidgets.QMessageBox.information(
                self, "Report Submitted", f"Report saved to: {dest}"
            )
            if hasattr(self, "statusLabel"):
                self.statusLabel.setText(f"Report saved to: {dest}")
            log.info(f"Report submitted: {dest}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Submission Failed", str(e))
            if hasattr(self, "statusLabel"):
                self.statusLabel.setText(f"Error: {e}")
            log.error(f"Submission failed: {e}")
            log.error(traceback.format_exc())
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
                
                # Create section header
                section_header = QtWidgets.QLabel(section_name.replace("_", " ").title())
                section_header.setObjectName("SectionHeader")
                section_header.setStyleSheet("""
                    QLabel {
                        font-weight: bold;
                        color: #E0E0E0;
                        background-color: #3D3D3D;
                        padding: 4px 8px;
                        border-radius: 4px;
                        margin-top: 8px;
                        margin-bottom: 4px;
                    }
                """)
                self.collected_info_layout.addWidget(section_header)
                
                # Create fields for this section
                self._add_metadata_fields(section_data, section_name)
            
            # Update the header to show data was collected
            count = len([k for k in self.collected_metadata.keys() if k != "log_files"])
            self.collected_info_header.setText(f"ℹ️ Collected Info ({count} sections)")
            
            log.info(f"Updated collected info widget with {count} metadata sections")
        except Exception as e:
            log.error(f"Failed to update collected info widget: {e}")
            error_label = QtWidgets.QLabel(f"Error displaying metadata: {e}")
            error_label.setStyleSheet("color: #ff6b6b;")
            self.collected_info_layout.addWidget(error_label)

    def _add_metadata_fields(self, data, section_name, parent_key=""):
        """Recursively add metadata fields to the layout"""
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
                    self.collected_info_layout.addWidget(subsection_header)
                    self._add_metadata_fields(value, section_name, full_key)
                else:
                    self._add_field(full_key, value)
        elif isinstance(data, list):
            # Handle lists (like environment variables, etc.)
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    self._add_metadata_fields(item, section_name, f"{parent_key}[{i}]")
                else:
                    self._add_field(f"{parent_key}[{i}]", item)
        else:
            self._add_field(parent_key or section_name, data)

    def _add_field(self, key, value):
        """Add a single field to the layout"""
        # Skip certain keys that are too verbose or not useful
        skip_keys = ['python_path', 'python_packages']
        if key in skip_keys:
            return
        
        # Create container widget
        field_widget = QtWidgets.QWidget()
        field_layout = QtWidgets.QHBoxLayout(field_widget)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(8)
        
        # Create label
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
        self.collected_info_layout.addWidget(field_widget)

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


