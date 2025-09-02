# ui/sorter_tab_ui.py

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QProgressBar, QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)


class SorterTabUi:
    """Handles the creation and layout of all UI elements for the Sorter Tab."""
    
    def __init__(self, tab_widget: 'ManaBoxSorterTab'):
        """
        Initializes the UI builder.

        Args:
            tab_widget: The parent ManaBoxSorterTab widget that will own the UI elements.
        """
        self.tab_widget = tab_widget
    
    def setup_ui(self, main_layout: QVBoxLayout):
        """
        Creates and adds the main UI sections to the provided layout.

        Args:
            main_layout: The main QVBoxLayout of the parent tab.
        """
        self._create_import_section(main_layout)
        self._create_options_section(main_layout)
        self._create_run_section(main_layout)
        self._create_results_section(main_layout)
    
    def _create_import_section(self, layout: QVBoxLayout):
        group = QGroupBox("1. Import Collection")
        layout.addWidget(group)
        group_layout = QVBoxLayout(group)
        
        button_layout = QHBoxLayout()
        self.tab_widget.import_button = QPushButton("Import ManaBox CSV")
        self.tab_widget.import_button.setObjectName("AccentButton")
        self.tab_widget.import_button.setToolTip(
                "Import a ManaBox CSV export file containing your collection (Shortcut: Ctrl+O)")
        self.tab_widget.import_button.clicked.connect(self.tab_widget.import_csv)
        
        self.tab_widget.reset_progress_button = QPushButton("Reset Progress")
        self.tab_widget.reset_progress_button.setToolTip(
                "Resets the sorting progress for all cards in the current collection.")
        self.tab_widget.reset_progress_button.clicked.connect(self.tab_widget.reset_sort_progress)
        
        button_layout.addWidget(self.tab_widget.import_button)
        button_layout.addStretch()
        button_layout.addWidget(self.tab_widget.reset_progress_button)
        
        self.tab_widget.file_label = QLabel("No file loaded.")
        self.tab_widget.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tab_widget.file_label.setToolTip("Shows the currently loaded collection file and status")
        self.tab_widget.progress_bar = QProgressBar()
        self.tab_widget.progress_bar.setVisible(False)
        self.tab_widget.progress_bar.setToolTip("Shows progress of card data fetching from Scryfall")
        
        group_layout.addLayout(button_layout)
        group_layout.addWidget(self.tab_widget.file_label)
        group_layout.addWidget(self.tab_widget.progress_bar)
    
    def _create_options_section(self, layout: QVBoxLayout):
        options_group = QGroupBox("2. Sorting Options")
        options_layout = QHBoxLayout(options_group)
        layout.addWidget(options_group)
        
        sort_order_group = QGroupBox("Sort Order")
        sort_order_group.setToolTip(
                "Define the hierarchy for organizing your cards. Double-click to move criteria between lists. "
                "Drag-and-drop within the 'Selected' list to reorder.")
        options_layout.addWidget(sort_order_group, 2)
        grid = QGridLayout(sort_order_group)
        
        self.tab_widget.available_list = QListWidget()
        self.tab_widget.available_list.addItems(
                ["Set", "Color Identity", "Rarity", "Type Line", "First Letter", "Name", "Condition",
                 "Commander Staple"])
        self.tab_widget.available_list.setToolTip(
                "Available sorting criteria. Double-click an item to add it to the sort order.")
        self.tab_widget.available_list.itemDoubleClicked.connect(self.tab_widget.add_criterion)
        
        self.tab_widget.selected_list = QListWidget()
        self.tab_widget.selected_list.setToolTip(
                "Your sorting hierarchy. Double-click an item to remove it. Drag and drop to reorder.")
        self.tab_widget.selected_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tab_widget.selected_list.itemDoubleClicked.connect(self.tab_widget.remove_criterion)
        
        grid.addWidget(self.tab_widget.available_list, 0, 0)
        grid.addWidget(self.tab_widget.selected_list, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        
        set_plan_group = QGroupBox("Set Sorting Plan")
        set_plan_group.setToolTip("Options for optimizing letter-based sorting within sets")
        options_layout.addWidget(set_plan_group, 1)
        set_plan_layout = QVBoxLayout(set_plan_group)
        
        self.tab_widget.group_low_count_check = QCheckBox("Group low-count letters into piles")
        self.tab_widget.group_low_count_check.setChecked(True)
        self.tab_widget.group_low_count_check.setToolTip(
                "Combine letters with few cards into larger piles for more efficient sorting")
        set_plan_layout.addWidget(self.tab_widget.group_low_count_check)
        
        self.tab_widget.optimal_grouping_check = QCheckBox("Optimal grouping (max 3 letters per group)")
        self.tab_widget.optimal_grouping_check.setChecked(False)
        self.tab_widget.optimal_grouping_check.setToolTip(
                "Use optimal algorithm to group letters with maximum of 3 letters per pile for efficient physical sorting")
        set_plan_layout.addWidget(self.tab_widget.optimal_grouping_check)
        
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Min pile total:"))
        self.tab_widget.group_threshold_edit = QLineEdit("20")
        self.tab_widget.group_threshold_edit.setToolTip(
                "Minimum number of cards per pile when grouping letters together")
        threshold_layout.addWidget(self.tab_widget.group_threshold_edit)
        set_plan_layout.addLayout(threshold_layout)
        set_plan_layout.addStretch()
    
    def _create_run_section(self, layout: QVBoxLayout):
        group = QGroupBox("3. Generate Plan")
        layout.addWidget(group)
        h_layout = QHBoxLayout(group)
        h_layout.addStretch()
        self.tab_widget.run_button = QPushButton("Generate Sorting Plan")
        self.tab_widget.run_button.setToolTip(
                "Create a visual sorting plan based on your criteria (Shortcut: Ctrl+G)")
        self.tab_widget.run_button.clicked.connect(self.tab_widget.start_new_plan_generation)
        h_layout.addWidget(self.tab_widget.run_button)
        h_layout.addStretch()
    
    def _create_results_section(self, layout: QVBoxLayout):
        group = QGroupBox("4. Sorting Plan")
        layout.addWidget(group)
        results_layout = QVBoxLayout(group)
        
        top_bar_layout = QHBoxLayout()
        self.tab_widget.breadcrumb_layout = QHBoxLayout()
        self.tab_widget.breadcrumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        top_bar_layout.addLayout(self.tab_widget.breadcrumb_layout, 1)
        
        self.tab_widget.show_sorted_check = QCheckBox("Show Sorted Groups")
        self.tab_widget.show_sorted_check.setToolTip("Include already-sorted cards in the display")
        self.tab_widget.show_sorted_check.stateChanged.connect(self.tab_widget.on_show_sorted_toggled)
        top_bar_layout.addWidget(self.tab_widget.show_sorted_check)
        top_bar_layout.addStretch()
        
        self.tab_widget.mark_sorted_button = QPushButton("Mark Group as Sorted")
        self.tab_widget.mark_sorted_button.setToolTip(
                "Mark all cards in the selected group(s) as sorted (Shortcut: Space)")
        self.tab_widget.mark_sorted_button.clicked.connect(self.tab_widget.on_mark_group_button_clicked)
        self.tab_widget.mark_sorted_button.setVisible(False)
        top_bar_layout.addWidget(self.tab_widget.mark_sorted_button)
        
        self.tab_widget.export_button = QPushButton("Export View")
        self.tab_widget.export_button.setToolTip("Export the current view to a CSV file (Shortcut: Ctrl+E)")
        self.tab_widget.export_button.clicked.connect(self.tab_widget.export_current_view)
        self.tab_widget.export_button.setVisible(False)
        top_bar_layout.addWidget(self.tab_widget.export_button)
        
        results_layout.addLayout(top_bar_layout)
        
        self.tab_widget.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        self.tab_widget.filter_edit = QLineEdit()
        self.tab_widget.filter_edit.setPlaceholderText("Filter current view...")
        self.tab_widget.filter_edit.setToolTip("Type to filter the current view by group name")
        self.tab_widget.filter_edit.textChanged.connect(self.tab_widget.filter_current_view)
        self.tab_widget.filter_edit.setVisible(False)
        
        self.tab_widget.results_stack = QStackedWidget()
        left_layout.addWidget(self.tab_widget.filter_edit)
        left_layout.addWidget(self.tab_widget.results_stack)
        
        self.tab_widget.preview_panel = QWidget()
        right_layout = QVBoxLayout(self.tab_widget.preview_panel)
        
        self.tab_widget.card_image_label = QLabel("Select an individual card to see its image.")
        self.tab_widget.card_image_label.setObjectName("CardImageLabel")
        self.tab_widget.card_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tab_widget.card_image_label.setMinimumSize(220, 308)
        self.tab_widget.card_image_label.setToolTip("Card images appear here when you select individual cards")
        
        self.tab_widget.fetch_image_button = QPushButton("Fetch Image")
        self.tab_widget.fetch_image_button.setToolTip("Download and display the image for the selected card.")
        self.tab_widget.fetch_image_button.clicked.connect(self.tab_widget.on_fetch_image_clicked)
        self.tab_widget.fetch_image_button.setVisible(False)
        
        self.tab_widget.card_details_label = QLabel()
        self.tab_widget.card_details_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tab_widget.card_details_label.setWordWrap(True)
        self.tab_widget.card_details_label.setToolTip("Detailed card information appears here")
        
        right_layout.addWidget(self.tab_widget.card_image_label)
        right_layout.addWidget(self.tab_widget.fetch_image_button)
        right_layout.addWidget(self.tab_widget.card_details_label)
        right_layout.addStretch()
        
        self.tab_widget.main_splitter.addWidget(left_panel)
        self.tab_widget.main_splitter.addWidget(self.tab_widget.preview_panel)
        self.tab_widget.main_splitter.setSizes(self.tab_widget.splitter_sizes)
        
        results_layout.addWidget(self.tab_widget.main_splitter)
        
        self.tab_widget.status_label = QLabel()
        self.tab_widget.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        results_layout.addWidget(self.tab_widget.status_label)
        
        layout.setStretchFactor(group, 1)
