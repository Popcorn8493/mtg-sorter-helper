#!/usr/bin/env python3


import sys
import os
import argparse
import logging
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QSplashScreen, QMessageBox
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QTimer, QThread, QCoreApplication

# Local application imports
from ui.main_window import MTGToolkitWindow
from core.constants import Config, ThemeManager


def setup_logging():
    """Setup application logging with appropriate levels"""
    log_dir = Config.APP_CACHE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "mtg_toolkit.log"

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Set specific log levels for different components
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)

    return logging.getLogger(__name__)


def create_splash_screen():
    """Create an attractive splash screen for application startup"""
    # Create a simple splash screen
    splash_pixmap = QPixmap(400, 300)
    splash_pixmap.fill(QColor('#2b2b2b'))

    painter = QPainter(splash_pixmap)
    painter.setPen(QColor('#f0f0f0'))
    painter.setFont(QFont('Segoe UI', 24, QFont.Weight.Bold))

    # Draw title
    painter.drawText(splash_pixmap.rect(), Qt.AlignmentFlag.AlignCenter,
                     "MTG Toolkit\nEnhanced")

    painter.setFont(QFont('Segoe UI', 12))
    painter.setPen(QColor('#00aaff'))
    painter.drawText(20, 250, "Loading collection management tools...")

    painter.end()

    splash = QSplashScreen(splash_pixmap)
    splash.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.SplashScreen)
    return splash


def check_system_requirements():
    """Check system requirements and warn if issues are detected"""
    issues = []

    # Check Python version
    if sys.version_info < (3, 8):
        issues.append(f"Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")

    # Check available disk space for cache
    try:
        import shutil
        free_space = shutil.disk_usage(Config.APP_CACHE_DIR.parent).free
        required_space = 1024 * 1024 * 1024  # 1GB
        if free_space < required_space:
            issues.append(f"Low disk space: {free_space // (1024 * 1024)} MB available, 1GB recommended")
    except Exception:
        pass

    # Check internet connectivity (basic check)
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
    except OSError:
        issues.append("No internet connection detected - some features may not work")

    return issues


def parse_arguments():
    """Parse command line arguments for advanced usage"""
    parser = argparse.ArgumentParser(
        description="MTG Toolkit Enhanced - Collection Management Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Normal startup
  %(prog)s --theme light            # Start with light theme
  %(prog)s --debug                  # Enable debug logging
  %(prog)s --clear-cache            # Clear cache on startup
  %(prog)s --import file.csv        # Import collection on startup
        """
    )

    parser.add_argument('--version', action='version', version='MTG Toolkit Enhanced v1.0')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--theme', choices=['dark', 'light'], help='Start with specified theme')
    parser.add_argument('--clear-cache', action='store_true', help='Clear all cache on startup')
    parser.add_argument('--import', dest='import_file', metavar='FILE',
                        help='Import CSV collection file on startup')
    parser.add_argument('--no-splash', action='store_true', help='Skip splash screen')
    parser.add_argument('--safe-mode', action='store_true',
                        help='Start in safe mode (minimal features, useful for troubleshooting)')

    return parser.parse_args()


def main():
    """Main application entry point with enhanced startup sequence"""
    try:
        # Configure Qt for high DPI displays
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

        # Create the application instance
        app = QApplication(sys.argv)

        # Set up basic logging
        logger = setup_logging()
        logger.info("Starting MTG Toolkit Enhanced")

        # Set application metadata
        QCoreApplication.setApplicationName(Config.APP_NAME)
        QCoreApplication.setApplicationVersion("Enhanced v1.0")
        QCoreApplication.setOrganizationName(Config.ORG_NAME)

        # Apply default stylesheet immediately
        app.setStyleSheet(ThemeManager.get_dark_stylesheet())

        # Set default font
        app.setFont(QFont('Segoe UI', 10))

        # Create main window
        logger.info("Creating main window...")
        main_window = MTGToolkitWindow()

        # Show main window
        logger.info("Showing main window...")
        main_window.show()

        # Log startup completion
        logger.info("MTG Toolkit Enhanced startup completed successfully")

        # Run the application
        exit_code = app.exec()
        logger.info(f"Application exiting with code: {exit_code}")
        return exit_code

    except Exception as e:
        print(f"Fatal error during startup: {e}")
        import traceback
        traceback.print_exc()

        # Try to show error dialog if possible
        try:
            if 'app' in locals():
                QMessageBox.critical(None, "Startup Error", f"Fatal error: {str(e)}")
        except:
            pass

        return 1


if __name__ == "__main__":
    # Handle Ctrl+C gracefully
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)