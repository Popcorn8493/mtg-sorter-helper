import argparse
import logging
import os
os.environ['QT_API'] = 'pyqt6'
import sys
import traceback
from PyQt6.QtCore import Qt, QCoreApplication, QTimer
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QApplication, QSplashScreen, QMessageBox
from core.constants import Config, ThemeManager

def get_memory_usage():
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        return None

def check_memory_limit(limit_mb=1024):
    usage = get_memory_usage()
    if usage and usage > limit_mb:
        return (False, usage)
    return (True, usage)

def setup_logging():
    try:
        log_dir = Config.APP_CACHE_DIR / 'logs'
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / 'mtg_toolkit.log'
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)])
        logging.getLogger('matplotlib').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)
        return logging.getLogger(__name__)
    except Exception as e:
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.warning(f'Failed to setup advanced logging: {e}')
        return logger

def create_splash_screen():
    try:
        splash_pixmap = QPixmap(400, 300)
        splash_pixmap.fill(QColor('#2b2b2b'))
        painter = QPainter(splash_pixmap)
        painter.setPen(QColor('#f0f0f0'))
        painter.setFont(QFont(Config.SYSTEM_FONT_NAME, 24, QFont.Weight.Bold))
        painter.drawText(splash_pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 'MTG Toolkit\nEnhanced')
        painter.setFont(QFont(Config.SYSTEM_FONT_NAME, 12))
        painter.setPen(QColor('#00aaff'))
        painter.drawText(20, 250, 'Loading collection management tools...')
        painter.end()
        splash = QSplashScreen(splash_pixmap)
        splash.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.SplashScreen)
        return splash
    except Exception as e:
        print(f'Failed to create splash screen: {e}')
        return None

def check_system_requirements():
    issues = []
    if sys.version_info < (3, 8):
        issues.append(f'Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}')
    try:
        import shutil
        free_space = shutil.disk_usage(Config.APP_CACHE_DIR.parent).free
        required_space = 1024 * 1024 * 1024
        if free_space < required_space:
            issues.append(f'Low disk space: {free_space // (1024 * 1024)} MB available, 1GB recommended')
    except Exception:
        pass
    try:
        import requests
        requests.head('https://api.scryfall.com', timeout=5)
    except Exception:
        issues.append('Could not connect to Scryfall API. Check your internet connection.')
    return issues

def parse_arguments():
    parser = argparse.ArgumentParser(description='MTG Toolkit Enhanced - Collection Management Tool', formatter_class=argparse.RawDescriptionHelpFormatter, epilog='\nExamples:\n  %(prog)s                          # Normal startup\n  %(prog)s --theme light            # Start with light theme\n  %(prog)s --debug                  # Enable debug logging\n  %(prog)s --clear-cache            # Clear cache on startup\n  %(prog)s --import file.csv        # Import collection on startup\n        ')
    parser.add_argument('--version', action='version', version='MTG Toolkit Enhanced v1.0')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--theme', choices=['dark', 'light'], help='Start with specified theme')
    parser.add_argument('--clear-cache', action='store_true', help='Clear all cache on startup')
    parser.add_argument('--import', dest='import_file', metavar='FILE', help='Import CSV collection file on startup')
    parser.add_argument('--no-splash', action='store_true', help='Skip splash screen')
    parser.add_argument('--safe-mode', action='store_true', help='Start in safe mode (minimal features, useful for troubleshooting)')
    return parser.parse_args()

def safe_import_main_window():
    try:
        from ui.main_window import MTGToolkitWindow
        return MTGToolkitWindow
    except ImportError as e:
        print(f'Failed to import main window: {e}')
        return None
    except Exception as e:
        print(f'Unexpected error importing main window: {e}')
        traceback.print_exc()
        return None

def main():
    logger = None
    app = None
    main_window = None
    splash = None
    try:
        args = parse_arguments()
        try:
            QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
            os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
        except Exception as e:
            print(f'Warning: Failed to configure high DPI settings: {e}')
        try:
            app = QApplication(sys.argv)
        except Exception as e:
            print(f'Critical error: Failed to create QApplication: {e}')
            return 1
        logger = setup_logging()
        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)
            logger.debug('Debug logging enabled.')
        logger.info('Starting MTG Toolkit Enhanced')
        try:
            QCoreApplication.setApplicationName(Config.APP_NAME)
            QCoreApplication.setApplicationVersion('Enhanced v1.0')
            QCoreApplication.setOrganizationName(Config.ORG_NAME)
        except Exception as e:
            logger.warning(f'Failed to set application metadata: {e}')
        if args.clear_cache:
            try:
                from api.mtgjson_api import MTGJsonAPI
                logger.info('Clearing cache on startup...')
                api = MTGJsonAPI()
                if api.clear_cache():
                    logger.info('Cache cleared successfully.')
                    try:
                        QMessageBox.information(None, 'Cache Cleared', 'Application cache has been cleared.')
                    except:
                        print('Cache cleared successfully.')
                else:
                    logger.warning('Could not clear cache.')
                    try:
                        QMessageBox.warning(None, 'Cache Error', 'Could not clear application cache.')
                    except:
                        print('Warning: Could not clear application cache.')
            except Exception as e:
                logger.error(f'Error during cache clearing: {e}')
        if not args.safe_mode:
            try:
                issues = check_system_requirements()
                if issues:
                    issue_str = '\n'.join((f'- {issue}' for issue in issues))
                    logger.warning(f'System requirement issues detected: {issues}')
                    try:
                        QMessageBox.warning(None, 'System Requirement Warnings', f'The following issues were detected:\n\n{issue_str}\n\nThe application will continue, but some features may not work correctly.')
                    except:
                        print(f'Warning: System requirement issues detected:\n{issue_str}')
            except Exception as e:
                logger.warning(f'Failed to check system requirements: {e}')
        try:
            theme_stylesheet = ThemeManager.get_light_stylesheet() if args.theme == 'light' else ThemeManager.get_dark_stylesheet()
            app.setStyleSheet(theme_stylesheet)
        except Exception as e:
            logger.warning(f'Failed to apply theme: {e}')
        try:
            app.setFont(QFont(Config.SYSTEM_FONT_NAME, 10))
        except Exception as e:
            logger.warning(f'Failed to set default font: {e}')
        if not args.no_splash and (not args.safe_mode):
            try:
                splash = create_splash_screen()
                if splash:
                    splash.show()
                    splash.showMessage('Initializing UI...', Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, QColor('white'))
                    app.processEvents()
            except Exception as e:
                logger.warning(f'Failed to create splash screen: {e}')
                splash = None
        logger.info('Creating main window...')
        try:
            MTGToolkitWindow = safe_import_main_window()
            if MTGToolkitWindow is None:
                raise ImportError('Failed to import main window class')
            main_window = MTGToolkitWindow()
            if main_window is None:
                raise RuntimeError('Failed to create main window instance')
        except Exception as e:
            logger.critical(f'Failed to create main window: {e}', exc_info=True)
            if splash:
                splash.close()
            try:
                QMessageBox.critical(None, 'Startup Error', f'Failed to create the main application window:\n\n{e}\n\nPlease try restarting the application.')
            except:
                print(f'Critical error: Failed to create main window: {e}')
            return 1
        if args.import_file and main_window:
            try:
                if splash:
                    splash.showMessage(f'Importing {os.path.basename(args.import_file)}...', Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, QColor('white'))
                QTimer.singleShot(100, lambda: main_window.sorter_tab.import_csv(filepath=args.import_file))
            except Exception as e:
                logger.error(f'Failed to schedule startup import: {e}')
        logger.info('Showing main window...')
        try:
            main_window.show()
            if splash:
                splash.finish(main_window)
        except Exception as e:
            logger.error(f'Failed to show main window: {e}')
            if splash:
                try:
                    splash.close()
                except:
                    pass
            return 1
        logger.info('MTG Toolkit Enhanced startup completed successfully')

        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            logger.critical('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))
            error_msg = f'An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}'
            try:
                QMessageBox.critical(None, 'Unexpected Error', f'{error_msg}\n\nThe error has been logged. Please save your work and restart the application.')
            except:
                print(f'Critical error: {error_msg}')
        sys.excepthook = handle_exception
        try:
            exit_code = app.exec()
            logger.info(f'Application exiting with code: {exit_code}')
            return exit_code
        except Exception as e:
            logger.critical(f'Error in application event loop: {e}', exc_info=True)
            return 1
    except KeyboardInterrupt:
        logger.info('Application interrupted by user')
        return 0
    except Exception as e:
        try:
            logger.critical(f'Fatal error during startup: {e}', exc_info=True)
        except:
            print(f'Fatal error during startup: {e}')
            traceback.print_exc()
        try:
            if app:
                QMessageBox.critical(None, 'Startup Error', f'A fatal error occurred during startup:\n\n{e}\n\nPlease check the logs and try restarting.')
            else:
                app = QApplication(sys.argv)
                QMessageBox.critical(None, 'Startup Error', f'A fatal error occurred during startup:\n\n{e}')
        except Exception:
            print(f'Critical error: {e}')
        return 1
    finally:
        try:
            if splash:
                splash.close()
            if main_window:
                main_window.close()
            if app:
                app.quit()
        except:
            pass
if __name__ == '__main__':
    import signal

    def signal_handler(sig, frame):
        print('\nApplication interrupted by user')
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f'Fatal error: {e}')
        traceback.print_exc()
        sys.exit(1)