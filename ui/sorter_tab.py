from typing import Dict, List
from PyQt6.QtCore import QTimer, Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import QApplication, QTreeWidgetItem, QTreeWidgetItemIterator, QWidget, QVBoxLayout
from api.mtgjson_api import MTGJsonAPI
from core.decorators import safe_ui_method, safe_cleanup_method
from core.models import Card, SortGroup
from ui.custom_widgets import EmptyState, NavigableTreeWidget
from ui.debug_logger import SorterTabDebugger, DebugLevel, DebugManager
from ui.set_sorter_view import SetSorterView
from ui.sorter_export import SorterExport
from ui.sorter_handlers import SorterHandlers
from ui.sorter_import import SorterImport
from ui.sorter_navigation import SorterNavigation
from ui.sorter_preview import SorterPreview
from ui.sorter_tab_ui import SorterTabUi
from workers.threads import WorkerManager
from .status_manager import StatusAwareMixin

class ManaBoxSorterTab(QWidget, StatusAwareMixin):
    collection_loaded = Signal()
    progress_updated = Signal(int)
    project_modified = Signal()
    operation_started = Signal(str, int)
    operation_finished = Signal()

    def __init__(self, api: MTGJsonAPI):
        super().__init__()
        self.api = api
        self.all_cards: List[Card] = []
        self.worker_manager = WorkerManager()
        self.import_thread = None
        self.import_worker = None
        self.sort_order: List[str] = []
        self.last_csv_path: str | None = None
        self.progress_to_load: Dict | None = None
        self.is_loading = False
        self.preview_card: Card | None = None
        self.splitter_sizes = [700, 350]
        self.ui: SorterTabUi | None = None
        self._is_refreshing = False
        self._is_destroyed = False
        self._is_navigating = False
        self._is_generating_plan = False
        self.debugger = DebugManager.get_sorter_debugger()
        self.handlers = SorterHandlers(self)
        self.navigation = SorterNavigation(self)
        self.preview = SorterPreview(self)
        self.export = SorterExport(self)
        self.import_module = SorterImport(self)
        QVBoxLayout(self)
        self.setup_ui()

    def cleanup_workers(self):
        """Clean up all worker threads before shutdown."""
        try:
            self.worker_manager.cleanup_all()
        except Exception as e:
            print(f'Error cleaning up worker manager: {e}')

        # Clean up import threads
        try:
            if self.import_worker and hasattr(self.import_worker, 'cancel'):
                self.import_worker.cancel()
        except Exception as e:
            print(f'Error canceling import worker: {e}')

        try:
            if self.import_thread and self.import_thread.isRunning():
                self.import_thread.quit()
                if not self.import_thread.wait(2000):
                    print('Warning: Import thread did not stop gracefully')
                    self.import_thread.terminate()
                    self.import_thread.wait(1000)
        except Exception as e:
            print(f'Error cleaning up import thread: {e}')

    def handle_error(self, operation: str, error: Exception, show_message: bool=True, message_timeout: int=5000, log_prefix: str='ERROR', error_category: str='GENERAL', additional_context: str=None) -> None:
        try:
            context_info = f' | Context: {additional_context}' if additional_context else ''
            error_type = type(error).__name__
            timestamp = __import__('datetime').datetime.now().strftime('%H:%M:%S')
            print(f'[{timestamp}] {log_prefix}[{error_category}]: {operation} failed')
            print(f'  Error Type: {error_type}')
            print(f'  Error Message: {error}')
            if context_info:
                print(f'  {context_info}')
            import traceback
            traceback.print_exc()
            if show_message and hasattr(self, 'show_status_message'):
                error_msg = str(error)
                if len(error_msg) > 100:
                    error_msg = error_msg[:97] + '...'
                if error_category == 'CRITICAL':
                    error_msg = f'Critical Error: {error_msg}'
                elif error_category == 'UI':
                    error_msg = f'Interface Error: {error_msg}'
                elif error_category == 'BACKGROUND':
                    error_msg = f'Background Task Error: {error_msg}'
                self.show_status_message(f'Error: {error_msg}', message_timeout, style='error')
        except Exception as handler_error:
            print(f'CRITICAL: Error handler itself failed: {handler_error}')
            import traceback
            traceback.print_exc()

    def handle_silent_error(self, operation: str, error: Exception, log_prefix: str='ERROR', error_category: str='SILENT', additional_context: str=None) -> None:
        self.handle_error(operation, error, show_message=False, log_prefix=log_prefix, error_category=error_category, additional_context=additional_context)

    def handle_ui_error(self, operation: str, error: Exception, show_message: bool=True, additional_context: str=None) -> None:
        self.handle_error(operation, error, show_message=show_message, log_prefix='[UI]', error_category='UI', additional_context=additional_context)

    def handle_background_error(self, operation: str, error: Exception, show_message: bool=False, additional_context: str=None) -> None:
        self.handle_error(operation, error, show_message=show_message, log_prefix='[Background]', error_category='BACKGROUND', additional_context=additional_context)

    def handle_critical_error(self, operation: str, error: Exception, show_message: bool=True, additional_context: str=None) -> None:
        self.handle_error(operation, error, show_message=show_message, log_prefix='[CRITICAL]', error_category='CRITICAL', additional_context=additional_context)

    def handle_network_error(self, operation: str, error: Exception, show_message: bool=True, additional_context: str=None) -> None:
        context = f"Network operation failed{(': ' + additional_context if additional_context else '')}"
        self.handle_error(operation, error, show_message=show_message, log_prefix='[Network]', error_category='NETWORK', additional_context=context)

    def handle_file_error(self, operation: str, error: Exception, show_message: bool=True, additional_context: str=None) -> None:
        context = f"File operation failed{(': ' + additional_context if additional_context else '')}"
        self.handle_error(operation, error, show_message=show_message, log_prefix='[File]', error_category='FILE', additional_context=context)

    def cleanup_widget(self):
        if self._is_destroyed:
            return
        self._is_destroyed = True
        self.cleanup_workers()

    def __del__(self):
        self.cleanup_widget()

    def closeEvent(self, event):
        self.cleanup_widget()
        super().closeEvent(event)

    def setup_ui(self):
        self.ui = SorterTabUi(self)
        self.ui.setup_ui(self.layout())
        StatusAwareMixin.__init__(self)
        self._init_status_manager()
        self._show_empty_state()

    @safe_ui_method('Plan generation failed')
    def _start_plan_generation(self):
        if self._is_destroyed or self._is_generating_plan:
            return
        self.start_new_plan_generation()

    def start_new_plan_generation(self):
        if not self.all_cards:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, 'No Collection', 'Please import a collection first.')
            return
        if self._is_generating_plan:
            return
        self._is_generating_plan = True
        try:
            self._hide_empty_state()
            self.navigation.clear_layout(self.breadcrumb_layout)
            self._clear_stack()
            self.preview.reset_preview_pane()
            self.navigation.add_breadcrumb('Home', 0)
            self.navigation.create_new_view(self.all_cards, 0)
            self.handlers.update_button_visibility()
            self.filter_edit.setVisible(True)
        except Exception as e:
            self.handle_critical_error('start_new_plan_generation', e, additional_context=f'cards_count: {(len(self.all_cards) if self.all_cards else 0)}, generating: {self._is_generating_plan}')
        finally:
            self._is_generating_plan = False

    @safe_cleanup_method('Stack clearing failed')
    def _clear_stack(self):
        while self.results_stack.count() > 0:
            widget = self.results_stack.widget(0)
            self.results_stack.removeWidget(widget)
            if widget:
                if hasattr(widget, 'cleanup'):
                    widget.cleanup()
                widget.deleteLater()
        QApplication.processEvents()

    def _show_empty_state(self):
        if self._is_destroyed:
            return
        try:
            self._clear_stack()
            empty_state = EmptyState(title='No Collection Loaded', message="Import a collection CSV file to begin organizing your cards. ManaBox and Lion's Eye Diamond formats are supported.", action_text='Import Collection', action_callback=self.import_csv)
            self.results_stack.addWidget(empty_state)
            self.results_stack.setCurrentWidget(empty_state)
            self.preview_panel.setVisible(False)
            self.filter_edit.setVisible(False)
        except Exception as e:
            self.handle_ui_error('showing empty state', e)

    def _hide_empty_state(self):
        if self._is_destroyed:
            return
        try:
            current_widget = self.results_stack.currentWidget()
            if isinstance(current_widget, EmptyState):
                self._clear_stack()
        except Exception as e:
            self.handle_ui_error('hiding empty state', e)

    def _refresh_current_view(self):
        if self._is_destroyed or self._is_refreshing:
            return
        self._is_refreshing = True
        try:
            current_widget = self.results_stack.currentWidget()
            if isinstance(current_widget, SetSorterView):
                current_widget._safe_regenerate_plan()
                self._is_refreshing = False
                return
            if not isinstance(current_widget, NavigableTreeWidget):
                if self.all_cards and (not self._is_generating_plan):
                    QTimer.singleShot(200, self._start_plan_generation)
                self._is_refreshing = False
                return
            level = self.results_stack.currentIndex()
            cards_to_process = getattr(current_widget, 'cards_for_view', self.all_cards)
            self.sort_order = self._get_sort_order_safely()
            criterion = self.sort_order[level] if 0 <= level < len(self.sort_order) else None
            nodes = self.navigation._generate_level_breakdown(cards_to_process, criterion)
            expanded_items = {item.text(0) for item in self._get_expanded_items(current_widget)}
            selected_items = {item.text(0) for item in current_widget.selectedItems()}
            current_item_text = current_widget.currentItem().text(0) if current_widget.currentItem() else None
            scroll_position = current_widget.verticalScrollBar().value()
            current_widget.setUpdatesEnabled(False)
            current_widget.clear()

            def on_population_finished():
                if self._is_destroyed:
                    self._is_refreshing = False
                    return
                try:
                    show_sorted = self.show_sorted_check.isChecked()
                    header_label = 'Total Count' if show_sorted else 'Unsorted Count'
                    current_widget.setHeaderLabels(['Group', header_label])
                    self._restore_tree_state(current_widget, expanded_items, selected_items, current_item_text, scroll_position)
                    current_widget.setUpdatesEnabled(True)
                except Exception as e:
                    self.handle_silent_error('post-population refresh', e)
                finally:
                    self._is_refreshing = False
                    self.handlers.update_button_visibility()
                    self._update_view_layout()
            current_widget._populate_tree_progressively(nodes, on_finished=on_population_finished)
        except Exception as e:
            self.handle_ui_error('_refresh_current_view setup', e, additional_context=f'destroyed: {self._is_destroyed}, refreshing: {self._is_refreshing}')
            self._is_refreshing = False

    def _get_expanded_items(self, tree_widget):
        expanded = []
        try:
            iterator = QTreeWidgetItemIterator(tree_widget)
            while iterator.value():
                item = iterator.value()
                if item.isExpanded():
                    expanded.append(item)
                iterator += 1
        except:
            pass
        return expanded

    def _restore_tree_state(self, tree_widget, expanded_items, selected_items, current_item_text, scroll_position):
        tree_widget.blockSignals(True)
        try:
            iterator = QTreeWidgetItemIterator(tree_widget)
            while iterator.value():
                item = iterator.value()
                item_text = item.text(0)
                if item_text in expanded_items:
                    item.setExpanded(True)
                if item_text in selected_items:
                    item.setSelected(True)
                if item_text == current_item_text:
                    tree_widget.setCurrentItem(item)
                iterator += 1
        except Exception as e:
            self.handle_silent_error('restoring tree state', e)
        finally:
            tree_widget.blockSignals(False)
            if tree_widget.currentItem():
                self.handlers.on_tree_selection_changed(tree_widget.currentItem(), None)
            QTimer.singleShot(50, lambda: tree_widget.verticalScrollBar().setValue(scroll_position))

    def _update_sorted_item_visibility(self):
        if self._is_destroyed:
            return
        try:
            current_widget = self.results_stack.currentWidget()
            if not isinstance(current_widget, NavigableTreeWidget):
                return
            show_sorted = self.show_sorted_check.isChecked()
            iterator = QTreeWidgetItemIterator(current_widget)
            while iterator.value():
                item = iterator.value()
                if item:
                    is_sorted = item.checkState(0) == Qt.CheckState.Checked
                    if is_sorted:
                        item.setHidden(not show_sorted)
                    else:
                        item.setHidden(False)
                iterator += 1
        except Exception as e:
            self.handle_silent_error('updating sorted item visibility', e)

    def _update_view_layout(self):
        self.preview_panel.setVisible(True)
        if not self.preview_panel.isVisible():
            self.main_splitter.setSizes(self.splitter_sizes)

    def _check_level_completion(self, item: QTreeWidgetItem):
        if self._is_destroyed:
            return
        try:
            current_widget = self.results_stack.currentWidget()
            if not isinstance(current_widget, NavigableTreeWidget):
                return
            all_cards_in_level = getattr(current_widget, 'cards_for_view', [])
            if not all_cards_in_level:
                return
            all_sorted = all((c.is_fully_sorted for c in all_cards_in_level))
            if all_sorted:
                current_level = self.results_stack.currentIndex()
                sort_order = self._get_sort_order_safely()
                if current_level >= len(sort_order) - 1:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.information(self, 'Level Complete!', f'Congratulations! All cards in this group have been sorted.\n\nYou can now navigate back to continue with other groups.')
                else:
                    next_criterion = sort_order[current_level + 1] if current_level + 1 < len(sort_order) else 'Next Level'
                    reply = QMessageBox.question(self, 'Level Complete!', f'All cards in this level have been sorted!\n\nWould you like to advance to the next level ({next_criterion})?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
                    if reply == QMessageBox.StandardButton.Yes:
                        self.show_status_message(f' Advancing to {next_criterion} level...', 3000, style='info')
        except Exception as e:
            self.handle_silent_error('_check_level_completion', e)

    def _mark_cards_as_sorted(self, item: QTreeWidgetItem) -> bool:
        cards_to_mark = self.navigation._get_cards_from_item(item)
        if not cards_to_mark:
            self.show_status_message(' Could not find cards for this group.', style='warning')
            return False
        for card in cards_to_mark:
            card.sorted_count = card.quantity
        return True

    def show_status_message(self, message: str, timeout: int=2500, style: str='auto'):
        super().show_status_message(message, timeout, style)

    def handle_item_click(self, item: QTreeWidgetItem, next_level: int):
        return self.handlers.handle_item_click(item, next_level)

    def drill_down(self, item: QTreeWidgetItem, next_level: int):
        return self.handlers.drill_down(item, next_level)

    def on_show_sorted_toggled(self):
        return self.handlers.on_show_sorted_toggled()

    def on_tree_selection_changed(self, current, previous):
        return self.handlers.on_tree_selection_changed(current, previous)

    def on_item_sorted_toggled(self, item: QTreeWidgetItem, is_sorted: bool):
        return self.handlers.on_item_sorted_toggled(item, is_sorted)

    def on_mark_group_button_clicked(self):
        return self.handlers.on_mark_group_button_clicked()

    def mark_item_as_sorted(self, item: QTreeWidgetItem):
        return self.handlers.mark_item_as_sorted(item)

    def filter_current_view(self, text: str):
        return self.handlers.filter_current_view(text)

    def update_button_visibility(self, *args):
        return self.handlers.update_button_visibility(*args)

    def add_criterion(self, item):
        return self.handlers.add_criterion(item)

    def remove_criterion(self, item):
        return self.handlers.remove_criterion(item)

    def update_progress(self, value, total):
        return self.handlers.update_progress(value, total)

    def add_breadcrumb(self, text: str, level: int):
        return self.navigation.add_breadcrumb(text, level)

    def navigate_to_level(self, level: int):
        return self.navigation.navigate_to_level(level)

    def navigate_and_refresh(self, level: int):
        return self.navigation.navigate_and_refresh(level)

    def create_new_view(self, cards_in_group: List[Card], level: int):
        return self.navigation.create_new_view(cards_in_group, level)

    def create_set_sorter_view(self, cards_to_sort: List[Card], set_name: str):
        return self.navigation.create_set_sorter_view(cards_to_sort, set_name)

    def _generate_level_breakdown(self, current_cards: List[Card], criterion: str | None) -> List[SortGroup]:
        return self.navigation._generate_level_breakdown(current_cards, criterion)

    def _get_nested_value(self, card: Card, key: str) -> str:
        return self.navigation._get_nested_value(card, key)

    def _get_cards_from_item(self, item: QTreeWidgetItem) -> List[Card]:
        return self.navigation._get_cards_from_item(item)

    def _get_sort_order_safely(self) -> List[str]:
        return self.navigation._get_sort_order_safely()

    def _should_show_card_preview(self, item: QTreeWidgetItem, next_level: int) -> bool:
        return self.navigation._should_show_card_preview(item, next_level)

    def _should_show_card_preview_for_selection(self, item: QTreeWidgetItem) -> bool:
        return self.navigation._should_show_card_preview_for_selection(item)

    def clear_layout(self, layout):
        return self.navigation.clear_layout(layout)

    def reset_preview_pane(self, *args):
        return self.preview.reset_preview_pane(*args)

    def update_card_preview(self, item: QTreeWidgetItem):
        return self.preview.update_card_preview(item)


    def export_current_view(self):
        return self.export.export_current_view()

    def get_save_data(self) -> dict:
        return self.export.get_save_data()

    def save_to_project(self, filepath: str, is_auto_save: bool=False) -> bool:
        return self.export.save_to_project(filepath, is_auto_save)

    def load_from_project(self, filepath: str) -> bool:
        return self.export.load_from_project(filepath)

    def import_csv(self, filepath=None):
        return self.import_module.import_csv(filepath)

    def clear_project(self, prompt=True):
        return self.import_module.clear_project(prompt)

    def reset_sort_progress(self):
        return self.import_module.reset_sort_progress()

    def on_import_finished(self, cards: List[Card]):
        return self.import_module.on_import_finished(cards)

    def on_import_error(self, error_message: str):
        return self.import_module.on_import_error(error_message)

    def get_debug_stats(self) -> Dict:
        """Get debug statistics for this tab."""
        return self.debugger.get_stats()