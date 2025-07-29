from qtpy import QtWidgets, QtCore, QtGui
import os

class AttachmentListWidget(QtWidgets.QWidget):
    attachmentRemoved = QtCore.Signal(str)  # emits the file path
    attachmentAdded = QtCore.Signal()  # emitted when attachment is added
    screenshotRemoved = QtCore.Signal(str)  # emits the screenshot file path
    screenshotAdded = QtCore.Signal(str)  # emits the screenshot file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.list_widget = QtWidgets.QListWidget(self)
        self.layout.addWidget(self.list_widget)
        self.attachments = []
        
        # Setup FontAwesome
        self._setup_fontawesome()

        # Set up list widget for simple list view
        self.list_widget.setViewMode(QtWidgets.QListView.ListMode)
        self.list_widget.setSpacing(2)
        self.list_widget.setResizeMode(QtWidgets.QListView.Adjust)
        self.list_widget.setMovement(QtWidgets.QListView.Static)
        
        # Apply consistent styling
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #2D2D2D;
                border: 1px solid #666666;
                border-radius: 4px;
                color: #E0E0E0;
                font-size: 11px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 3px;
                margin: 1px 0px;
            }
            QListWidget::item:hover {
                background-color: #3D3D3D;
            }
            QListWidget::item:selected {
                background-color: #4D4D4D;
            }
        """)
        
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemDoubleClicked.connect(self._open_attachment)

    def _setup_fontawesome(self):
        """Load FontAwesome 7 Free Solid font and store the family name."""
        import os
        font_path = os.path.join(os.path.dirname(__file__), "..", "..", "vendor", "fontawesome", "FontAwesome7Free-Solid-900.otf")
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

    def _get_fontawesome_icon(self, unicode_char):
        """Create a FontAwesome icon with white color"""
        if self.fontawesome_family:
            font = QtGui.QFont(self.fontawesome_family, 12)
            font.setWeight(QtGui.QFont.Black)
            return QtGui.QIcon(QtGui.QPixmap.fromImage(self._create_icon_image(unicode_char, font)))
        else:
            # Fallback to standard icon
            return self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogContentsView)

    def _create_icon_image(self, unicode_char, font):
        """Create an icon image from FontAwesome unicode character"""
        # Create a small pixmap for the icon
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(QtCore.Qt.transparent)
        
        painter = QtGui.QPainter(pixmap)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#FFFFFF"))  # White color
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, unicode_char)
        painter.end()
        
        return pixmap.toImage()

    def set_attachments(self, attachments):
        self.attachments = attachments[:]
        self.refresh()

    def add_attachment(self, path):
        if path not in self.attachments:
            self.attachments.append(path)
            self.refresh()
            self.attachmentAdded.emit()
            # Emit screenshot added signal if it's an image
            if self._is_image_file(path):
                self.screenshotAdded.emit(path)

    def remove_attachment(self, path):
        if path in self.attachments:
            self.attachments.remove(path)
            self.refresh()
            self.attachmentRemoved.emit(path)
            # Emit screenshot removed signal if it's an image
            if self._is_image_file(path):
                self.screenshotRemoved.emit(path)

    def refresh(self):
        self.list_widget.clear()
        for i, path in enumerate(self.attachments):
            filename = os.path.basename(path)
            item = QtWidgets.QListWidgetItem(filename)
            item.setToolTip(f"{filename}\n{path}")
            item.setData(QtCore.Qt.UserRole, path)  # Store full path for opening
            
            # Set appropriate icon based on file type
            if self._is_image_file(path):
                item.setIcon(self._get_fontawesome_icon("\uf1c5"))  # fa-file-image
            elif path.lower().endswith('.log'):
                item.setIcon(self._get_fontawesome_icon("\uf15c"))  # fa-file-alt
            elif path.lower().endswith('.txt'):
                item.setIcon(self._get_fontawesome_icon("\uf15c"))  # fa-file-alt
            else:
                item.setIcon(self._get_fontawesome_icon("\uf15b"))  # fa-file
            
            self.list_widget.addItem(item)
            
            # Create custom widget with remove button
            self._create_item_widget(item, filename, path)
        
        # Update parent widget title if it's a group box
        if hasattr(self.parent(), 'setTitle'):
            screenshot_count = sum(1 for path in self.attachments if self._is_image_file(path))
            total_count = len(self.attachments)
            if screenshot_count > 0:
                self.parent().setTitle(f"Attachments ({total_count} files, {screenshot_count} screenshots)")
            else:
                self.parent().setTitle(f"Attachments ({total_count} files)")
    
    def _is_image_file(self, path):
        """Check if the file is an image based on extension"""
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp'}
        return os.path.splitext(path.lower())[1] in image_extensions

    def _create_item_widget(self, item, filename, path):
        """Create a custom widget for each list item with remove button"""
        # Create container widget
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        
        # Create filename label (no icon to avoid double icons)
        filename_label = QtWidgets.QLabel(filename)
        filename_label.setStyleSheet("""
            QLabel {
                color: #E0E0E0;
                background: transparent;
                font-size: 11px;
                font-weight: 500;
            }
        """)
        layout.addWidget(filename_label, 1)  # Take remaining space
        
        # Create remove button
        remove_btn = QtWidgets.QPushButton("✕")
        remove_btn.setFixedSize(20, 20)
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #FF4444;
                border: none;
                font-weight: bold;
                font-size: 16px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                color: #FF6666;
            }
            QPushButton:pressed {
                color: #CC3333;
            }
        """)
        
        # Connect remove button to the correct attachment
        remove_btn.clicked.connect(lambda: self.remove_attachment(path))
        
        layout.addWidget(remove_btn)
        
        # Set the widget for the list item
        self.list_widget.setItemWidget(item, widget)



    def _open_attachment(self, item):
        """Open attachment in OS file explorer"""
        path = item.data(QtCore.Qt.UserRole)
        if path and os.path.exists(path):
            import subprocess
            import platform
            
            try:
                if platform.system() == "Windows":
                    subprocess.run(["explorer", "/select,", path], check=True)
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", "-R", path], check=True)
                else:  # Linux
                    subprocess.run(["xdg-open", os.path.dirname(path)], check=True)
            except subprocess.CalledProcessError as e:
                print(f"Failed to open file: {e}")

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self)
        
        # Add Open action
        open_action = menu.addAction("Open in Explorer")
        menu.addSeparator()
        remove_action = menu.addAction("Remove")
        
        action = menu.exec_(self.list_widget.mapToGlobal(pos))
        if action == open_action:
            self._open_attachment(item)
        elif action == remove_action:
            idx = self.list_widget.row(item)
            path = self.attachments[idx]
            self.remove_attachment(path)
