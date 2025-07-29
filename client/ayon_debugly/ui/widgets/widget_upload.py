from qtpy import QtWidgets, QtCore
import os

class UploadWidget(QtWidgets.QFrame):
    filesDropped = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameStyle(QtWidgets.QFrame.StyledPanel | QtWidgets.QFrame.Raised)
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #666666;
                border-radius: 6px;
                background: #2D2D2D;
                min-height: 80px;
                padding: 12px;
            }
            QFrame:hover {
                border-color: #888888;
                background: #3D3D3D;
            }
            QLabel {
                color: #E0E0E0;
                font-size: 13px;
                font-weight: 500;
                background: transparent;
            }
        """)
        self.label = QtWidgets.QLabel("📁 Drag and drop files here to attach\nor click Browse Files below", self)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)
        layout.addWidget(self.label)
        
        # Ensure the widget expands to fill its container
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if files:
                self.filesDropped.emit(files)
        event.acceptProposedAction()
