import pathlib
from typing import List
from PyQt6.QtCore import QSettings, QThread, QTimer
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from api.mtgjson_api import MTGJsonAPI
from core.constants import Config
from core.models import Card
from workers.threads import CsvImportWorker, LionsEyeImportWorker
from ui.first_time_setup_dialog import FirstTimeSetupDialog

class SorterImport:

    def __init__(self, parent):
        self.parent = parent
        self.api: MTGJsonAPI = parent.api
        self.last_csv_path: str | None = None
        self.progress_to_load: dict | None = None
        self.is_loading = False
        self.import_thread: QThread | None = None
        self.import_worker: CsvImportWorker | LionsEyeImportWorker | None = None

    def _detect_csv_format(self, filepath: str) -> str:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = [f.readline().strip() for _ in range(3)]
            if any(('Number of Non-foil' in line and 'Number of Foil' in line for line in lines)):
                return 'lions_eye'
            if any(('Scryfall ID' in line and 'Quantity' in line for line in lines)):
                return 'manabox'
            return 'unknown'
        except Exception:
            return 'unknown'

    def import_csv(self, filepath=None):
        if self.is_loading:
            QMessageBox.information(self.parent, 'Import in Progress', 'Please wait for the current import to complete.')
            return
        if not filepath:
            settings = QSettings(Config.ORG_NAME, Config.APP_NAME)
            last_dir = settings.value('sorter/lastImportDir', str(pathlib.Path.home()))
            filepath, _ = QFileDialog.getOpenFileName(self.parent, 'Open Collection CSV', last_dir, 'CSV Files (*.csv);;All Files (*.*)')
            if not filepath:
                return
            settings.setValue('sorter/lastImportDir', str(pathlib.Path(filepath).parent))
        try:
            file_path = pathlib.Path(filepath)
            if not file_path.exists():
                QMessageBox.critical(self.parent, 'File Not Found', f"The file '{filepath}' does not exist.")
                return
            if not file_path.is_file():
                QMessageBox.critical(self.parent, 'Invalid File', f"'{filepath}' is not a valid file.")
                return
            csv_format = self._detect_csv_format(filepath)
            if csv_format == 'unknown':
                if QMessageBox.question(self.parent, 'Unrecognized Format', "This file doesn't look like a supported CSV format (ManaBox or Lion's Eye). Continue anyway?") == QMessageBox.StandardButton.No:
                    return
                csv_format = 'manabox'
        except Exception as e:
            self.parent.handle_file_error('file access', e, additional_context=f"filepath: {filepath}, exists: {(file_path.exists() if 'file_path' in locals() else 'Unknown')}")
            QMessageBox.critical(self.parent, 'File Access Error', f'Unable to read file: {e}')
            return

        # Check if first-time setup is needed
        if not self.api.ensure_allprintings_loaded():
            setup_dialog = FirstTimeSetupDialog(self.parent)
            from PyQt6.QtWidgets import QDialog
            result = setup_dialog.exec()
            if result != QDialog.DialogCode.Accepted:
                QMessageBox.information(self.parent, 'Setup Cancelled', 'Import cancelled. Please run setup to download the card database.')
                return

        self.parent.cleanup_workers()
        self.is_loading = True
        self.last_csv_path = filepath
        self.parent.import_button.setEnabled(False)
        self.parent.run_button.setEnabled(False)
        self.parent.file_label.setText(f'Loading {pathlib.Path(filepath).name}...')
        self.parent.progress_bar.setVisible(True)
        self.parent.progress_bar.setRange(0, 0)
        self.parent.operation_started.emit(f'Importing {pathlib.Path(filepath).name}', 0)
        self.import_thread = QThread()
        if csv_format == 'lions_eye':
            self.import_worker = LionsEyeImportWorker(filepath, self.api)
        else:
            self.import_worker = CsvImportWorker(filepath, self.api)
        self.import_worker.moveToThread(self.import_thread)
        self.import_thread.started.connect(self.import_worker.process)
        self.import_worker.progress.connect(self.parent.update_progress)
        self.import_worker.finished.connect(self.on_import_finished)
        self.import_worker.error.connect(self.on_import_error)
        self.import_worker.finished.connect(self.import_thread.quit)
        self.import_worker.finished.connect(self.import_worker.deleteLater)
        self.import_thread.finished.connect(self.import_thread.deleteLater)
        self.import_thread.start()

    def on_import_finished(self, cards: List[Card]):
        try:
            self.parent.all_cards = cards
            if self.progress_to_load:
                for card in self.parent.all_cards:
                    card.sorted_count = self.progress_to_load.get(card.scryfall_id, 0)
                    card.sorted_count = min(card.sorted_count, card.quantity)
                self.progress_to_load = None
            unique_count = len(self.parent.all_cards)
            total_count = sum((card.quantity for card in self.parent.all_cards))
            self.parent.file_label.setText(f'Loaded {unique_count:,} unique cards ({total_count:,} total)')
            self.parent.progress_bar.setVisible(False)
            self.parent.import_button.setEnabled(True)
            self.parent.run_button.setEnabled(True)
            self.is_loading = False
            self.parent.operation_finished.emit()
            self.parent.collection_loaded.emit()
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
            self.parent._start_plan_generation()
            self.parent.project_modified.emit()
            # Image caching removed in MTGJSON migration
        except MemoryError:
            self.is_loading = False
            self.parent.file_label.setText('Import failed - out of memory')
            self.parent.progress_bar.setVisible(False)
            self.parent.import_button.setEnabled(True)
            self.parent.run_button.setEnabled(True)
            self.parent.operation_finished.emit()
            QMessageBox.critical(self.parent, 'Memory Error', 'Not enough memory to load this collection.\n\nTry:\n• Closing other applications\n• Splitting the collection into smaller files\n• Restarting the application')
        except Exception as e:
            self.parent.handle_critical_error('import process', e, additional_context=f'cards_count: {(len(self.parent.all_cards) if self.parent.all_cards else 0)}, loading: {self.is_loading}')
            self.is_loading = False
            self.parent.file_label.setText('Import failed - unexpected error')
            self.parent.progress_bar.setVisible(False)
            self.parent.import_button.setEnabled(True)
            self.parent.run_button.setEnabled(True)
            self.parent.operation_finished.emit()
            QMessageBox.critical(self.parent, 'Import Error', f'Unexpected error during import:\n\n{str(e)}')
        finally:
            pass

    def on_import_error(self, error_message: str):
        self.is_loading = False
        self.parent.file_label.setText('Import failed - see details below')
        self.parent.progress_bar.setVisible(False)
        self.parent.import_button.setEnabled(True)
        self.parent.run_button.setEnabled(True)
        self.parent.operation_finished.emit()
        QMessageBox.critical(self.parent, 'Import Error', error_message)

    def clear_project(self, prompt=True):
        if prompt:
            reply = QMessageBox.question(self.parent, 'Clear Project', 'Are you sure you want to clear all loaded data and sorting progress?\n\nThis action cannot be undone.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.parent.cleanup_workers()
        self.parent.all_cards = []
        self.last_csv_path = None
        self.progress_to_load = None
        self.parent.file_label.setText('No file loaded.')
        self.parent.clear_layout(self.parent.breadcrumb_layout)
        self.parent._show_empty_state()
        self.parent.reset_preview_pane()
        self.parent.filter_edit.clear()
        self.parent.filter_edit.setVisible(False)
        self.parent.preview_panel.setVisible(False)
        self.parent.update_button_visibility()
        self.parent.show_status_message('Project cleared. Import a new CSV to begin.', 5000, style='info')
        self.parent.project_modified.emit()

    def reset_sort_progress(self):
        if not self.parent.all_cards:
            QMessageBox.information(self.parent, 'No Collection', 'No collection is loaded.')
            return
        reply = QMessageBox.question(self.parent, 'Reset Sort Progress', 'Are you sure you want to reset the sorting progress for all cards?\n\nThis will mark all cards as unsorted.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for card in self.parent.all_cards:
                card.sorted_count = 0
            self.parent.show_status_message('All sorting progress has been reset.', 3000, style='info')
            self.parent.project_modified.emit()
            QTimer.singleShot(100, self.parent._refresh_current_view)