import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

# Local application imports
from ui.main_window import MTGToolkitWindow
from core.constants import STYLESHEET

if __name__ == "__main__":
    # --- High-DPI Scaling ---
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setFont(QFont("Segoe UI", 10))

    main_window = MTGToolkitWindow()
    main_window.show()

    sys.exit(app.exec())
