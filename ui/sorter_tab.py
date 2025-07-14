import csv
import pathlib
import collections
import string
from typing import Dict, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QListWidget, QCheckBox,
    QGroupBox, QFileDialog, QMessageBox, QProgressBar, QStackedWidget, QSplitter,
    QTreeWidgetItem, QTreeWidgetItemIterator, QHeaderView, QTreeWidget, QAbstractItemView
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from api.scryfall_api import ScryfallAPI, MTGAPIError
from workers.threads import CsvImportWorker, ImageFetchWorker
from ui.custom_widgets import SortableTreeWidgetItem, NavigableTreeWidget
from core.models import Card, SortGroup
from core.constants import Config
from PyQt6.QtCore import QSettings


class SetSorterView(QWidget):
    """A dedicated widget for the 'Sort This Set' view."""

    def __init__(self, cards_to_sort: List[Card], set_name: str, parent_tab: 'ManaBoxSorterTab'):
        super().__init__()
        self.cards_to_sort = cards_to_sort
        self.set_name = set_name
        self.parent_tab = parent_tab
        self._is_generating = False
        self._setup_ui()
        QTimer.singleShot(0, self.generate_plan)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        chart_group = QGroupBox(f"Optimal Sort Plan for {self.set_name}")
        chart_layout = QVBoxLayout(chart_group)
        self.canvas = FigureCanvas(Figure(facecolor='#2b2b2b'))
        self.ax = self.canvas.figure.subplots()
        chart_layout.addWidget(self.canvas)
        splitter.addWidget(chart_group)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        piles_group = QGroupBox("Sorting Piles")
        piles_layout = QVBoxLayout(piles_group)
        self.tree = QTreeWidget()
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setHeaderLabels(["Pile", "Unsorted Count"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setSortingEnabled(True)
        self.tree.setToolTip("Double-click a pile to mark it as sorted, or select multiple piles and use the button")
        piles_layout.addWidget(self.tree)
        right_layout.addWidget(piles_group)
        controls_layout = QHBoxLayout()
        mark_pile_button = QPushButton("Mark Selected as Sorted")
        mark_pile_button.setToolTip("Mark the selected pile(s) as completely sorted (Shortcut: Space)")
        controls_layout.addWidget(mark_pile_button)
        right_layout.addLayout(controls_layout)
        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])

        mark_pile_button.clicked.connect(lambda: self.on_mark_piles_sorted())
        self.tree.itemDoubleClicked.connect(lambda item, col: self.on_mark_piles_sorted([item]))

    def on_mark_piles_sorted(self, items_to_mark=None):
        selected_items = items_to_mark or self.tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select one or more piles from the list.")
            return
        card_count = 0
        for item in selected_items:
            cards_in_pile = self.parent_tab._get_cards_from_item(item)
            for card in cards_in_pile:
                unsorted_before = card.quantity - card.sorted_count
                card_count += unsorted_before if unsorted_before > 0 else 0
                card.sorted_count = card.quantity
        self.parent_tab.show_status_message(f"Sorted {card_count} cards in {len(selected_items)} pile(s).")
        self.generate_plan()

    def generate_plan(self):
        if self._is_generating:
            return

        self._is_generating = True
        try:
            self.ax.clear()
            self.tree.clear()

            show_sorted = self.parent_tab.show_sorted_check.isChecked()

            if show_sorted:
                cards_to_process = self.cards_to_sort
                chart_title = f"Card Distribution in {self.set_name}"
            else:
                cards_to_process = [c for c in self.cards_to_sort if c.quantity > c.sorted_count]
                chart_title = f"Unsorted Cards in {self.set_name}"

            if not cards_to_process:
                self.ax.text(0.5, 0.5, "Set Complete!", ha='center', va='center', color='white', fontsize=16)
                self.canvas.draw()
                return

            piles = collections.defaultdict(list)
            if self.parent_tab.group_low_count_check.isChecked():
                try:
                    threshold = int(self.parent_tab.group_threshold_edit.text())
                except ValueError:
                    threshold = 20

                raw_letter_totals = collections.defaultdict(int)
                for card in cards_to_process:
                    if card.name and card.name != 'N/A':
                        count = card.quantity if show_sorted else (card.quantity - card.sorted_count)
                        raw_letter_totals[card.name[0].upper()] += count

                mapping = {}
                buf, tot = "", 0

                def flush():
                    nonlocal buf, tot
                    if buf:
                        for ch in buf: mapping[ch] = buf
                        buf, tot = "", 0

                letters = string.ascii_uppercase
                for i, l in enumerate(letters):
                    count = raw_letter_totals.get(l, 0)
                    if 0 < count < threshold:
                        buf += l;
                        tot += count
                        if tot >= threshold or not (
                                i < 25 and raw_letter_totals.get(letters[i + 1], 0) < threshold): flush()
                    else:
                        flush()
                        mapping[l] = l
                flush()
                for card in cards_to_process:
                    if card.name and card.name != 'N/A':
                        first_letter = card.name[0].upper()
                        pile_key = mapping.get(first_letter, first_letter)
                        piles[pile_key].append(card)
            else:
                for card in cards_to_process:
                    if card.name and card.name != 'N/A':
                        piles[card.name[0].upper()].append(card)

            nodes = []
            for name, pile_cards in piles.items():
                unsorted_count = sum(c.quantity - c.sorted_count for c in pile_cards)
                total_count = sum(c.quantity for c in pile_cards)
                node = SortGroup(group_name=name, count=unsorted_count, cards=pile_cards)
                node.total_count = total_count
                nodes.append(node)

            self.parent_tab._populate_tree(self.tree.invisibleRootItem(), nodes)
            self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)

            if show_sorted:
                display_nodes = sorted([n for n in nodes if hasattr(n, 'total_count') and n.total_count > 0],
                                       key=lambda x: x.total_count, reverse=True)
                labels = [node.group_name for node in display_nodes]
                counts = [node.total_count for node in display_nodes]
            else:
                display_nodes = sorted([n for n in nodes if n.count > 0], key=lambda x: x.count, reverse=True)
                labels = [node.group_name for node in display_nodes]
                counts = [node.count for node in display_nodes]

            colors = ['#555' if node.count <= 0 else '#007acc' for node in display_nodes]

            self.ax.bar(labels, counts, color=colors)
            self.ax.set_title(chart_title, color='white')
            self.ax.set_ylabel("Card Count", color='white')
            self.ax.tick_params(axis='x', colors='white', rotation=45)
            self.ax.tick_params(axis='y', colors='white')
            for spine in self.ax.spines.values(): spine.set_color('white')
            self.canvas.figure.tight_layout()
            self.canvas.draw()
        finally:
            self._is_generating = False


class ManaBoxSorterTab(QWidget):
    # Signals for communication with main window
    collection_loaded = pyqtSignal()
    progress_updated = pyqtSignal(int)
    operation_started = pyqtSignal(str, int)  # message, max_value
    operation_finished = pyqtSignal()

    def __init__(self, api: ScryfallAPI):
        super().__init__()
        self.api = api
        self.all_cards: List[Card] = []
        self.worker = None
        self.sort_order: List[str] = []
        self.current_loading_id: str | None = None
        self.last_csv_path: str | None = None
        self.progress_to_load: Dict | None = None
        self.is_loading = False

        main_layout = QVBoxLayout(self)
        self._create_import_section(main_layout)
        self._create_options_section(main_layout)
        self._create_run_section(main_layout)
        self._create_results_section(main_layout)

    def initial_load(self):
        settings = QSettings(Config.ORG_NAME, Config.APP_NAME)
        last_path = settings.value("sorter/lastCsvPath", None)
        if last_path and pathlib.Path(last_path).exists():
            self.progress_to_load = settings.value("sorter/progress", {})
            self.import_csv(filepath=last_path)

    def _create_import_section(self, layout: QVBoxLayout):
        group = QGroupBox("1. Import Collection")
        layout.addWidget(group)
        group_layout = QVBoxLayout(group)
        self.import_button = QPushButton("Import ManaBox CSV")
        self.import_button.setObjectName("AccentButton")
        self.import_button.setToolTip("Import a ManaBox CSV export file containing your collection (Shortcut: Ctrl+O)")
        self.import_button.clicked.connect(self.import_csv)
        self.file_label = QLabel("No file loaded.")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_label.setToolTip("Shows the currently loaded collection file and status")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setToolTip("Shows progress of card data fetching from Scryfall")
        group_layout.addWidget(self.import_button)
        group_layout.addWidget(self.file_label)
        group_layout.addWidget(self.progress_bar)

    def _create_options_section(self, layout: QVBoxLayout):
        options_group = QGroupBox("2. Sorting Options")
        options_layout = QHBoxLayout(options_group)
        layout.addWidget(options_group)
        sort_order_group = QGroupBox("Sort Order")
        sort_order_group.setToolTip(
            "Define the hierarchy for organizing your cards. Cards will be grouped by the first criterion, then sub-grouped by the second, etc.")
        options_layout.addWidget(sort_order_group, 2)
        grid = QGridLayout(sort_order_group)
        self.available_list = QListWidget()
        self.available_list.addItems(
            ["Set", "Color Identity", "Rarity", "Type Line", "Name", "Condition", "Commander Staple"])
        self.available_list.setToolTip("Available sorting criteria. Double-click or use >> to add to sort order.")
        self.selected_list = QListWidget()
        self.selected_list.setToolTip("Your sorting hierarchy. Use Up/Down to reorder, << to remove criteria.")
        add_button = QPushButton(">>");
        add_button.setToolTip("Add selected criterion to sort order")
        add_button.clicked.connect(self.add_criterion)
        remove_button = QPushButton("<<");
        remove_button.setToolTip("Remove selected criterion from sort order")
        remove_button.clicked.connect(self.remove_criterion)
        up_button = QPushButton("Up");
        up_button.setToolTip("Move selected criterion up in priority")
        up_button.clicked.connect(self.move_up)
        down_button = QPushButton("Down");
        down_button.setToolTip("Move selected criterion down in priority")
        down_button.clicked.connect(self.move_down)
        btn_layout = QVBoxLayout();
        btn_layout.addStretch();
        btn_layout.addWidget(add_button);
        btn_layout.addWidget(remove_button);
        btn_layout.addStretch()
        side_btn_layout = QVBoxLayout();
        side_btn_layout.addStretch();
        side_btn_layout.addWidget(up_button);
        side_btn_layout.addWidget(down_button);
        side_btn_layout.addStretch()
        grid.addWidget(self.available_list, 0, 0);
        grid.addLayout(btn_layout, 0, 1);
        grid.addWidget(self.selected_list, 0, 2);
        grid.addLayout(side_btn_layout, 0, 3)
        grid.setColumnStretch(0, 1);
        grid.setColumnStretch(2, 1)
        set_plan_group = QGroupBox("Set Sorting Plan")
        set_plan_group.setToolTip("Options for optimizing letter-based sorting within sets")
        options_layout.addWidget(set_plan_group, 1)
        set_plan_layout = QVBoxLayout(set_plan_group)
        self.group_low_count_check = QCheckBox("Group low-count letters into piles");
        self.group_low_count_check.setChecked(True)
        self.group_low_count_check.setToolTip(
            "Combine letters with few cards into larger piles for more efficient sorting")
        set_plan_layout.addWidget(self.group_low_count_check)
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Min pile total:"))
        self.group_threshold_edit = QLineEdit("20")
        self.group_threshold_edit.setToolTip("Minimum number of cards per pile when grouping letters together")
        threshold_layout.addWidget(self.group_threshold_edit)
        set_plan_layout.addLayout(threshold_layout)
        set_plan_layout.addStretch()

    def _create_run_section(self, layout: QVBoxLayout):
        group = QGroupBox("3. Generate Plan")
        layout.addWidget(group)
        h_layout = QHBoxLayout(group)
        h_layout.addStretch()
        self.run_button = QPushButton("Generate Sorting Plan")
        self.run_button.setToolTip("Create a visual sorting plan based on your criteria (Shortcut: Ctrl+G)")
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
        self.show_sorted_check = QCheckBox("Show Sorted Groups")
        self.show_sorted_check.setToolTip("Include already-sorted cards in the display")
        self.show_sorted_check.stateChanged.connect(self.on_show_sorted_toggled)
        top_bar_layout.addWidget(self.show_sorted_check)
        top_bar_layout.addStretch()
        self.sort_set_button = QPushButton("Sort This Set");
        self.sort_set_button.setToolTip("Open detailed sorting view for the selected set")
        self.sort_set_button.clicked.connect(self.on_sort_set_clicked);
        self.sort_set_button.setVisible(False)
        top_bar_layout.addWidget(self.sort_set_button)
        self.mark_sorted_button = QPushButton("Mark Group as Sorted");
        self.mark_sorted_button.setToolTip("Mark all cards in the selected group(s) as sorted (Shortcut: Space)")
        self.mark_sorted_button.clicked.connect(self.on_mark_group_button_clicked);
        self.mark_sorted_button.setVisible(False)
        top_bar_layout.addWidget(self.mark_sorted_button)
        self.export_button = QPushButton("Export View");
        self.export_button.setToolTip("Export the current view to a CSV file (Shortcut: Ctrl+E)")
        self.export_button.clicked.connect(self.export_current_view);
        self.export_button.setVisible(False)
        top_bar_layout.addWidget(self.export_button)
        results_layout.addLayout(top_bar_layout)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget();
        left_layout = QVBoxLayout(left_panel)
        self.filter_edit = QLineEdit();
        self.filter_edit.setPlaceholderText("Filter current view...");
        self.filter_edit.setToolTip("Type to filter the current view by group name")
        self.filter_edit.textChanged.connect(self.filter_current_view);
        self.filter_edit.setVisible(False)
        self.results_stack = QStackedWidget()
        left_layout.addWidget(self.filter_edit);
        left_layout.addWidget(self.results_stack)
        right_panel = QWidget();
        right_layout = QVBoxLayout(right_panel)
        self.card_image_label = QLabel("Double-click a card to see its image.");
        self.card_image_label.setObjectName("CardImageLabel");
        self.card_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter);
        self.card_image_label.setMinimumSize(220, 308)
        self.card_image_label.setToolTip("Card images appear here when you select individual cards")
        self.card_details_label = QLabel();
        self.card_details_label.setAlignment(Qt.AlignmentFlag.AlignTop);
        self.card_details_label.setWordWrap(True)
        self.card_details_label.setToolTip("Detailed card information appears here")
        right_layout.addWidget(self.card_image_label);
        right_layout.addWidget(self.card_details_label);
        right_layout.addStretch()
        main_splitter.addWidget(left_panel);
        main_splitter.addWidget(right_panel);
        main_splitter.setSizes([700, 350])
        results_layout.addWidget(main_splitter)
        self.status_label = QLabel();
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        results_layout.addWidget(self.status_label)
        layout.setStretchFactor(group, 1)

    def on_show_sorted_toggled(self):
        current_widget = self.results_stack.currentWidget()
        if isinstance(current_widget, SetSorterView):
            current_widget.generate_plan()
        else:
            self.generate_plan()

    def import_csv(self, filepath=None):
        if self.is_loading:
            QMessageBox.information(self, "Import in Progress", "Please wait for the current import to complete.")
            return

        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(
                self,
                "Open ManaBox CSV",
                "",
                "CSV Files (*.csv);;All Files (*.*)"
            )
            if not filepath:
                return

        # Validate file exists and is readable
        try:
            file_path = pathlib.Path(filepath)
            if not file_path.exists():
                QMessageBox.critical(
                    self,
                    "File Not Found",
                    f"The file '{filepath}' does not exist.\n\nPlease check the file path and try again."
                )
                return

            if not file_path.is_file():
                QMessageBox.critical(
                    self,
                    "Invalid File",
                    f"'{filepath}' is not a valid file.\n\nPlease select a CSV file exported from ManaBox."
                )
                return

            # Quick validation of CSV structure
            with open(filepath, 'r', encoding='utf-8') as f:
                first_few_lines = [f.readline() for _ in range(5)]
                header_found = any('Scryfall ID' in line and 'Quantity' in line for line in first_few_lines)
                if not header_found:
                    reply = QMessageBox.question(
                        self,
                        "Unrecognized Format",
                        "This file doesn't appear to be a standard ManaBox CSV export.\n"
                        "It should contain 'Scryfall ID' and 'Quantity' columns.\n\n"
                        "Do you want to try importing it anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.No:
                        return
        except Exception as e:
            QMessageBox.critical(
                self,
                "File Access Error",
                f"Unable to read the file '{filepath}':\n\n{str(e)}\n\n"
                "Please check file permissions and try again."
            )
            return

        self.is_loading = True;
        self.last_csv_path = filepath
        self.import_button.setEnabled(False);
        self.run_button.setEnabled(False)
        filename = pathlib.Path(filepath).name
        self.file_label.setText(f"Loading {filename}...")
        self.progress_bar.setVisible(True);
        self.progress_bar.setRange(0, 0)

        # Emit signal for status bar
        self.operation_started.emit(f"Importing {filename}", 0)

        self.worker = CsvImportWorker(filepath, self.api)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_import_finished)
        self.worker.error.connect(self.on_import_error)
        self.worker.start()

    def update_progress(self, value, total):
        if self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
            # Update operation with known total
            self.operation_started.emit(f"Fetching card data", total)
        self.progress_bar.setValue(value)
        self.file_label.setText(f"Fetching card data: {value}/{total}")
        self.progress_updated.emit(value)

    def on_import_finished(self, cards: List[Card]):
        self.all_cards = cards
        if self.progress_to_load:
            for card in self.all_cards:
                card.sorted_count = self.progress_to_load.get(card.scryfall_id, 0)
            self.progress_to_load = None

        unique_count = len(self.all_cards)
        total_count = sum(card.quantity for card in self.all_cards)

        self.file_label.setText(f"Loaded {unique_count:,} unique cards ({total_count:,} total)")
        self.progress_bar.setVisible(False);
        self.import_button.setEnabled(True);
        self.run_button.setEnabled(True)
        self.is_loading = False

        # Emit signals
        self.operation_finished.emit()
        self.collection_loaded.emit()

        self.generate_plan()

    def on_import_error(self, error_message: str):
        self.is_loading = False;
        self.file_label.setText("Import failed - see details below")
        self.progress_bar.setVisible(False)
        self.import_button.setEnabled(True);
        self.run_button.setEnabled(True)

        # Emit signal
        self.operation_finished.emit()

        # Show detailed error message
        if "Could not fetch card" in error_message:
            detailed_msg = (
                f"Import failed due to network issues:\n\n{error_message}\n\n"
                "Possible solutions:\n"
                "• Check your internet connection\n"
                "• Verify that Scryfall.com is accessible\n"
                "• Try importing a smaller file first\n"
                "• Wait a moment and try again (rate limiting)"
            )
        elif "Could not find header" in error_message:
            detailed_msg = (
                f"CSV format error:\n\n{error_message}\n\n"
                "Please ensure you're using a ManaBox CSV export with:\n"
                "• 'Scryfall ID' column\n"
                "• 'Quantity' column\n"
                "• Proper CSV formatting"
            )
        else:
            detailed_msg = f"Import failed:\n\n{error_message}\n\nPlease check the file format and try again."

        QMessageBox.critical(self, "Import Error", detailed_msg)

    def add_criterion(self):
        if item := self.available_list.currentItem():
            self.selected_list.addItem(self.available_list.takeItem(self.available_list.row(item)))

    def remove_criterion(self):
        if item := self.selected_list.currentItem():
            self.available_list.addItem(self.selected_list.takeItem(self.selected_list.row(item)))

    def move_up(self):
        if (row := self.selected_list.currentRow()) > 0:
            item = self.selected_list.takeItem(row);
            self.selected_list.insertItem(row - 1, item);
            self.selected_list.setCurrentRow(row - 1)

    def move_down(self):
        if (row := self.selected_list.currentRow()) < self.selected_list.count() - 1:
            item = self.selected_list.takeItem(row);
            self.selected_list.insertItem(row + 1, item);
            self.selected_list.setCurrentRow(row + 1)

    def generate_plan(self):
        if self.is_loading:
            return
        if not self.all_cards:
            if not self.last_csv_path:
                QMessageBox.information(
                    self,
                    "No Collection",
                    "Please import a collection first using the 'Import ManaBox CSV' button.\n\n"
                    "You can export your collection from ManaBox and import it here."
                )
            return

        cards_to_process = self.all_cards
        if not self.show_sorted_check.isChecked():
            cards_to_process = [card for card in self.all_cards if card.quantity > card.sorted_count]

        self.clear_layout(self.breadcrumb_layout)
        while self.results_stack.count() > 0:
            widget = self.results_stack.widget(0);
            self.results_stack.removeWidget(widget);
            widget.deleteLater()
        self.reset_preview_pane()

        if not cards_to_process:
            self.show_status_message("🎉 Sorting Complete! All cards have been sorted.", 5000)
            for w in [self.export_button, self.mark_sorted_button, self.filter_edit]:
                w.setVisible(False)
            return

        self.add_breadcrumb("Home", 0)
        self.create_new_view(cards_to_process, 0)
        self.filter_edit.setVisible(True)
        self.update_button_visibility()

    def create_new_view(self, cards_in_group: List[Card], level: int):
        tree = NavigableTreeWidget()
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setHeaderLabels(['Group', 'Unsorted Count'])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.setSortingEnabled(True)
        tree.setToolTip("Double-click to drill down, Enter to drill down, Backspace to go up, Space to mark as sorted")
        tree.itemDoubleClicked.connect(lambda item: self.handle_item_double_click(item, level + 1))
        tree.navigateUpRequested.connect(lambda: self.navigate_to_level(level - 1) if level > 0 else None)
        tree.currentItemChanged.connect(self.update_button_visibility)
        tree.currentItemChanged.connect(self.on_tree_selection_changed)
        self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
        criterion = self.sort_order[level] if level < len(self.sort_order) else None
        nodes = self._generate_level_breakdown(cards_in_group, criterion)
        self._populate_tree(tree.invisibleRootItem(), nodes)
        tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.results_stack.addWidget(tree)
        self.results_stack.setCurrentWidget(tree)

    def on_tree_selection_changed(self, current, previous):
        """Handle tree selection change for card preview"""
        if current:
            self.update_card_preview(current)
        else:
            self.reset_preview_pane()

    def on_sort_set_clicked(self):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, NavigableTreeWidget):
            return
        current_item = current_tree.currentItem()
        if not current_item:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select a set from the list to open the detailed sorting view.\n\n"
                "The sorting view will help you organize cards within that set more efficiently."
            )
            return
        cards_in_set = self._get_cards_from_item(current_item)
        level = self.results_stack.currentIndex()
        self.navigate_to_level(level)
        self.add_breadcrumb(f"{current_item.text(0)} (Sorting)", level + 1)
        self.create_set_sorter_view(cards_in_set, current_item.text(0))
        self.update_button_visibility()

    def create_set_sorter_view(self, cards_to_sort: List[Card], set_name: str):
        view = SetSorterView(cards_to_sort, set_name, self)
        self.results_stack.addWidget(view)
        self.results_stack.setCurrentWidget(view)

    def handle_item_double_click(self, item: QTreeWidgetItem, next_level: int):
        self.drill_down(item, next_level)

    def drill_down(self, item: QTreeWidgetItem, next_level: int):
        if next_level > len(self.sort_order):
            return
        cards_in_group = self._get_cards_from_item(item)
        if not cards_in_group:
            return
        self.navigate_to_level(next_level - 1)
        self.add_breadcrumb(item.text(0), next_level)
        self.create_new_view(cards_in_group, next_level)

    def add_breadcrumb(self, text: str, level: int):
        if level > 0:
            self.breadcrumb_layout.addWidget(QLabel(">"))
        btn = QPushButton(text.split(': ')[-1])
        btn.setObjectName("BreadcrumbButton")
        btn.setToolTip(f"Navigate back to {text}")
        btn.clicked.connect(lambda: self.navigate_to_level(level))
        self.breadcrumb_layout.addWidget(btn)

    def navigate_to_level(self, level: int):
        while self.results_stack.count() > level + 1:
            widget = self.results_stack.widget(level + 1);
            self.results_stack.removeWidget(widget);
            widget.deleteLater()
        while self.breadcrumb_layout.count() > (level * 2) + 1:
            if widget := self.breadcrumb_layout.takeAt(self.breadcrumb_layout.count() - 1).widget():
                widget.deleteLater()
        self.results_stack.setCurrentIndex(level);
        self.filter_edit.clear();
        self.filter_current_view("");
        self.update_button_visibility()

    def _generate_level_breakdown(self, current_cards: List[Card], criterion: str | None) -> List[SortGroup]:
        if not criterion:
            nodes = [SortGroup(group_name=c.name, count=(c.quantity - c.sorted_count), cards=[c], is_card_leaf=True) for
                     c in current_cards]
            return sorted(nodes, key=lambda sg: sg.group_name)
        groups = collections.defaultdict(list)
        for card in current_cards:
            groups[self._get_nested_value(card, criterion)].append(card)
        nodes = [
            SortGroup(group_name=f"{criterion}: {name}", count=sum(c.quantity - c.sorted_count for c in card_group),
                      cards=card_group) for name, card_group in sorted(groups.items())]
        return nodes

    def _populate_tree(self, parent_item: QTreeWidgetItem, nodes: List[SortGroup]):
        for node in nodes:
            tree_item = SortableTreeWidgetItem(parent_item, [node.group_name, str(node.count)])
            tree_item.setData(0, Qt.ItemDataRole.UserRole, node.cards)
            if node.count <= 0:
                font = tree_item.font(0);
                font.setStrikeOut(True)
                tree_item.setFont(0, font);
                tree_item.setFont(1, font)
                tree_item.setForeground(0, QColor(Qt.GlobalColor.gray));
                tree_item.setForeground(1, QColor(Qt.GlobalColor.gray))
            if node.is_card_leaf:
                font = tree_item.font(0);
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
        if not cards or len(cards) != 1:
            return
        card = cards[0]
        if not isinstance(card, Card) or not card.image_uri:
            return
        self.current_loading_id = card.scryfall_id
        self.card_image_label.setText("Loading image...")
        self.card_details_label.setText(
            f"<b>{card.name}</b><br>{card.mana_cost or ''}<br>{card.type_line}<br>"
            f"<i>{card.set_name} ({card.rarity.upper()})</i><br><br>"
            f"Total Owned: {card.quantity}<br>Sorted: {card.sorted_count}")
        self.image_worker = ImageFetchWorker(card.image_uri, card.scryfall_id, self.api)
        self.image_worker.finished.connect(self.on_image_loaded)
        self.image_worker.error.connect(lambda err: self.card_image_label.setText(f"Image unavailable:\n{err}"))
        self.image_worker.start()

    def on_image_loaded(self, image_data: bytes, scryfall_id: str):
        if scryfall_id != self.current_loading_id:
            return
        pixmap = QPixmap();
        pixmap.loadFromData(image_data)
        self.card_image_label.setPixmap(pixmap.scaled(self.card_image_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))

    def export_current_view(self):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget) or current_tree.topLevelItemCount() == 0:
            QMessageBox.information(
                self,
                "No Data",
                "There's no data to export in the current view.\n\n"
                "Generate a sorting plan first, then navigate to the view you want to export."
            )
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save View as CSV",
            "sorter_view.csv",
            "CSV Files (*.csv);;All Files (*.*)"
        )
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
            QMessageBox.information(self, "Export Success", f"Successfully exported current view to:\n{filepath}")
        except PermissionError:
            QMessageBox.critical(
                self,
                "Permission Error",
                f"Cannot write to '{filepath}'.\n\n"
                "The file may be open in another program or you may not have write permissions."
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export file:\n\n{str(e)}")

    def filter_current_view(self, text: str):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget):
            return
        iterator = QTreeWidgetItemIterator(current_tree, QTreeWidgetItemIterator.IteratorFlag.All)
        while iterator.value():
            item = iterator.value()
            item.setHidden(text.lower() not in item.text(0).lower())
            iterator += 1

    def _get_cards_from_item(self, item: QTreeWidgetItem) -> List[Card]:
        if not item:
            return []
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if item_data and isinstance(item_data, list) and all(isinstance(c, Card) for c in item_data):
            return item_data
        return []

    def on_mark_group_button_clicked(self):
        current_tree = self.results_stack.currentWidget()
        if not isinstance(current_tree, QTreeWidget):
            return
        selected_items = current_tree.selectedItems()
        if not selected_items:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select one or more groups to mark as sorted.\n\n"
                "You can select multiple groups by holding Ctrl while clicking."
            )
            return

        # Count cards that will be affected
        total_cards_affected = 0
        for item in selected_items:
            cards_to_mark = self._get_cards_from_item(item)
            for card in cards_to_mark:
                total_cards_affected += max(0, card.quantity - card.sorted_count)

        if total_cards_affected == 0:
            QMessageBox.information(
                self,
                "Already Sorted",
                "All selected groups are already completely sorted."
            )
            return

        # Confirm action
        reply = QMessageBox.question(
            self,
            "Confirm Mark as Sorted",
            f"This will mark {total_cards_affected} cards in {len(selected_items)} group(s) as sorted.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                self.mark_item_as_sorted(item, should_regenerate=False)
            self.show_status_message(f"✓ Marked {len(selected_items)} groups as sorted ({total_cards_affected} cards)")
            self.generate_plan()

    def mark_item_as_sorted(self, item: QTreeWidgetItem, should_regenerate: bool = True):
        cards_to_mark = self._get_cards_from_item(item)
        if not cards_to_mark:
            if should_regenerate:
                self.show_status_message("⚠ Could not find cards associated with this group.")
            return
        for card in cards_to_mark:
            card.sorted_count = card.quantity
        if should_regenerate:
            self.show_status_message(f"✓ Group '{item.text(0)}' marked as sorted.")
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

    # Keyboard shortcut handlers
    def handle_enter_key(self):
        """Handle Enter key - drill down if possible"""
        current_tree = self.results_stack.currentWidget()
        if isinstance(current_tree, NavigableTreeWidget) and current_tree.currentItem():
            level = self.results_stack.currentIndex()
            self.drill_down(current_tree.currentItem(), level + 1)

    def handle_escape_key(self):
        """Handle Escape key - clear filter or selection"""
        if self.filter_edit.text():
            self.filter_edit.clear()
        else:
            current_tree = self.results_stack.currentWidget()
            if isinstance(current_tree, QTreeWidget):
                current_tree.clearSelection()

    def handle_backspace_key(self):
        """Handle Backspace key - navigate up"""
        level = self.results_stack.currentIndex()
        if level > 0:
            self.navigate_to_level(level - 1)