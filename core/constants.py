import os
import pathlib
import platform

def _get_system_font():
    """Get the appropriate system font for the current platform (for CSS)."""
    system = platform.system()
    if system == 'Darwin':  # macOS
        return '"Helvetica Neue", "Helvetica", Arial, sans-serif'
    elif system == 'Windows':
        return '"Segoe UI", Arial, sans-serif'
    else:  # Linux and others
        return '"Ubuntu", "Roboto", "Helvetica Neue", Arial, sans-serif'

def _get_system_font_name():
    """Get the font name for QFont based on platform."""
    system = platform.system()
    if system == 'Darwin':  # macOS
        return 'Helvetica Neue'
    elif system == 'Windows':
        return 'Segoe UI'
    else:  # Linux and others
        return 'Ubuntu'

def _get_global_cache_dir():
    app_name = 'MTGToolkit'
    try:
        if os.name == 'nt':
            appdata = os.environ.get('APPDATA')
            if appdata:
                cache_base = pathlib.Path(appdata)
            else:
                cache_base = pathlib.Path.home() / 'AppData' / 'Roaming'
        elif os.name == 'posix':
            xdg_cache = os.environ.get('XDG_CACHE_HOME')
            if xdg_cache:
                cache_base = pathlib.Path(xdg_cache)
            else:
                cache_base = pathlib.Path.home() / '.cache'
        else:
            cache_base = pathlib.Path.home()
        cache_base = cache_base.resolve()
        return cache_base / f'{app_name}_cache'
    except Exception as e:
        print(f'Warning: Failed to determine cache directory: {e}')
        return pathlib.Path.home() / f'{app_name}_cache'

class Config:
    APP_NAME = 'MTGToolkit'
    ORG_NAME = 'MTGToolkitOrg'
    SCRYFALL_API_CARD_ENDPOINT = 'https://api.scryfall.com/cards/'
    SCRYFALL_API_SET_ENDPOINT = 'https://api.scryfall.com/cards/search'
    MTGJSON_API_BASE = 'https://mtgjson.com/api/v5/'
    ALLPRINTINGS_URL = 'https://mtgjson.com/api/v5/AllPrintings.json.gz'
    APP_CACHE_DIR = _get_global_cache_dir()
    CARD_CACHE_DIR = APP_CACHE_DIR / 'card_data'
    IMAGE_CACHE_DIR = APP_CACHE_DIR / 'image_data'
    SET_CACHE_DIR = APP_CACHE_DIR / 'set_data'
    BOOSTER_CACHE_DIR = APP_CACHE_DIR / 'booster_data'
    ALLPRINTINGS_CACHE_PATH = APP_CACHE_DIR / 'allprintings.json'
    SCRYFALL_INDEX_PATH = APP_CACHE_DIR / 'scryfall_index.db'
    MAX_CACHE_SIZE_MB = 500
    MAX_IMAGE_CACHE_SIZE_MB = 200
    MAX_BOOSTER_CACHE_SIZE_MB = 50
    AUTO_SAVE_INTERVAL = 300000
    PROJECT_EXTENSION = 'mtgproj'
    MAX_RECENT_PROJECTS = 5
    DEFAULT_THEME = 'dark'
    SYSTEM_FONT = _get_system_font()
    SYSTEM_FONT_NAME = _get_system_font_name()

def _setup_global_cache():
    import shutil
    try:
        Config.APP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Config.CARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Config.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Config.SET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Config.BOOSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        print(f'Cache directories created successfully at: {Config.APP_CACHE_DIR}')
    except Exception as e:
        print(f'Error creating cache directories: {e}')
        try:
            fallback_cache = pathlib.Path.home() / 'MTGToolkit_cache'
            fallback_cache.mkdir(parents=True, exist_ok=True)
            Config.APP_CACHE_DIR = fallback_cache
            Config.CARD_CACHE_DIR = fallback_cache / 'card_data'
            Config.IMAGE_CACHE_DIR = fallback_cache / 'image_data'
            Config.SET_CACHE_DIR = fallback_cache / 'set_data'
            Config.BOOSTER_CACHE_DIR = fallback_cache / 'booster_data'
            Config.CARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            Config.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            Config.SET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            Config.BOOSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            print(f'Using fallback cache directory: {fallback_cache}')
        except Exception as fallback_error:
            print(f'Critical error: Could not create any cache directories: {fallback_error}')
            raise
    old_cache_dir = pathlib.Path('.mtgtoolkit_cache')
    if old_cache_dir.exists() and old_cache_dir.is_dir():
        print(f'Found old cache directory: {old_cache_dir}')
        print(f'Migrating to global cache: {Config.APP_CACHE_DIR}')
        try:
            for old_subdir, new_subdir in [('card_data', Config.CARD_CACHE_DIR), ('image_data', Config.IMAGE_CACHE_DIR), ('set_data', Config.SET_CACHE_DIR), ('booster_data', Config.BOOSTER_CACHE_DIR)]:
                old_path = old_cache_dir / old_subdir
                if old_path.exists():
                    print(f'Migrating {old_subdir} from {old_path} to {new_subdir}')
                    files_copied = 0
                    for file_path in old_path.glob('*'):
                        if file_path.is_file():
                            new_file_path = new_subdir / file_path.name
                            if not new_file_path.exists():
                                shutil.copy2(file_path, new_file_path)
                                files_copied += 1
                            else:
                                print(f'Skipped {file_path.name} (already exists)')
                    print(f'Copied {files_copied} files from {old_subdir}')
                else:
                    print(f'No {old_subdir} directory found in old cache')
            print(f'Cache migration completed. You can safely delete: {old_cache_dir}')
        except Exception as e:
            print(f'Cache migration failed: {e}')
            print('Old cache will remain, but new cache location will be used going forward.')
    print(f'Global cache location: {Config.APP_CACHE_DIR}')

def verify_cache_accessibility():
    try:
        test_file = Config.APP_CACHE_DIR / 'test_write.tmp'
        test_file.write_text('test')
        test_file.unlink()
        test_file = Config.CARD_CACHE_DIR / 'test_write.tmp'
        test_file.write_text('test')
        test_file.unlink()
        test_file = Config.IMAGE_CACHE_DIR / 'test_write.tmp'
        test_file.write_text('test')
        test_file.unlink()
        test_file = Config.SET_CACHE_DIR / 'test_write.tmp'
        test_file.write_text('test')
        test_file.unlink()
        test_file = Config.BOOSTER_CACHE_DIR / 'test_write.tmp'
        test_file.write_text('test')
        test_file.unlink()
        print('Cache directories are accessible and writable')
        return True
    except Exception as e:
        print(f'Warning: Cache directories may not be fully accessible: {e}')
        return False
_setup_global_cache()
verify_cache_accessibility()

class ThemeManager:

    @staticmethod
    def get_dark_stylesheet():
        stylesheet = "\n        QWidget {\n            background-color: #2b2b2b;\n            color: #f0f0f0;\n            font-family: " + Config.SYSTEM_FONT + ";\n            font-size: 10pt;\n        }"
        stylesheet += "\n        QMainWindow, QTabWidget, QSplitter {\n            background-color: #2b2b2b;\n        }\n        QTabWidget::pane { border: 1px solid #444; border-top: 0px; }\n        QTabBar::tab { \n            background: #3c3f41; \n            border: 1px solid #444; \n            border-bottom: none; \n            padding: 8px 20px; \n            border-top-left-radius: 4px; \n            border-top-right-radius: 4px; \n        }\n        QTabBar::tab:selected { background: #2b2b2b; margin-bottom: -1px; }\n        QTabBar::tab:!selected:hover { background: #4f5355; }\n        QGroupBox { \n            font-weight: bold; \n            border: 1px solid #444; \n            border-radius: 5px; \n            margin-top: 1ex; \n        }\n        QGroupBox::title { \n            subcontrol-origin: margin; \n            subcontrol-position: top left; \n            padding: 0 3px; \n            font-size: 12pt; \n            font-weight: 600; \n        }\n        QLabel.subtitle { \n            font-size: 9pt; \n            color: #888; \n        }\n        QLabel.title { \n            font-size: 14pt; \n            font-weight: 700; \n        }\n        QPushButton { \n            background-color: #3c3f41; \n            border: 1px solid #555; \n            padding: 5px 10px; \n            border-radius: 4px; \n        }\n        QPushButton:hover { background-color: #4f5355; }\n        QPushButton:pressed { background-color: #2a2d2f; }\n        QPushButton#AccentButton { \n            background-color: #007acc; \n            color: white; \n            font-weight: bold; \n        }\n        QPushButton#AccentButton:hover { background-color: #008ae6; }\n        QPushButton#BreadcrumbButton { \n            background-color: transparent; \n            border: none; \n            color: #00aaff; \n            text-align: left; \n            padding: 2px; \n        }\n        QPushButton#BreadcrumbButton:hover { text-decoration: underline; }\n        QLineEdit, QComboBox, QListWidget, QTreeWidget { \n            background-color: #3c3f41; \n            border: 1px solid #555; \n            border-radius: 4px; \n            padding: 3px; \n        }\n        QHeaderView::section { \n            background-color: #3c3f41; \n            border: 1px solid #555; \n            padding: 4px; \n        }\n        QProgressBar { \n            border: 1px solid #555; \n            border-radius: 4px; \n            text-align: center; \n        }\n        QProgressBar::chunk { \n            background-color: #007acc; \n            width: 10px; \n            margin: 0.5px; \n        }\n        #qt_toolbar_navigation { background-color: #2b2b2b; }\n        #qt_toolbar_navigation QToolButton { \n            background-color: #3c3f41; \n            border: 1px solid #555; \n            border-radius: 2px; \n            margin: 1px; \n        }\n        #qt_toolbar_navigation QToolButton:hover { background-color: #4f5355; }\n        QLabel#CardImageLabel { \n            background-color: #3c3f41; \n            border: 1px solid #555; \n            border-radius: 4px; \n        }\n        QStatusBar {\n            background-color: #2b2b2b;\n            border-top: 1px solid #444;\n            color: #f0f0f0;\n        }\n        QMenuBar {\n            background-color: #2b2b2b;\n            border-bottom: 1px solid #444;\n        }\n        QMenuBar::item {\n            background-color: transparent;\n            padding: 4px 8px;\n        }\n        QMenuBar::item:selected {\n            background-color: #3c3f41;\n        }\n        QMenu {\n            background-color: #3c3f41;\n            border: 1px solid #555;\n        }\n        QMenu::item {\n            padding: 5px 10px;\n        }\n        QMenu::item:selected {\n            background-color: #4f5355;\n        }\n        "
        return stylesheet

    @staticmethod
    def get_light_stylesheet():
        stylesheet = "\n        QWidget {\n            background-color: #ffffff;\n            color: #333333;\n            font-family: " + Config.SYSTEM_FONT + ";\n            font-size: 10pt;\n        }"
        stylesheet += "\n        QMainWindow, QTabWidget, QSplitter {\n            background-color: #ffffff;\n        }\n        QTabWidget::pane { border: 1px solid #cccccc; border-top: 0px; }\n        QTabBar::tab { \n            background: #f0f0f0; \n            border: 1px solid #cccccc; \n            border-bottom: none; \n            padding: 8px 20px; \n            border-top-left-radius: 4px; \n            border-top-right-radius: 4px; \n        }\n        QTabBar::tab:selected { background: #ffffff; margin-bottom: -1px; }\n        QTabBar::tab:!selected:hover { background: #e0e0e0; }\n        QGroupBox { \n            font-weight: bold; \n            border: 1px solid #cccccc; \n            border-radius: 5px; \n            margin-top: 1ex; \n        }\n        QGroupBox::title { \n            subcontrol-origin: margin; \n            subcontrol-position: top left; \n            padding: 0 3px; \n            font-size: 12pt; \n            font-weight: 600; \n        }\n        QLabel.subtitle { \n            font-size: 9pt; \n            color: #888; \n        }\n        QLabel.title { \n            font-size: 14pt; \n            font-weight: 700; \n        }\n        QPushButton { \n            background-color: #f0f0f0; \n            border: 1px solid #cccccc; \n            padding: 5px 10px; \n            border-radius: 4px; \n        }\n        QPushButton:hover { background-color: #e0e0e0; }\n        QPushButton:pressed { background-color: #d0d0d0; }\n        QPushButton#AccentButton { \n            background-color: #007acc; \n            color: white; \n            font-weight: bold; \n        }\n        QPushButton#AccentButton:hover { background-color: #005a99; }\n        QPushButton#BreadcrumbButton { \n            background-color: transparent; \n            border: none; \n            color: #007acc; \n            text-align: left; \n            padding: 2px; \n        }\n        QPushButton#BreadcrumbButton:hover { text-decoration: underline; }\n        QLineEdit, QComboBox, QListWidget, QTreeWidget { \n            background-color: #ffffff; \n            border: 1px solid #cccccc; \n            border-radius: 4px; \n            padding: 3px; \n        }\n        QHeaderView::section { \n            background-color: #f0f0f0; \n            border: 1px solid #cccccc; \n            padding: 4px; \n        }\n        QProgressBar { \n            border: 1px solid #cccccc; \n            border-radius: 4px; \n            text-align: center; \n        }\n        QProgressBar::chunk { \n            background-color: #007acc; \n            width: 10px; \n            margin: 0.5px; \n        }\n        #qt_toolbar_navigation { background-color: #f0f0f0; }\n        #qt_toolbar_navigation QToolButton { \n            background-color: #ffffff; \n            border: 1px solid #cccccc; \n            border-radius: 2px; \n            margin: 1px; \n        }\n        #qt_toolbar_navigation QToolButton:hover { background-color: #e0e0e0; }\n        QLabel#CardImageLabel { \n            background-color: #ffffff; \n            border: 1px solid #cccccc; \n            border-radius: 4px; \n        }\n        QStatusBar {\n            background-color: #f0f0f0;\n            border-top: 1px solid #cccccc;\n            color: #333333;\n        }\n        QMenuBar {\n            background-color: #f0f0f0;\n            border-bottom: 1px solid #cccccc;\n        }\n        QMenuBar::item {\n            background-color: transparent;\n            padding: 4px 8px;\n        }\n        QMenuBar::item:selected {\n            background-color: #e0e0e0;\n        }\n        QMenu {\n            background-color: #ffffff;\n            border: 1px solid #cccccc;\n        }\n        QMenu::item {\n            padding: 5px 10px;\n        }\n        QMenu::item:selected {\n            background-color: #e0e0e0;\n        }\n        "
        return stylesheet

STYLESHEET = ThemeManager.get_dark_stylesheet()