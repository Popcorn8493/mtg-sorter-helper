import csv
import pathlib
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTreeWidget, QTreeWidgetItemIterator
from core.models import Card
from core.project_manager import ProjectManager

class SorterExport:

    def __init__(self, parent):
        self.parent = parent

    def export_current_view(self):
        current_tree = self.parent.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget) or current_tree.topLevelItemCount() == 0:
            QMessageBox.information(self.parent, 'No Data', "There's no data to export.")
            return
        filepath, _ = QFileDialog.getSaveFileName(self.parent, 'Save View as CSV', 'sorter_view.csv', 'CSV Files (*.csv)')
        if not filepath:
            return
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([current_tree.headerItem().text(i) for i in range(current_tree.columnCount())])
                iterator = QTreeWidgetItemIterator(current_tree)
                while iterator.value():
                    item = iterator.value()
                    if not item.isHidden():
                        writer.writerow([item.text(i) for i in range(current_tree.columnCount())])
                    iterator += 1
            QMessageBox.information(self.parent, 'Export Success', f'Successfully exported to:\n{filepath}')
        except Exception as e:
            self.parent.handle_file_error('exporting file', e, additional_context=f"filepath: {filepath}, tree_items: {(current_tree.topLevelItemCount() if current_tree else 'None')}")
            QMessageBox.critical(self.parent, 'Export Error', f'Failed to export file: {e}')

    def get_save_data(self) -> dict:
        if not self.parent.all_cards:
            return {}
        progress = {c.scryfall_id: c.sorted_count for c in self.parent.all_cards if c.sorted_count > 0}
        sort_criteria = self.parent._get_sort_order_safely()
        cards_as_dicts = [c.__dict__ for c in self.parent.all_cards]
        return {'metadata': {'version': '1.1', 'app': 'MTGToolkit'}, 'collection': cards_as_dicts, 'progress': progress, 'settings': {'sort_criteria': sort_criteria, 'group_low_count': self.parent.group_low_count_check.isChecked(), 'optimal_grouping': self.parent.optimal_grouping_check.isChecked(), 'group_threshold': self.parent.group_threshold_edit.text()}}

    def save_to_project(self, filepath: str, is_auto_save: bool=False) -> bool:
        save_data = self.get_save_data()
        if not save_data:
            if not is_auto_save:
                QMessageBox.information(self.parent, 'Empty Project', 'Nothing to save. Please import a collection first.')
            return False
        try:
            ProjectManager.save_project(filepath, save_data)
            if not is_auto_save:
                self.parent.show_status_message(f'Project saved to {pathlib.Path(filepath).name}', style='success')
            return True
        except IOError as e:
            QMessageBox.critical(self.parent, 'Save Error', str(e))
            return False

    def load_from_project(self, filepath: str) -> bool:
        try:
            project_data = ProjectManager.load_project(filepath)
            self.parent.clear_project(prompt=False)
            self.parent.all_cards = [Card(**data) for data in project_data.get('collection', [])]
            progress_data = project_data.get('progress', {})
            for card in self.parent.all_cards:
                card.sorted_count = progress_data.get(card.scryfall_id, 0)
            settings = project_data.get('settings', {})
            self.parent.group_low_count_check.setChecked(settings.get('group_low_count', True))
            self.parent.optimal_grouping_check.setChecked(settings.get('optimal_grouping', False))
            self.parent.group_threshold_edit.setText(settings.get('group_threshold', '20'))
            self.parent.selected_list.clear()
            self.parent.available_list.clear()
            self.parent.available_list.addItems(['Set', 'Color Identity', 'Rarity', 'Type Line', 'First Letter', 'Name', 'Condition', 'Commander Staple'])
            saved_criteria = settings.get('sort_criteria', [])
            for item_text in saved_criteria:
                items_to_move = self.parent.available_list.findItems(item_text, Qt.MatchFlag.MatchExactly)
                if items_to_move:
                    self.parent.selected_list.addItem(self.parent.available_list.takeItem(self.parent.available_list.row(items_to_move[0])))
            self.parent.file_label.setText(f'Loaded {len(self.parent.all_cards)} unique cards from {pathlib.Path(filepath).name}')
            QTimer.singleShot(100, self.parent._start_plan_generation)
            return True
        except IOError as e:
            QMessageBox.critical(self.parent, 'Load Project Error', str(e))
            self.parent.clear_project(prompt=False)
            return False