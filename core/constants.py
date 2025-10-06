# core/constants.py

import pathlib
import os


def _get_global_cache_dir():
    app_name = "MTGToolkit"

    try:
        if os.name == "nt":
            appdata = os.environ.get("APPDATA")
            if appdata:
                cache_base = pathlib.Path(appdata)
            else:
                cache_base = pathlib.Path.home() / "AppData" / "Roaming"
        elif os.name == "posix":
            xdg_cache = os.environ.get("XDG_CACHE_HOME")
            if xdg_cache:
                cache_base = pathlib.Path(xdg_cache)
            else:
                cache_base = pathlib.Path.home() / ".cache"
        else:
            cache_base = pathlib.Path.home()

        cache_base = cache_base.resolve()
        return cache_base / f"{app_name}_cache"
    except Exception as e:
        print(f"Warning: Failed to determine cache directory: {e}")
        return pathlib.Path.home() / f"{app_name}_cache"


class Config:
    APP_NAME = "MTGToolkit"
    ORG_NAME = "MTGToolkitOrg"
    SCRYFALL_API_CARD_ENDPOINT = "https://api.scryfall.com/cards/"
    SCRYFALL_API_SET_ENDPOINT = "https://api.scryfall.com/cards/search"

    APP_CACHE_DIR = _get_global_cache_dir()
    CARD_CACHE_DIR = APP_CACHE_DIR / "card_data"
    IMAGE_CACHE_DIR = APP_CACHE_DIR / "image_data"
    SET_CACHE_DIR = APP_CACHE_DIR / "set_data"

    MAX_CACHE_SIZE_MB = 500
    MAX_IMAGE_CACHE_SIZE_MB = 200
    AUTO_SAVE_INTERVAL = 300000
    PROJECT_EXTENSION = "mtgproj"
    MAX_RECENT_PROJECTS = 5

    DEFAULT_THEME = "dark"


def _setup_global_cache():
    import shutil

    try:
        Config.APP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Config.CARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Config.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Config.SET_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        print(f"Cache directories created successfully at: " f"{Config.APP_CACHE_DIR}")
    except Exception as e:
        print(f"Error creating cache directories: {e}")
        try:
            fallback_cache = pathlib.Path.home() / "MTGToolkit_cache"
            fallback_cache.mkdir(parents=True, exist_ok=True)
            Config.APP_CACHE_DIR = fallback_cache
            Config.CARD_CACHE_DIR = fallback_cache / "card_data"
            Config.IMAGE_CACHE_DIR = fallback_cache / "image_data"
            Config.SET_CACHE_DIR = fallback_cache / "set_data"

            Config.CARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            Config.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            Config.SET_CACHE_DIR.mkdir(parents=True, exist_ok=True)

            print(f"Using fallback cache directory: " f"{fallback_cache}")
        except Exception as fallback_error:
            print(
                f"Critical error: Could not create any cache "
                f"directories: {fallback_error}"
            )
            raise

    old_cache_dir = pathlib.Path(".mtgtoolkit_cache")
    if old_cache_dir.exists() and old_cache_dir.is_dir():
        print(f"Found old cache directory: {old_cache_dir}")
        print(f"Migrating to global cache: " f"{Config.APP_CACHE_DIR}")

        try:
            for old_subdir, new_subdir in [
                ("card_data", Config.CARD_CACHE_DIR),
                ("image_data", Config.IMAGE_CACHE_DIR),
                ("set_data", Config.SET_CACHE_DIR),
            ]:
                old_path = old_cache_dir / old_subdir
                if old_path.exists():
                    print(f"Migrating {old_subdir} from {old_path} " f"to {new_subdir}")
                    files_copied = 0
                    for file_path in old_path.glob("*"):
                        if file_path.is_file():
                            new_file_path = new_subdir / file_path.name
                            if not new_file_path.exists():
                                shutil.copy2(file_path, new_file_path)
                                files_copied += 1
                            else:
                                print(f"Skipped {file_path.name} " f"(already exists)")
                    print(f"Copied {files_copied} files from {old_subdir}")
                else:
                    print(f"No {old_subdir} directory found in old cache")

            print(
                f"Cache migration completed. You can safely " f"delete: {old_cache_dir}"
            )

        except Exception as e:
            print(f"Cache migration failed: {e}")
            print(
                "Old cache will remain, but new cache location "
                "will be used going forward."
            )

    print(f"Global cache location: {Config.APP_CACHE_DIR}")


def verify_cache_accessibility():
    try:
        test_file = Config.APP_CACHE_DIR / "test_write.tmp"
        test_file.write_text("test")
        test_file.unlink()

        test_file = Config.CARD_CACHE_DIR / "test_write.tmp"
        test_file.write_text("test")
        test_file.unlink()

        test_file = Config.IMAGE_CACHE_DIR / "test_write.tmp"
        test_file.write_text("test")
        test_file.unlink()

        test_file = Config.SET_CACHE_DIR / "test_write.tmp"
        test_file.write_text("test")
        test_file.unlink()

        print("Cache directories are accessible and writable")
        return True
    except Exception as e:
        print(f"Warning: Cache directories may not be fully " f"accessible: {e}")
        return False


_setup_global_cache()
verify_cache_accessibility()


class ThemeManager:

    @staticmethod
    def get_dark_stylesheet():
        return """
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
        QTabBar::tab { 
            background: #3c3f41; 
            border: 1px solid #444; 
            border-bottom: none; 
            padding: 8px 20px; 
            border-top-left-radius: 4px; 
            border-top-right-radius: 4px; 
        }
        QTabBar::tab:selected { background: #2b2b2b; margin-bottom: -1px; }
        QTabBar::tab:!selected:hover { background: #4f5355; }
        QGroupBox { 
            font-weight: bold; 
            border: 1px solid #444; 
            border-radius: 5px; 
            margin-top: 1ex; 
        }
        QGroupBox::title { 
            subcontrol-origin: margin; 
            subcontrol-position: top left; 
            padding: 0 3px; 
        }
        QPushButton { 
            background-color: #3c3f41; 
            border: 1px solid #555; 
            padding: 5px 10px; 
            border-radius: 4px; 
        }
        QPushButton:hover { background-color: #4f5355; }
        QPushButton:pressed { background-color: #2a2d2f; }
        QPushButton#AccentButton { 
            background-color: #007acc; 
            color: white; 
            font-weight: bold; 
        }
        QPushButton#AccentButton:hover { background-color: #008ae6; }
        QPushButton#BreadcrumbButton { 
            background-color: transparent; 
            border: none; 
            color: #00aaff; 
            text-align: left; 
            padding: 2px; 
        }
        QPushButton#BreadcrumbButton:hover { text-decoration: underline; }
        QLineEdit, QComboBox, QListWidget, QTreeWidget { 
            background-color: #3c3f41; 
            border: 1px solid #555; 
            border-radius: 4px; 
            padding: 3px; 
        }
        QHeaderView::section { 
            background-color: #3c3f41; 
            border: 1px solid #555; 
            padding: 4px; 
        }
        QProgressBar { 
            border: 1px solid #555; 
            border-radius: 4px; 
            text-align: center; 
        }
        QProgressBar::chunk { 
            background-color: #007acc; 
            width: 10px; 
            margin: 0.5px; 
        }
        #qt_toolbar_navigation { background-color: #2b2b2b; }
        #qt_toolbar_navigation QToolButton { 
            background-color: #3c3f41; 
            border: 1px solid #555; 
            border-radius: 2px; 
            margin: 1px; 
        }
        #qt_toolbar_navigation QToolButton:hover { background-color: #4f5355; }
        QLabel#CardImageLabel { 
            background-color: #3c3f41; 
            border: 1px solid #555; 
            border-radius: 4px; 
        }
        QStatusBar {
            background-color: #2b2b2b;
            border-top: 1px solid #444;
            color: #f0f0f0;
        }
        QMenuBar {
            background-color: #2b2b2b;
            border-bottom: 1px solid #444;
        }
        QMenuBar::item {
            background-color: transparent;
            padding: 4px 8px;
        }
        QMenuBar::item:selected {
            background-color: #3c3f41;
        }
        QMenu {
            background-color: #3c3f41;
            border: 1px solid #555;
        }
        QMenu::item {
            padding: 5px 10px;
        }
        QMenu::item:selected {
            background-color: #4f5355;
        }
        """

    @staticmethod
    def get_light_stylesheet():
        return """
        QWidget {
            background-color: #ffffff;
            color: #333333;
            font-family: 'Segoe UI';
            font-size: 10pt;
        }
        QMainWindow, QTabWidget, QSplitter {
            background-color: #ffffff;
        }
        QTabWidget::pane { border: 1px solid #cccccc; border-top: 0px; }
        QTabBar::tab { 
            background: #f0f0f0; 
            border: 1px solid #cccccc; 
            border-bottom: none; 
            padding: 8px 20px; 
            border-top-left-radius: 4px; 
            border-top-right-radius: 4px; 
        }
        QTabBar::tab:selected { background: #ffffff; margin-bottom: -1px; }
        QTabBar::tab:!selected:hover { background: #e0e0e0; }
        QGroupBox { 
            font-weight: bold; 
            border: 1px solid #cccccc; 
            border-radius: 5px; 
            margin-top: 1ex; 
        }
        QGroupBox::title { 
            subcontrol-origin: margin; 
            subcontrol-position: top left; 
            padding: 0 3px; 
        }
        QPushButton { 
            background-color: #f0f0f0; 
            border: 1px solid #cccccc; 
            padding: 5px 10px; 
            border-radius: 4px; 
        }
        QPushButton:hover { background-color: #e0e0e0; }
        QPushButton:pressed { background-color: #d0d0d0; }
        QPushButton#AccentButton { 
            background-color: #007acc; 
            color: white; 
            font-weight: bold; 
        }
        QPushButton#AccentButton:hover { background-color: #005a99; }
        QPushButton#BreadcrumbButton { 
            background-color: transparent; 
            border: none; 
            color: #007acc; 
            text-align: left; 
            padding: 2px; 
        }
        QPushButton#BreadcrumbButton:hover { text-decoration: underline; }
        QLineEdit, QComboBox, QListWidget, QTreeWidget { 
            background-color: #ffffff; 
            border: 1px solid #cccccc; 
            border-radius: 4px; 
            padding: 3px; 
        }
        QHeaderView::section { 
            background-color: #f0f0f0; 
            border: 1px solid #cccccc; 
            padding: 4px; 
        }
        QProgressBar { 
            border: 1px solid #cccccc; 
            border-radius: 4px; 
            text-align: center; 
        }
        QProgressBar::chunk { 
            background-color: #007acc; 
            width: 10px; 
            margin: 0.5px; 
        }
        #qt_toolbar_navigation { background-color: #f0f0f0; }
        #qt_toolbar_navigation QToolButton { 
            background-color: #ffffff; 
            border: 1px solid #cccccc; 
            border-radius: 2px; 
            margin: 1px; 
        }
        #qt_toolbar_navigation QToolButton:hover { background-color: #e0e0e0; }
        QLabel#CardImageLabel { 
            background-color: #ffffff; 
            border: 1px solid #cccccc; 
            border-radius: 4px; 
        }
        QStatusBar {
            background-color: #f0f0f0;
            border-top: 1px solid #cccccc;
            color: #333333;
        }
        QMenuBar {
            background-color: #f0f0f0;
            border-bottom: 1px solid #cccccc;
        }
        QMenuBar::item {
            background-color: transparent;
            padding: 4px 8px;
        }
        QMenuBar::item:selected {
            background-color: #e0e0e0;
        }
        QMenu {
            background-color: #ffffff;
            border: 1px solid #cccccc;
        }
        QMenu::item {
            padding: 5px 10px;
        }
        QMenu::item:selected {
            background-color: #e0e0e0;
        }
        """


STYLESHEET = ThemeManager.get_dark_stylesheet()
