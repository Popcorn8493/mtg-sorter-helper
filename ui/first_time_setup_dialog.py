"""
First-time setup dialog for downloading and indexing MTGJSON card database.

This dialog handles:
- Downloading AllPrintings.json.gz (compressed, ~180MB)
- Building Scryfall ID index from the downloaded data
- Progress tracking for both operations
"""

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit
from PyQt6.QtGui import QFont
from api.mtgjson_api import MTGJsonAPI
from api.scryfall_api import MTGAPIError


class SetupWorker(QObject):
    """Worker thread for downloading and indexing MTGJSON data."""

    download_progress = pyqtSignal(int, int)  # (bytes_downloaded, total_bytes)
    indexing_progress = pyqtSignal(int, int)  # (sets_processed, total_sets)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(bool)  # True if successful, False if failed
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.api = MTGJsonAPI()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        """Execute the full setup: download and index."""
        try:
            # Step 1: Download AllPrintings
            self.status_update.emit("Downloading MTGJSON AllPrintings database (compressed)...")
            try:
                self.api.download_allprintings(progress_callback=self._on_download_progress)
            except MTGAPIError as e:
                self.error.emit(f"Download failed: {str(e)}")
                self.finished.emit(False)
                return
            except Exception as e:
                self.error.emit(f"Unexpected error during download: {str(e)}")
                self.finished.emit(False)
                return

            if self._is_cancelled:
                self.finished.emit(False)
                return

            # Step 2: Build Scryfall Index
            self.status_update.emit("Building Scryfall ID index from card database...")
            try:
                self.api.build_scryfall_index(progress_callback=self._on_indexing_progress)
            except MTGAPIError as e:
                self.error.emit(f"Indexing failed: {str(e)}")
                self.finished.emit(False)
                return
            except Exception as e:
                self.error.emit(f"Unexpected error during indexing: {str(e)}")
                self.finished.emit(False)
                return

            if self._is_cancelled:
                self.finished.emit(False)
                return

            self.status_update.emit("Setup complete! Ready to import collections.")
            self.finished.emit(True)

        except Exception as e:
            self.error.emit(f"Setup failed: {str(e)}")
            self.finished.emit(False)

    def _on_download_progress(self, bytes_downloaded: int, total_bytes: int):
        """Callback for download progress."""
        if not self._is_cancelled:
            # Convert bytes to MB for display
            mb_downloaded = bytes_downloaded / (1024 * 1024)
            mb_total = total_bytes / (1024 * 1024)
            self.status_update.emit(f"Downloading... ({mb_downloaded:.1f} MB / {mb_total:.1f} MB)")
            self.download_progress.emit(bytes_downloaded, total_bytes)

    def _on_indexing_progress(self, sets_processed: int, total_sets: int):
        """Callback for indexing progress."""
        if not self._is_cancelled:
            self.status_update.emit(f"Building index... ({sets_processed} / {total_sets} sets)")
            self.indexing_progress.emit(sets_processed, total_sets)


class FirstTimeSetupDialog(QDialog):
    """Dialog for first-time setup of MTGJSON database."""

    setup_complete = pyqtSignal(bool)  # True if successful, False if cancelled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MTG Card Database Setup")
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self.worker = None
        self.worker_thread = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout()

        # Title
        title = QLabel("First-Time Setup Required")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(title)

        # Description
        description = QLabel(
            "To import your collection, MTG Toolkit needs to download and index "
            "the complete Magic: The Gathering card database from MTGJSON.\n\n"
            "This is a one-time process that takes 5-15 minutes depending on your "
            "internet connection.\n\n"
            "The download is compressed (~180MB) and will be decompressed locally."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        # Status text
        self.status_label = QLabel("Ready to begin setup...")
        layout.addWidget(self.status_label)

        # Download progress
        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        layout.addWidget(self.download_progress)

        # Indexing progress
        self.indexing_progress = QProgressBar()
        self.indexing_progress.setVisible(False)
        layout.addWidget(self.indexing_progress)

        # Log/Details text
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        self.details_text.setVisible(False)
        layout.addWidget(self.details_text)

        # Buttons
        button_layout = QVBoxLayout()

        self.start_button = QPushButton("Start Setup")
        self.start_button.clicked.connect(self._start_setup)
        button_layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel_setup)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _start_setup(self):
        """Start the setup process."""
        self.start_button.setEnabled(False)
        self.cancel_button.setText("Cancel")
        self.download_progress.setVisible(True)
        self.indexing_progress.setVisible(True)
        self.details_text.setVisible(True)

        # Create and start worker thread
        self.worker = SetupWorker()
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.run)
        self.worker.status_update.connect(self._on_status_update)
        self.worker.download_progress.connect(self._on_download_progress)
        self.worker.indexing_progress.connect(self._on_indexing_progress)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(self._on_finished)

        # Cleanup signals
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def _cancel_setup(self):
        """Cancel the setup process."""
        if self.worker and self.worker_thread and self.worker_thread.isRunning():
            self.worker.cancel()
            self.worker_thread.quit()
            self.worker_thread.wait(2000)

        self.setup_complete.emit(False)
        from PyQt6.QtWidgets import QDialog
        self.done(QDialog.DialogCode.Rejected)

    def _on_status_update(self, status: str):
        """Update status label."""
        self.status_label.setText(status)
        self.details_text.append(status)

    def _on_download_progress(self, bytes_downloaded: int, total_bytes: int):
        """Update download progress bar."""
        if total_bytes > 0:
            percentage = int((bytes_downloaded / total_bytes) * 100)
            self.download_progress.setValue(percentage)

    def _on_indexing_progress(self, sets_processed: int, total_sets: int):
        """Update indexing progress bar."""
        if total_sets > 0:
            percentage = int((sets_processed / total_sets) * 100)
            self.indexing_progress.setValue(percentage)

    def _on_error(self, error_message: str):
        """Handle error during setup."""
        self.details_text.append(f"ERROR: {error_message}")
        self.status_label.setText("Setup failed! See details below.")
        self.start_button.setEnabled(True)
        self.start_button.setText("Retry Setup")
        self.cancel_button.setText("Close")

    def _on_finished(self, success: bool):
        """Handle setup completion."""
        if success:
            self.status_label.setText("Setup complete! You can now import collections.")
            self.details_text.append("Setup completed successfully!")
            self.start_button.setEnabled(False)
            self.cancel_button.setText("Close")

            # Auto-close after a short delay
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self._accept_setup())
        else:
            self.status_label.setText("Setup cancelled.")
            self.start_button.setEnabled(True)
            self.start_button.setText("Retry Setup")
            self.cancel_button.setText("Close")

    def _accept_setup(self):
        """Accept and close the dialog after successful setup."""
        self.setup_complete.emit(True)
        # Use QDialog.Accepted (1) instead of accept() to properly signal success
        from PyQt6.QtWidgets import QDialog
        self.done(QDialog.DialogCode.Accepted)
