import csv
import pathlib
import collections
import string
from typing import Dict, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QListWidget, QCheckBox,
    QGroupBox, QFileDialog, QMessageBox, QProgressBar, QStackedWidget, QSplitter,
    QTreeWidgetItem, QTreeWidgetItemIterator, QHeaderView, QTreeWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from api.scryfall_api import ScryfallAPI
from workers.threads import CsvImportWorker, ImageFetchWorker
from ui.custom_widgets import SortableTreeWidgetItem, NavigableTreeWidget
from core.models import Card, SortGroup


class ManaBoxSorterTab(QWidget):
    def __init__(self, api: ScryfallAPI):
        super().__init__()
        self.api = api
        self.all_cards: List[Card] = []
        self.worker = None
        self.sort_order: List[str] = []
        self.current_loading_id: str | None = None

        main_layout = QVBoxLayout(self)
        self._create_import_section(main_layout)
        self._create_options_section(main_layout)
        self._create_run_section(main_layout)
        self._create_results_section(main_layout)

    def _create_import_section(self, layout: QVBoxLayout):
        group = QGroupBox("1. Import Collection")
        layout.addWidget(group)
        group_layout = QVBoxLayout(group)
        self.import_button = QPushButton("Import ManaBox CSV")
        self.import_button.setObjectName("AccentButton")
        self.import_button.clicked.connect(self.import_csv)
        self.file_label = QLabel("No file loaded.")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        group_layout.addWidget(self.import_button)
        group_layout.addWidget(self.file_label)
        group_layout.addWidget(self.progress_bar)

    def _create_options_section(self, layout: QVBoxLayout):
        options_group = QGroupBox("2. Sorting Options")
        options_layout = QHBoxLayout(options_group)
        layout.addWidget(options_group)

        # Sorting Order Group
        sort_order_group = QGroupBox("Sort Order")
        options_layout.addWidget(sort_order_group, 2)
        grid = QGridLayout(sort_order_group)
        self.available_list = QListWidget()
        self.available_list.addItems(
            ["Set", "Color Identity", "Rarity", "Type Line", "Name", "Condition", "Commander Staple"])
        self.selected_list = QListWidget()
        add_button = QPushButton(">>")
        add_button.clicked.connect(self.add_criterion)
        remove_button = QPushButton("<<")
        remove_button.clicked.connect(self.remove_criterion)
        up_button = QPushButton("Up")
        up_button.clicked.connect(self.move_up)
        down_button = QPushButton("Down")
        down_button.clicked.connect(self.move_down)
        btn_layout = QVBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(add_button)
        btn_layout.addWidget(remove_button)
        btn_layout.addStretch()
        side_btn_layout = QVBoxLayout()
        side_btn_layout.addStretch()
        side_btn_layout.addWidget(up_button)
        side_btn_layout.addWidget(down_button)
        side_btn_layout.addStretch()
        grid.addWidget(self.available_list, 0, 0)
        grid.addLayout(btn_layout, 0, 1)
        grid.addWidget(self.selected_list, 0, 2)
        grid.addLayout(side_btn_layout, 0, 3)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)

        # Set Sorting Plan Group
        set_plan_group = QGroupBox("Set Sorting Plan")
        options_layout.addWidget(set_plan_group, 1)
        set_plan_layout = QVBoxLayout(set_plan_group)
        self.group_low_count_check = QCheckBox("Group low-count letters into piles")
        self.group_low_count_check.setChecked(True)
        set_plan_layout.addWidget(self.group_low_count_check)
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Min pile total:"))
        self.group_threshold_edit = QLineEdit("20")
        threshold_layout.addWidget(self.group_threshold_edit)
        set_plan_layout.addLayout(threshold_layout)
        set_plan_layout.addStretch()

    def _create_run_section(self, layout: QVBoxLayout):
        group = QGroupBox("3. Generate Plan")
        layout.addWidget(group)
        h_layout = QHBoxLayout(group)
        h_layout.addStretch()
        self.run_button = QPushButton("Generate Sorting Plan")
        self.run_button.clicked.connect(self.generate_plan)
        h_layout.addWidget(self.run_button)
        h_layout.addStretch()

    def _create_results_section(self, layout: QVBoxLayout):
        group = QGroupBox("4. Sorting Plan")
        layout.addWidget(group)
        results_layout = QVBoxLayout(group)
        top_bar_layout = QHBoxLayout()
        self.breadcrumb_layout = QHBoxLayout()
        self.breadcrumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        top_bar_layout.addLayout(self.breadcrumb_layout, 1)

        self.sort_set_button = QPushButton("Sort This Set")
        self.sort_set_button.clicked.connect(self.on_sort_set_clicked)
        self.sort_set_button.setVisible(False)
        top_bar_layout.addWidget(self.sort_set_button)

        self.mark_sorted_button = QPushButton("Mark Group as Sorted")
        self.mark_sorted_button.clicked.connect(self.on_mark_group_button_clicked)
        self.mark_sorted_button.setVisible(False)
        top_bar_layout.addWidget(self.mark_sorted_button)

        self.export_button = QPushButton("Export View")
        self.export_button.clicked.connect(self.export_current_view)
        self.export_button.setVisible(False)
        top_bar_layout.addWidget(self.export_button)
        results_layout.addLayout(top_bar_layout)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter current view...")
        self.filter_edit.textChanged.connect(self.filter_current_view)
        self.filter_edit.setVisible(False)
        self.results_stack = QStackedWidget()
        left_layout.addWidget(self.filter_edit)
        left_layout.addWidget(self.results_stack)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.card_image_label = QLabel("Double-click a card to see its image.")
        self.card_image_label.setObjectName("CardImageLabel")
        self.card_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.card_image_label.setMinimumSize(220, 308)
        self.card_details_label = QLabel()
        self.card_details_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.card_details_label.setWordWrap(True)
        right_layout.addWidget(self.card_image_label)
        right_layout.addWidget(self.card_details_label)
        right_layout.addStretch()

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([700, 350])
        results_layout.addWidget(main_splitter)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        results_layout.addWidget(self.status_label)

        layout.setStretchFactor(group, 1)

    def import_csv(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Open ManaBox CSV", "", "CSV Files (*.csv)")
        if not filepath: return
        self.import_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.file_label.setText(f"Loading {pathlib.Path(filepath).name}...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.worker = CsvImportWorker(filepath, self.api)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_import_finished)
        self.worker.error.connect(self.on_import_error)
        self.worker.start()

    def update_progress(self, value, total):
        if self.progress_bar.maximum() != total: self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(value)
        self.file_label.setText(f"Fetching card data: {value}/{total}")

    def on_import_finished(self, cards: List[Card]):
        self.all_cards = cards
        self.file_label.setText(f"Loaded and enriched {len(self.all_cards)} unique cards.")
        self.progress_bar.setVisible(False)
        self.import_button.setEnabled(True)
        self.run_button.setEnabled(True)
        QMessageBox.information(self, "Success", f"Successfully imported data for {len(self.all_cards)} cards.")
        self.generate_plan()

    def on_import_error(self, error_message: str):
        self.file_label.setText("Import failed.")
        self.progress_bar.setVisible(False)
        self.import_button.setEnabled(True)
        self.run_button.setEnabled(True)
        QMessageBox.critical(self, "Import Error", error_message)

    def add_criterion(self):
        if item := self.available_list.currentItem():
            self.selected_list.addItem(self.available_list.takeItem(self.available_list.row(item)))

    def remove_criterion(self):
        if item := self.selected_list.currentItem():
            self.available_list.addItem(self.selected_list.takeItem(self.selected_list.row(item)))

    def move_up(self):
        if (row := self.selected_list.currentRow()) > 0:
            item = self.selected_list.takeItem(row)
            self.selected_list.insertItem(row - 1, item)
            self.selected_list.setCurrentRow(row - 1)

    def move_down(self):
        if (row := self.selected_list.currentRow()) < self.selected_list.count() - 1:
            item = self.selected_list.takeItem(row)
            self.selected_list.insertItem(row + 1, item)
            self.selected_list.setCurrentRow(row + 1)

    def generate_plan(self):
        if not self.all_cards:
            QMessageBox.warning(self, "No Data", "Please import a collection first.")
            return
        self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
        if not self.sort_order:
            QMessageBox.warning(self, "No Criteria", "Please select at least one sorting criterion.")
            return

        unsorted_cards = [card for card in self.all_cards if card.quantity > card.sorted_count]

        self.clear_layout(self.breadcrumb_layout)
        while self.results_stack.count() > 0:
            widget = self.results_stack.widget(0)
            self.results_stack.removeWidget(widget)
            widget.deleteLater()

        self.reset_preview_pane()

        if not unsorted_cards:
            self.show_status_message("Sorting Complete!", 5000)
            self.export_button.setVisible(False)
            self.mark_sorted_button.setVisible(False)
            self.filter_edit.setVisible(False)
            return

        self.add_breadcrumb("Home", 0)
        self.create_new_view(unsorted_cards, 0)
        self.filter_edit.setVisible(True)
        self.update_button_visibility()

    def create_new_view(self, cards_in_group: List[Card], level: int):
        tree = NavigableTreeWidget()
        tree.setHeaderLabels(['Group', 'Unsorted Count'])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.setSortingEnabled(True)
        tree.itemDoubleClicked.connect(lambda item: self.handle_item_double_click(item, level + 1))
        tree.navigateUpRequested.connect(lambda: self.navigate_to_level(level - 1) if level > 0 else None)
        tree.currentItemChanged.connect(self.update_button_visibility)
        tree.currentItemChanged.connect(self.reset_preview_pane)

        criterion = self.sort_order[level] if level < len(self.sort_order) else None
        nodes = self._generate_level_breakdown(cards_in_group, criterion)
        self._populate_tree(tree.invisibleRootItem(), nodes)

        self.results_stack.addWidget(tree)
        self.results_stack.setCurrentWidget(tree)

    def on_sort_set_clicked(self):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, NavigableTreeWidget): return

        current_item = current_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a set to sort.")
            return

        cards_in_set = self._get_cards_from_item(current_item)
        unsorted_cards = [c for c in cards_in_set if c.quantity > c.sorted_count]

        if not unsorted_cards:
            self.show_status_message("All cards in this set are already sorted.")
            return

        level = self.results_stack.currentIndex()
        next_level = level + 1

        self.navigate_to_level(level)

        self.add_breadcrumb(f"{current_item.text(0)} (Sorting)", next_level)
        self.create_set_sorter_view(unsorted_cards, current_item.text(0))
        self.update_button_visibility()

    def create_set_sorter_view(self, cards_to_sort: List[Card], set_name: str):
        view_widget = QWidget()

        layout = QVBoxLayout(view_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        chart_group = QGroupBox(f"Optimal Sort Plan for {set_name}")
        chart_layout = QVBoxLayout(chart_group)
        canvas = FigureCanvas(Figure(facecolor='#2b2b2b'))
        ax = canvas.figure.subplots()
        chart_layout.addWidget(canvas)
        splitter.addWidget(chart_group)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        piles_group = QGroupBox("Sorting Piles")
        piles_layout = QVBoxLayout(piles_group)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Pile", "Unsorted Count"])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.setSortingEnabled(True)
        piles_layout.addWidget(tree)
        right_layout.addWidget(piles_group)

        controls_layout = QHBoxLayout()
        mark_pile_button = QPushButton("Mark Selected Pile as Sorted")
        controls_layout.addWidget(mark_pile_button)
        right_layout.addLayout(controls_layout)

        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])

        def on_mark_pile_sorted(item_from_click=None):
            selected_item = item_from_click or tree.currentItem()
            if not selected_item:
                QMessageBox.warning(view_widget, "No Selection", "Please select a pile from the list.")
                return

            cards_in_pile = self._get_cards_from_item(selected_item)
            for card in cards_in_pile:
                card.sorted_count = card.quantity

            self.show_status_message(f"Pile '{selected_item.text(0)}' sorted.")
            generate_and_display_plan()

        def generate_and_display_plan():
            ax.clear()
            tree.clear()

            current_unsorted = [c for c in cards_to_sort if c.quantity > c.sorted_count]

            if not current_unsorted:
                ax.text(0.5, 0.5, "Set Complete!", ha='center', va='center', color='white', fontsize=16)
                canvas.draw()
                mark_pile_button.setEnabled(False)
                return

            piles = collections.defaultdict(list)

            if self.group_low_count_check.isChecked():
                try:
                    threshold = int(self.group_threshold_edit.text())
                except ValueError:
                    threshold = 20

                raw_letter_totals = collections.defaultdict(int)
                for card in current_unsorted:
                    if card.name and card.name != 'N/A':
                        raw_letter_totals[card.name[0].upper()] += (card.quantity - card.sorted_count)

                # --- START FINAL IMPLEMENTATION ---
                # This logic is a direct, in-line implementation of the working Set Analyzer algorithm.
                mapping = {}
                buf, tot = "", 0

                def flush():
                    nonlocal buf, tot
                    if buf:
                        for ch in buf: mapping[ch] = buf
                        buf, tot = "", 0

                letters = string.ascii_uppercase
                for i, l in enumerate(letters):
                    if raw_letter_totals.get(l, 0) < threshold:
                        buf += l
                        tot += raw_letter_totals.get(l, 0)
                        if tot >= threshold or not (i < 25 and raw_letter_totals.get(letters[i + 1], 0) < threshold):
                            flush()
                    else:
                        flush()
                        mapping[l] = l
                flush()
                # --- END FINAL IMPLEMENTATION ---

                for card in current_unsorted:
                    if card.name and card.name != 'N/A':
                        first_letter = card.name[0].upper()
                        # Use the generated map; default to the letter itself if somehow not in the map
                        pile_key = mapping.get(first_letter, first_letter)
                        piles[pile_key].append(card)
            else:
                # Original behavior if the box is unchecked
                for card in current_unsorted:
                    if card.name and card.name != 'N/A':
                        piles[card.name[0].upper()].append(card)

            nodes = []
            for name, pile_cards in piles.items():
                count = sum(c.quantity - c.sorted_count for c in pile_cards)
                if count > 0:
                    nodes.append(SortGroup(group_name=name, count=count, cards=pile_cards))

            nodes.sort(key=lambda x: x.count, reverse=True)

            labels = [node.group_name for node in nodes]
            counts = [node.count for node in nodes]
            ax.bar(labels, counts, color='#007acc')
            ax.set_title(f"Unsorted Cards in {set_name}", color='white')
            ax.set_ylabel("Card Count", color='white')
            ax.tick_params(axis='x', colors='white', rotation=45)
            ax.tick_params(axis='y', colors='white')
            for spine in ax.spines.values(): spine.set_color('white')
            canvas.figure.tight_layout()
            canvas.draw()

            self._populate_tree(tree.invisibleRootItem(), nodes)

        mark_pile_button.clicked.connect(lambda: on_mark_pile_sorted())
        tree.itemDoubleClicked.connect(lambda item: on_mark_pile_sorted(item))
        generate_and_display_plan()

        self.results_stack.addWidget(view_widget)
        self.results_stack.setCurrentWidget(view_widget)

    def handle_item_double_click(self, item: QTreeWidgetItem, next_level: int):
        if next_level > len(self.sort_order):
            self.mark_item_as_sorted(item)
        else:
            self.drill_down(item, next_level)

    def drill_down(self, item: QTreeWidgetItem, next_level: int):
        if next_level > len(self.sort_order): return

        cards_in_group = self._get_cards_from_item(item)
        if not cards_in_group: return

        self.navigate_to_level(next_level - 1)
        self.add_breadcrumb(item.text(0), next_level)
        self.create_new_view(cards_in_group, next_level)

    def add_breadcrumb(self, text: str, level: int):
        if level > 0: self.breadcrumb_layout.addWidget(QLabel(">"))
        btn = QPushButton(text.split(': ')[-1])
        btn.setObjectName("BreadcrumbButton")
        btn.clicked.connect(lambda: self.navigate_to_level(level))
        self.breadcrumb_layout.addWidget(btn)

    def navigate_to_level(self, level: int):
        while self.results_stack.count() > level + 1:
            widget = self.results_stack.widget(level + 1)
            self.results_stack.removeWidget(widget)
            widget.deleteLater()

        while self.breadcrumb_layout.count() > (level * 2) + 1:
            if widget := self.breadcrumb_layout.takeAt(self.breadcrumb_layout.count() - 1).widget():
                widget.deleteLater()

        self.results_stack.setCurrentIndex(level)
        self.filter_edit.clear()
        self.filter_current_view("")
        self.update_button_visibility()

    def _generate_level_breakdown(self, current_cards: List[Card], criterion: str | None) -> List[SortGroup]:
        if not criterion:
            return sorted(
                [SortGroup(group_name=c.name, count=(c.quantity - c.sorted_count), cards=[c], is_card_leaf=True) for c
                 in current_cards],
                key=lambda sg: sg.group_name)

        groups = collections.defaultdict(list)
        for card in current_cards:
            groups[self._get_nested_value(card, criterion)].append(card)

        sorted_group_names = sorted(groups.keys())

        return [
            SortGroup(group_name=f"{criterion}: {name}", count=sum(c.quantity - c.sorted_count for c in groups[name]),
                      cards=groups[name]) for name in sorted_group_names]

    def _populate_tree(self, parent_item: QTreeWidgetItem, nodes: List[SortGroup]):
        for node in nodes:
            tree_item = SortableTreeWidgetItem(parent_item, [node.group_name, str(node.count)])
            tree_item.setData(0, Qt.ItemDataRole.UserRole, node.cards)
            if node.is_card_leaf:
                font = tree_item.font(0)
                font.setItalic(True)
                for i in range(2):
                    tree_item.setFont(i, font)

    def _get_nested_value(self, card: Card, key: str) -> str:
        if key == "Name": return card.name
        if key == "Set": return card.set_name
        if key == "Rarity": return card.rarity.capitalize()
        if key == "Type Line": return card.type_line.split('//')[0].strip()
        if key == "Condition": return card.condition.capitalize()
        if key == "Color Identity": return ''.join(sorted(card.color_identity)) or 'Colorless'
        if key == "Commander Staple": return "Staple (Top 1000)" if card.edhrec_rank and card.edhrec_rank <= 1000 else "Not a Staple"
        return 'N/A'

    def clear_layout(self, layout: QHBoxLayout):
        while layout.count():
            if child := layout.takeAt(0).widget():
                child.deleteLater()

    def reset_preview_pane(self, *args):
        self.current_loading_id = None
        self.card_image_label.setText("Select a card to see its image.")
        self.card_image_label.setPixmap(QPixmap())
        self.card_details_label.setText("")

    def update_card_preview(self, item: QTreeWidgetItem):
        self.reset_preview_pane()
        cards = self._get_cards_from_item(item)
        if not cards or len(cards) != 1: return
        card = cards[0]
        if not isinstance(card, Card) or not card.image_uri: return

        self.current_loading_id = card.scryfall_id
        self.card_image_label.setText("Loading image...")
        self.card_details_label.setText(f"<b>{card.name}</b><br>"
                                        f"{card.mana_cost or ''}<br>"
                                        f"{card.type_line}<br>"
                                        f"<i>{card.set_name} ({card.rarity.upper()})</i><br><br>"
                                        f"Total Owned: {card.quantity}<br>"
                                        f"Sorted: {card.sorted_count}")

        self.image_worker = ImageFetchWorker(card.image_uri, card.scryfall_id, self.api)
        self.image_worker.finished.connect(self.on_image_loaded)
        self.image_worker.error.connect(lambda err: self.card_image_label.setText(f"Error:\n{err}"))
        self.image_worker.start()

    def on_image_loaded(self, image_data: bytes, scryfall_id: str):
        if scryfall_id != self.current_loading_id: return
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        self.card_image_label.setPixmap(pixmap.scaled(self.card_image_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))

    def export_current_view(self):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget) or current_tree.topLevelItemCount() == 0:
            QMessageBox.warning(self, "Export Error", "No data to export in the current view.")
            return

        filepath, _ = QFileDialog.askSaveAsFileName(self, "Save View as CSV", "sorter_view.csv", "CSV Files (*.csv)")
        if not filepath: return

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
            QMessageBox.information(self, "Export Success", f"Successfully exported current view to {filepath}")
        except IOError as e:
            QMessageBox.critical(self, "Export Error", f"Failed to write to file: {e}")

    def filter_current_view(self, text: str):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget): return

        iterator = QTreeWidgetItemIterator(current_tree, QTreeWidgetItemIterator.IteratorFlag.All)
        while iterator.value():
            item = iterator.value()
            item.setHidden(text.lower() not in item.text(0).lower())
            iterator += 1

    def _get_cards_from_item(self, item: QTreeWidgetItem) -> List[Card]:
        if not item: return []
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if item_data and isinstance(item_data, list) and all(isinstance(c, Card) for c in item_data):
            return item_data
        return []

    def on_mark_group_button_clicked(self):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget): return

        current_item = current_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No Selection", "Please select a group to mark as sorted.")
            return
        self.mark_item_as_sorted(current_item)

    def mark_item_as_sorted(self, item: QTreeWidgetItem):
        cards_to_mark = self._get_cards_from_item(item)
        if not cards_to_mark:
            self.show_status_message("Could not find cards associated with this group.")
            return

        for card in cards_to_mark:
            card.sorted_count = card.quantity

        self.show_status_message(f"Group '{item.text(0)}' sorted.")
        self.generate_plan()

    def update_button_visibility(self, *args):
        is_normal_view = isinstance(self.results_stack.currentWidget(), NavigableTreeWidget)

        self.mark_sorted_button.setVisible(is_normal_view)
        self.export_button.setVisible(is_normal_view)
        self.sort_set_button.setVisible(False)

        if not is_normal_view:
            return

        level = self.results_stack.currentIndex()
        if level == 0 and self.sort_order and self.sort_order[0] == "Set":
            current_tree = self.results_stack.currentWidget()
            if current_tree and current_tree.currentItem():
                self.sort_set_button.setVisible(True)

    def show_status_message(self, message: str, timeout: int = 2500):
        self.status_label.setText(message)
        QTimer.singleShot(timeout, lambda: self.status_label.setText(""))
