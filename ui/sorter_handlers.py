from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator
from ui.custom_widgets import NavigableTreeWidget
from ui.set_sorter_view import SetSorterView

class SorterHandlers:

    def __init__(self, parent):
        self.parent = parent

    def handle_item_click(self, item: QTreeWidgetItem, next_level: int):
        if self.parent._is_destroyed or not item:
            return
        try:
            if self.parent._should_show_card_preview(item, next_level):
                self.parent.update_card_preview(item)
            else:
                self.parent.reset_preview_pane()
            self.parent.sort_order = self.parent._get_sort_order_safely()
            current_level = next_level - 1
            current_widget = self.parent.results_stack.currentWidget()
            if isinstance(current_widget, SetSorterView):
                cards_in_pile = self.parent._get_cards_from_item(item)
                if cards_in_pile:
                    self.parent.navigate_to_level(self.parent.results_stack.currentIndex())
                    breadcrumb_text = item.text(0)
                    self.parent.add_breadcrumb(breadcrumb_text, next_level)
                    final_level = len(self.parent.sort_order)
                    self.parent.create_new_view(cards_in_pile, final_level)
                    self.parent.update_button_visibility()
                    return
            if 0 <= current_level < len(self.parent.sort_order) and self.parent.sort_order[current_level] == 'Name':
                return
            self.parent.show_status_message(f"Drilling down into '{item.text(0).split(': ')[-1]}'...", 2000, style='info')
            self.parent.drill_down(item, next_level)
        except Exception as e:
            self.parent.handle_ui_error('handle_item_click', e, additional_context=f"item: {(item.text(0) if item else 'None')}, level: {next_level}")

    def drill_down(self, item: QTreeWidgetItem, next_level: int):
        if self.parent._is_destroyed or not item or self.parent._is_navigating:
            return
        try:
            self.parent._is_navigating = True
            self.parent.sort_order = self.parent._get_sort_order_safely()
            if not self.parent.sort_order:
                self.parent.show_status_message('Configuration error: Sort criteria not available.', 3000, style='error')
                return
            if next_level > len(self.parent.sort_order):
                self.parent.show_status_message('Cannot drill down further - no more sort criteria available.', 3000, style='warning')
                return
            current_level_index = next_level - 1
            if 0 <= current_level_index < len(self.parent.sort_order):
                current_criterion = self.parent.sort_order[current_level_index]
                next_criterion = self.parent.sort_order[next_level] if next_level < len(self.parent.sort_order) else None
                if current_criterion == 'Set' and next_criterion == 'First Letter':
                    cards_in_set = self.parent._get_cards_from_item(item)
                    if not cards_in_set:
                        self.parent.show_status_message('No cards found in selected set.', 2000, style='warning')
                        return
                    self.parent.navigate_to_level(current_level_index)
                    breadcrumb_text = item.text(0).split(': ')[-1]
                    self.parent.add_breadcrumb(f'{breadcrumb_text} (Letter Sort)', next_level)
                    self.parent.create_set_sorter_view(cards_in_set, breadcrumb_text)
                    return
            cards_in_group = self.parent._get_cards_from_item(item)
            if not cards_in_group:
                self.parent.show_status_message('No cards found in selected group.', 2000, style='warning')
                return
            try:
                self.parent.navigate_to_level(next_level - 1)
            except Exception as nav_error:
                print(f'ERROR: Navigation failed: {nav_error}')
                import traceback
                traceback.print_exc()
                self.parent.show_status_message('Navigation error occurred.', 3000, style='error')
                return
            try:
                breadcrumb_text = item.text(0).split(': ')[-1]
                self.parent.add_breadcrumb(breadcrumb_text, next_level)
            except Exception as breadcrumb_error:
                print(f'ERROR: Breadcrumb creation failed: {breadcrumb_error}')
            try:
                self.parent.create_new_view(cards_in_group, next_level)
            except Exception as create_error:
                print(f'ERROR: View creation failed: {create_error}')
                import traceback
                traceback.print_exc()
                self.parent.show_status_message('Failed to create view for next level.', 3000, style='error')
                return
            try:
                self.parent.update_button_visibility()
            except Exception as button_error:
                print(f'ERROR: Button visibility update failed: {button_error}')
        except Exception as e:
            self.parent.handle_ui_error('drill_down', e, additional_context=f"item: {(item.text(0) if item else 'None')}, level: {next_level}, navigating: {self.parent._is_navigating}")
        finally:
            self.parent._is_navigating = False

    def on_show_sorted_toggled(self):
        if not self.parent._is_destroyed and (not self.parent._is_refreshing):
            self.parent._update_sorted_item_visibility()
            QTimer.singleShot(100, self.parent._refresh_current_view)

    def on_tree_selection_changed(self, current, previous):
        if current:
            if self.parent._should_show_card_preview_for_selection(current):
                self.parent.update_card_preview(current)
            else:
                self.parent.reset_preview_pane()
        else:
            self.parent.reset_preview_pane()

    def on_item_sorted_toggled(self, item: QTreeWidgetItem, is_sorted: bool):
        if self.parent._is_destroyed or not item:
            return
        try:
            cards = self.parent._get_cards_from_item(item)
            if not cards:
                self.parent.show_status_message(' Could not find cards for this group.', style='warning')
                return
            for card in cards:
                if is_sorted:
                    card.sorted_count = card.quantity
                else:
                    card.sorted_count = 0
            current_widget = self.parent.results_stack.currentWidget()
            if isinstance(current_widget, NavigableTreeWidget):
                current_widget.set_item_sorted_state(item, is_sorted)
            show_sorted = self.parent.show_sorted_check.isChecked()
            if is_sorted and (not show_sorted):
                item.setHidden(True)
            else:
                item.setHidden(False)
            action = 'SORTED' if is_sorted else 'UNSORTED'
            self.parent.show_status_message(f" Marked '{item.text(0)}' as {action}.", style='success')
            self.parent.project_modified.emit()
        except Exception as e:
            self.parent.handle_ui_error('on_item_sorted_toggled', e)

    def on_mark_group_button_clicked(self):
        current_tree = self.parent.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget):
            return
        selected_items = current_tree.selectedItems()
        if not selected_items:
            QMessageBox.information(self.parent, 'No Selection', 'Please select one or more groups to mark as sorted.')
            return
        total_cards_affected = 0
        for item in selected_items:
            cards_to_mark = self.parent._get_cards_from_item(item)
            for card in cards_to_mark:
                total_cards_affected += max(0, card.quantity - card.sorted_count)
        if total_cards_affected == 0:
            QMessageBox.information(self.parent, 'Already Sorted', 'All selected groups are already completely sorted.')
            return
        if QMessageBox.question(self.parent, 'Confirm Mark as Sorted', f'Mark {total_cards_affected} cards as sorted?') == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                self.parent._mark_cards_as_sorted(item)
            self.parent.show_status_message(f'Marked {len(selected_items)} groups as sorted ({total_cards_affected} cards)', style='success')
            self.parent.project_modified.emit()
            QTimer.singleShot(50, self.parent._refresh_current_view)

    def mark_item_as_sorted(self, item: QTreeWidgetItem):
        cards = self.parent._get_cards_from_item(item)
        if not cards:
            self.parent.show_status_message(' Could not find cards for this group.', style='warning')
            return
        is_already_sorted = all((c.is_fully_sorted for c in cards))
        for card in cards:
            if is_already_sorted:
                card.sorted_count = 0
            else:
                card.sorted_count = card.quantity
        if is_already_sorted:
            self.parent.show_status_message(f" Group '{item.text(0)}' marked as UNSORTED.", style='warning')
        else:
            self.parent.show_status_message(f" Group '{item.text(0)}' marked as SORTED.", style='success')
            QTimer.singleShot(100, lambda: self.parent._check_level_completion(item))
        self.parent.project_modified.emit()
        QTimer.singleShot(50, self.parent._refresh_current_view)

    def filter_current_view(self, text: str):
        current_widget = self.parent.results_stack.currentWidget()
        tree_to_filter = None
        if isinstance(current_widget, QTreeWidget):
            tree_to_filter = current_widget
        elif isinstance(current_widget, SetSorterView) and hasattr(current_widget, 'tree'):
            tree_to_filter = current_widget.tree
        if tree_to_filter:
            iterator = QTreeWidgetItemIterator(tree_to_filter, QTreeWidgetItemIterator.IteratorFlag.All)
            while iterator.value():
                item = iterator.value()
                item.setHidden(text.lower() not in item.text(0).lower())
                iterator += 1

    def update_button_visibility(self, *args):
        is_normal_view = isinstance(self.parent.results_stack.currentWidget(), NavigableTreeWidget)
        self.parent.mark_sorted_button.setVisible(is_normal_view)
        self.parent.export_button.setVisible(is_normal_view)

    def add_criterion(self, item):
        self.parent.selected_list.addItem(self.parent.available_list.takeItem(self.parent.available_list.row(item)))
        self.parent.project_modified.emit()

    def remove_criterion(self, item):
        self.parent.available_list.addItem(self.parent.selected_list.takeItem(self.parent.selected_list.row(item)))
        self.parent.project_modified.emit()

    def update_progress(self, value, total):
        if self.parent.progress_bar.maximum() != total:
            self.parent.progress_bar.setRange(0, total)
            self.parent.operation_started.emit(f'Fetching card data', total)
        self.parent.progress_bar.setValue(value)
        self.parent.file_label.setText(f'Fetching card data: {value}/{total}')
        self.parent.progress_updated.emit(value)