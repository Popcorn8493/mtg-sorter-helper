import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt  # Import the Qt core module

# Local application imports
from ui.main_window import MTGToolkitWindow
from core.constants import STYLESHEET

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    # Create the application instance AFTER setting the policy
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setFont(QFont("Segoe UI", 10))

    main_window = MTGToolkitWindow()
    main_window.show()

    sys.exit(app.exec())
