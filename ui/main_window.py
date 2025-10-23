from pathlib import Path
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QFileDialog, QMessageBox
from api.mtgjson_api import MTGJsonAPI
from core.constants import Config
from ui.analyzer_tab import SetAnalyzerTab
from ui.sorter_tab import ManaBoxSorterTab

class MTGToolkitWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('MTG Toolkit')
        self.setGeometry(100, 100, 1280, 800)
        self.current_project_path = None
        self._is_dirty = False
        self.settings = QSettings(Config.ORG_NAME, Config.APP_NAME)
        self.api = MTGJsonAPI()
        tab_widget = QTabWidget()
        self.setCentralWidget(tab_widget)
        self.sorter_tab = ManaBoxSorterTab(self.api)
        tab_widget.addTab(self.sorter_tab, 'Collection Sorter')
        self.analyzer_tab = SetAnalyzerTab(self.api, self.sorter_tab)
        tab_widget.addTab(self.analyzer_tab, 'Set Analyzer')
        self._create_actions()
        self._create_menus()
        self._startup_sequence()
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.auto_save_project)
        self.auto_save_timer.start(Config.AUTO_SAVE_INTERVAL)
        self.sorter_tab.project_modified.connect(self.set_dirty)

    def _startup_sequence(self):
        self.load_settings()
        self._prompt_to_load_last_project()

    def set_dirty(self, dirty=True):
        print('DEBUG: MainWindow.set_dirty called with dirty =', dirty)
        try:
            if self._is_dirty != dirty:
                print('DEBUG: Updating dirty state from', self._is_dirty, 'to', dirty)
                self._is_dirty = dirty
                print('DEBUG: About to call _update_window_title...')
                self._update_window_title()
                print('DEBUG: _update_window_title completed')
            else:
                print('DEBUG: No dirty state change needed')
        except Exception as e:
            print(f'ERROR: Exception in set_dirty: {e}')
            import traceback
            traceback.print_exc()

    def _update_window_title(self):
        print('DEBUG: _update_window_title called')
        try:
            title = 'MTG Toolkit'
            print('DEBUG: Base title set')
            if self.current_project_path:
                print(f'DEBUG: Adding project path: {self.current_project_path}')
                title = f'{Path(self.current_project_path).name} - {title}'
                print(f'DEBUG: Title with project: {title}')
            if self._is_dirty:
                print('DEBUG: Adding dirty marker')
                title = f'*{title}'
                print(f'DEBUG: Final title: {title}')
            print('DEBUG: About to call setWindowTitle...')
            self.setWindowTitle(title)
            print('DEBUG: setWindowTitle completed')
        except Exception as e:
            print(f'ERROR: Exception in _update_window_title: {e}')
            import traceback
            traceback.print_exc()

    def _create_actions(self):
        self.new_action = QAction('&New Project', self, shortcut=QKeySequence.StandardKey.New, statusTip='Create a new project', triggered=self.new_project)
        self.open_action = QAction('&Open Project...', self, shortcut=QKeySequence.StandardKey.Open, statusTip='Open an existing project', triggered=self.open_project)
        self.save_action = QAction('&Save Project', self, shortcut=QKeySequence.StandardKey.Save, statusTip='Save the current project', triggered=self.save_project)
        self.save_as_action = QAction('Save Project &As...', self, shortcut=QKeySequence.StandardKey.SaveAs, statusTip='Save the current project under a new name', triggered=self.save_project_as)
        self.exit_action = QAction('E&xit', self, shortcut='Ctrl+Q', statusTip='Exit the application', triggered=self.close)

    def _create_menus(self):
        file_menu = self.menuBar().addMenu('&File')
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        self.recent_projects_menu = file_menu.addMenu('Recent Projects')
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

    def new_project(self):
        if not self._prompt_to_save():
            return
        self.sorter_tab.clear_project(prompt=False)
        self.current_project_path = None
        self.set_dirty(False)

    def open_project(self, filepath=None):
        if not self._prompt_to_save():
            return
        if not filepath:
            last_dir = str(Path(self.settings.value('general/lastProjectPath', str(Path.home()))).parent)
            filepath, _ = QFileDialog.getOpenFileName(self, 'Open Project', last_dir, f'MTG Sorter Projects (*.{Config.PROJECT_EXTENSION});;All Files (*)')
        if not filepath:
            return
        if not Path(filepath).exists():
            QMessageBox.warning(self, 'File Not Found', f'The project file could not be found:\n{filepath}')
            self._remove_from_recent_projects(filepath)
            return
        if self.sorter_tab.load_from_project(filepath):
            self.current_project_path = filepath
            self.set_dirty(False)
            self.settings.setValue('general/lastProjectPath', filepath)
            self._add_to_recent_projects(filepath)

    def save_project(self):
        if not self.current_project_path:
            return self.save_project_as()
        if self.sorter_tab.save_to_project(self.current_project_path):
            self.set_dirty(False)
            return True
        return False

    def save_project_as(self):
        filepath, _ = QFileDialog.getSaveFileName(self, 'Save Project As', self.current_project_path or str(Path.home() / 'Untitled.mtgproj'), f'MTG Sorter Projects (*.{Config.PROJECT_EXTENSION});;All Files (*)')
        if not filepath:
            return False
        if self.sorter_tab.save_to_project(filepath):
            self.current_project_path = filepath
            self.set_dirty(False)
            self.settings.setValue('general/lastProjectPath', filepath)
            self._add_to_recent_projects(filepath)
            return True
        return False

    def auto_save_project(self):
        if self._is_dirty and self.current_project_path:
            self.sorter_tab.save_to_project(self.current_project_path, is_auto_save=True)

    def load_settings(self):
        if self.analyzer_tab:
            self.analyzer_tab.set_code_edit.setText(self.settings.value('analyzer/lastSetCode', '', str))
        self.restoreGeometry(self.settings.value('general/geometry', self.saveGeometry()))
        self._update_recent_projects_menu()

    def _prompt_to_load_last_project(self):
        last_project_path = self.settings.value('general/lastProjectPath', None)
        if last_project_path and Path(last_project_path).exists():
            reply = QMessageBox.question(self, 'Reopen Last Project?', f'Would you like to open the last project you were working on?\n\n{last_project_path}', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes:
                self.open_project(filepath=last_project_path)

    def _update_recent_projects_menu(self):
        self.recent_projects_menu.clear()
        recent_files = self.settings.value('recentProjects', [], str)
        if not recent_files:
            action = QAction('No Recent Projects', self)
            action.setEnabled(False)
            self.recent_projects_menu.addAction(action)
            return
        for i, filepath in enumerate(recent_files):
            action = QAction(f'&{i + 1} {Path(filepath).name}', self, triggered=lambda checked, p=filepath: self.open_project(filepath=p))
            self.recent_projects_menu.addAction(action)

    def _add_to_recent_projects(self, filepath: str):
        if not filepath:
            return
        recent_files = self.settings.value('recentProjects', [], str)
        try:
            recent_files.remove(filepath)
        except ValueError:
            pass
        recent_files.insert(0, filepath)
        self.settings.setValue('recentProjects', recent_files[:Config.MAX_RECENT_PROJECTS])
        self._update_recent_projects_menu()

    def _remove_from_recent_projects(self, filepath: str):
        if not filepath:
            return
        recent_files = self.settings.value('recentProjects', [], str)
        try:
            recent_files.remove(filepath)
            self.settings.setValue('recentProjects', recent_files)
            self._update_recent_projects_menu()
        except ValueError:
            pass

    def save_settings(self):
        if self.analyzer_tab:
            self.settings.setValue('analyzer/lastSetCode', self.analyzer_tab.set_code_edit.text())
        self.settings.setValue('general/geometry', self.saveGeometry())

    def _prompt_to_save(self) -> bool:
        if not self._is_dirty:
            return True
        reply = QMessageBox.question(self, 'Unsaved Changes', 'You have unsaved changes. Would you like to save them?', QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if reply == QMessageBox.StandardButton.Save:
            return self.save_project()
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        return True

    def closeEvent(self, event):
        if self._prompt_to_save():
            self.auto_save_timer.stop()
            self.save_settings()

            # Clean up worker threads before exit
            try:
                if hasattr(self.sorter_tab, 'cleanup_workers'):
                    self.sorter_tab.cleanup_workers()
                if hasattr(self.analyzer_tab, 'cleanup_workers'):
                    self.analyzer_tab.cleanup_workers()
            except Exception as e:
                print(f'Error cleaning up workers: {e}')

            self.api.clear_cache()
            event.accept()
        else:
            event.ignore()