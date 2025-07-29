from qtpy import QtWidgets, QtGui, QtCore
import sys
import tempfile

class ScreenMarquee(QtWidgets.QWidget):
    finished = QtCore.Signal(object)  # Emit the selection rectangle
    
    def __init__(self, parent=None):
        super().__init__(None)  # No parent to avoid focus issues
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint | 
            QtCore.Qt.FramelessWindowHint | 
            QtCore.Qt.Tool
            # Removed WindowDoesNotAcceptFocus - we need focus for mouse events
        )
        
        # Get screen geometry and set widget to cover all screens
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            screen_rect = screen.geometry()
            self.setGeometry(screen_rect)
        else:
            # Fallback to available geometry
            self.setGeometry(0, 0, 1920, 1080)
        
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.start = None
        self.end = None
        self.selection_rect = None
        
        # Track if we're actively selecting
        self.selecting = False
        
        print("ScreenMarquee created")

    def showEvent(self, event):
        super().showEvent(event)
        print("ScreenMarquee shown")
        # Force focus and raise
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        
        # Draw semi-transparent overlay
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 100))
        
        if self.start and self.end:
            # Clear the selection area
            selection = QtCore.QRect(self.start, self.end).normalized()
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
            painter.fillRect(selection, QtCore.Qt.transparent)
            
            # Draw selection border
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
            painter.setPen(QtGui.QPen(QtGui.QColor(224, 224, 224), 2, QtCore.Qt.SolidLine))
            painter.drawRect(selection)

    def mousePressEvent(self, event):
        print(f"Mouse press: {event.button()}, pos: {event.pos()}")
        if event.button() == QtCore.Qt.LeftButton:
            self.start = event.pos()
            self.end = self.start
            self.selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.start and self.selecting:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        print(f"Mouse release: {event.button()}, selecting: {self.selecting}")
        if event.button() == QtCore.Qt.LeftButton and self.selecting:
            self.end = event.pos()
            self.selection_rect = QtCore.QRect(self.start, self.end).normalized()
            print(f"Selection made: {self.selection_rect}")
            self.selecting = False
            self.close()
            self.finished.emit(self.selection_rect)

    def keyPressEvent(self, event):
        print(f"Key press: {event.key()}")
        if event.key() == QtCore.Qt.Key_Escape:
            print("Escape pressed - cancelling")
            self.selection_rect = None
            self.selecting = False
            self.close()
            self.finished.emit(None)

    def closeEvent(self, event):
        print("ScreenMarquee closing")
        super().closeEvent(event)

    @staticmethod
    def capture_to_file():
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        screen = QtWidgets.QApplication.primaryScreen()
        if not screen:
            QtWidgets.QMessageBox.critical(None, "Error", "No screen found.")
            return None
        
        # Show marquee overlay
        marquee = ScreenMarquee()
        marquee.show()
        
        # Use a local event loop to wait for the marquee to finish
        loop = QtCore.QEventLoop()
        marquee.finished.connect(loop.quit)
        loop.exec_()
        
        # After close, get selection
        if not marquee.selection_rect or marquee.selection_rect.isNull():
            return None
        
        # Grab screenshot
        screenshot = screen.grabWindow(0)
        cropped = screenshot.copy(marquee.selection_rect)
        tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        cropped.save(tmpfile.name, "PNG")
        return tmpfile.name 
