from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from ui.widget_factory import WidgetFactory, SorterTabWidgetConfigs

class SorterTabUi:

    def __init__(self, tab_widget):
        self.tab_widget = tab_widget
        self.widget_factory = WidgetFactory(tab_widget)

    def setup_ui(self, main_layout: QVBoxLayout):
        self._create_layout_widgets()
        self._create_all_widgets()
        self._create_import_section(main_layout)
        self._create_options_section(main_layout)
        self._create_run_section(main_layout)
        self._create_results_section(main_layout)

    def _create_all_widgets(self):
        all_configs = SorterTabWidgetConfigs.get_all_configs()
        for section_name, configs in all_configs.items():
            for config in configs:
                if config.name == 'breadcrumb_layout':
                    continue
                self._setup_widget_connections(config)
                widget = self.widget_factory.create_widget(config)
                setattr(self.tab_widget, config.name, widget)

    def _setup_widget_connections(self, config):
        connections_map = {'import_button': {'clicked': self.tab_widget.import_csv}, 'reset_progress_button': {'clicked': self.tab_widget.reset_sort_progress}, 'available_list': {'itemDoubleClicked': self.tab_widget.add_criterion}, 'selected_list': {'itemDoubleClicked': self.tab_widget.remove_criterion}, 'run_button': {'clicked': self.tab_widget.start_new_plan_generation}, 'show_sorted_check': {'stateChanged': self.tab_widget.on_show_sorted_toggled}, 'mark_sorted_button': {'clicked': self.tab_widget.on_mark_group_button_clicked}, 'export_button': {'clicked': self.tab_widget.export_current_view}, 'filter_edit': {'textChanged': self.tab_widget.filter_current_view}}
        if config.name in connections_map:
            config.connections = connections_map[config.name]

    def _create_layout_widgets(self):
        breadcrumb_widget = QWidget()
        breadcrumb_layout = QHBoxLayout(breadcrumb_widget)
        breadcrumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        setattr(self.tab_widget, 'breadcrumb_layout', breadcrumb_layout)
        setattr(self.tab_widget, 'breadcrumb_widget', breadcrumb_widget)

    def _create_import_section(self, layout: QVBoxLayout):
        group = QGroupBox('1. Import Collection')
        layout.addWidget(group)
        group_layout = QVBoxLayout(group)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.tab_widget.import_button)
        button_layout.addStretch()
        button_layout.addWidget(self.tab_widget.reset_progress_button)
        group_layout.addLayout(button_layout)
        group_layout.addWidget(self.tab_widget.file_label)
        group_layout.addWidget(self.tab_widget.progress_bar)

    def _create_options_section(self, layout: QVBoxLayout):
        options_group = QGroupBox('2. Sorting Options')
        options_layout = QHBoxLayout(options_group)
        layout.addWidget(options_group)
        sort_order_group = QGroupBox('Sort Order')
        sort_order_group.setToolTip("Define the hierarchy for organizing your cards. Double-click to move criteria between lists. Drag-and-drop within the 'Selected' list to reorder.")
        options_layout.addWidget(sort_order_group, 2)
        grid = QGridLayout(sort_order_group)
        grid.addWidget(self.tab_widget.available_list, 0, 0)
        grid.addWidget(self.tab_widget.selected_list, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        set_plan_group = QGroupBox('Set Sorting Plan')
        set_plan_group.setToolTip('Options for optimizing letter-based sorting within sets')
        options_layout.addWidget(set_plan_group, 1)
        set_plan_layout = QVBoxLayout(set_plan_group)
        set_plan_layout.addWidget(self.tab_widget.group_low_count_check)
        set_plan_layout.addWidget(self.tab_widget.optimal_grouping_check)
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel('Min pile total:'))
        threshold_layout.addWidget(self.tab_widget.group_threshold_edit)
        set_plan_layout.addLayout(threshold_layout)
        set_plan_layout.addStretch()

    def _create_run_section(self, layout: QVBoxLayout):
        group = QGroupBox('3. Generate Plan')
        layout.addWidget(group)
        h_layout = QHBoxLayout(group)
        h_layout.addStretch()
        h_layout.addWidget(self.tab_widget.run_button)
        h_layout.addStretch()

    def _create_results_section(self, layout: QVBoxLayout):
        group = QGroupBox('4. Sorting Plan')
        layout.addWidget(group)
        results_layout = QVBoxLayout(group)
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addWidget(self.tab_widget.breadcrumb_widget, 1)
        top_bar_layout.addWidget(self.tab_widget.show_sorted_check)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self.tab_widget.mark_sorted_button)
        top_bar_layout.addWidget(self.tab_widget.export_button)
        results_layout.addLayout(top_bar_layout)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self.tab_widget.filter_edit)
        left_layout.addWidget(self.tab_widget.results_stack)
        right_layout = QVBoxLayout(self.tab_widget.preview_panel)
        right_layout.addWidget(self.tab_widget.card_details_label)
        right_layout.addStretch()
        self.tab_widget.main_splitter.addWidget(left_panel)
        self.tab_widget.main_splitter.addWidget(self.tab_widget.preview_panel)
        results_layout.addWidget(self.tab_widget.main_splitter)
        results_layout.addWidget(self.tab_widget.status_label)
        layout.setStretchFactor(group, 1)