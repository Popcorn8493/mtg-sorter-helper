import pathlib

class Config:
    """Holds application configuration."""
    APP_NAME = "MTGToolkit"
    ORG_NAME = "MTGToolkitOrg"
    SCRYFALL_API_CARD_ENDPOINT = "https://api.scryfall.com/cards/"
    SCRYFALL_API_SET_ENDPOINT = "https://api.scryfall.com/cards/search"
    APP_CACHE_DIR = pathlib.Path(f".{APP_NAME.lower()}_cache")
    CARD_CACHE_DIR = APP_CACHE_DIR / "card_data"
    IMAGE_CACHE_DIR = APP_CACHE_DIR / "image_data"
    SET_CACHE_DIR = APP_CACHE_DIR / "set_data"

# --- Setup Caching Directories ---
Config.APP_CACHE_DIR.mkdir(exist_ok=True)
Config.CARD_CACHE_DIR.mkdir(exist_ok=True)
Config.IMAGE_CACHE_DIR.mkdir(exist_ok=True)
Config.SET_CACHE_DIR.mkdir(exist_ok=True)

STYLESHEET = """
    QWidget {
        background-color: #2b2b2b;
        color: #f0f0f0;
        font-family: 'Segoe UI';
        font-size: 10pt;
    }
    QMainWindow, QTabWidget, QSplitter {
        background-color: #2b2b2b;
    }
    QTabWidget::pane { border: 1px solid #444; border-top: 0px; }
    QTabBar::tab { background: #3c3f41; border: 1px solid #444; border-bottom: none; padding: 8px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
    QTabBar::tab:selected { background: #2b2b2b; margin-bottom: -1px; }
    QTabBar::tab:!selected:hover { background: #4f5355; }
    QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 5px; margin-top: 1ex; }
    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; }
    QPushButton { background-color: #3c3f41; border: 1px solid #555; padding: 5px 10px; border-radius: 4px; }
    QPushButton:hover { background-color: #4f5355; }
    QPushButton:pressed { background-color: #2a2d2f; }
    QPushButton#AccentButton { background-color: #007acc; color: white; font-weight: bold; }
    QPushButton#AccentButton:hover { background-color: #008ae6; }
    QPushButton#BreadcrumbButton { background-color: transparent; border: none; color: #00aaff; text-align: left; padding: 2px; }
    QPushButton#BreadcrumbButton:hover { text-decoration: underline; }
    QLineEdit, QComboBox, QListWidget, QTreeWidget { background-color: #3c3f41; border: 1px solid #555; border-radius: 4px; padding: 3px; }
    QHeaderView::section { background-color: #3c3f41; border: 1px solid #555; padding: 4px; }
    QProgressBar { border: 1px solid #555; border-radius: 4px; text-align: center; }
    QProgressBar::chunk { background-color: #007acc; width: 10px; margin: 0.5px; }
    #qt_toolbar_navigation { background-color: #2b2b2b; }
    #qt_toolbar_navigation QToolButton { background-color: #3c3f41; border: 1px solid #555; border-radius: 2px; margin: 1px; }
    #qt_toolbar_navigation QToolButton:hover { background-color: #4f5355; }
    QLabel#CardImageLabel { background-color: #3c3f41; border: 1px solid #555; border-radius: 4px; }
"""
