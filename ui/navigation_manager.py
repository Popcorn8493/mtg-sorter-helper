from typing import List, Dict, Any, Callable
from PyQt6.QtCore import QObject, pyqtSignal as Signal
from PyQt6.QtWidgets import QStackedWidget, QHBoxLayout, QPushButton, QLabel
from core.models import Card, SortGroup
from core.sorter_planner import SorterPlanner

class NavigationManager(QObject):
    view_changed = Signal(str)
    breadcrumb_updated = Signal(list)

    def __init__(self, results_stack: QStackedWidget, breadcrumb_layout: QHBoxLayout):
        super().__init__()
        self.results_stack = results_stack
        self.breadcrumb_layout = breadcrumb_layout
        self.planner = SorterPlanner()
        self.current_path: List[str] = []
        self.current_sort_groups: List[SortGroup] = []
        self.current_cards: List[Card] = []
        self.current_sort_order: List[str] = []
        self.view_factories: Dict[str, Callable] = {}
        self.history: List[Dict[str, Any]] = []
        self.history_index: int = -1

    def register_view_factory(self, view_type: str, factory_func: Callable):
        self.view_factories[view_type] = factory_func

    def navigate_to_root(self, cards: List[Card], sort_order: List[str]):
        self.current_cards = cards
        self.current_sort_order = sort_order
        self.current_path = []
        self.current_sort_groups = self.planner.create_sorting_plan(cards, sort_order)
        self._create_and_show_view('root')
        self._update_breadcrumbs()
        self._add_to_history()

    def navigate_to_group(self, group_name: str, level: int):
        if level > len(self.current_path):
            self.current_path.append(group_name)
        else:
            self.current_path = self.current_path[:level] + [group_name]
        cards_at_path = self.planner.get_cards_at_path(self.current_sort_groups, self.current_path)
        if level < len(self.current_sort_order) - 1:
            remaining_sort_order = self.current_sort_order[level + 1:]
            sub_groups = self.planner.create_sorting_plan(cards_at_path, remaining_sort_order)
            self._create_and_show_hierarchical_view(sub_groups, cards_at_path)
        else:
            self._create_and_show_card_list_view(cards_at_path)
        self._update_breadcrumbs()
        self._add_to_history()

    def navigate_to_set_sorter(self, cards: List[Card], set_name: str):
        self.current_cards = cards
        self.current_path = ['Set Sorter', set_name]
        self._create_and_show_view('set_sorter', cards=cards, set_name=set_name)
        self._update_breadcrumbs()
        self._add_to_history()

    def navigate_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_from_history()

    def navigate_forward(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._restore_from_history()

    def navigate_to_breadcrumb(self, index: int):
        if 0 <= index < len(self.current_path):
            self.current_path = self.current_path[:index + 1]
            if index == 0 and self.current_path[0] == 'Set Sorter':
                set_name = self.current_path[1] if len(self.current_path) > 1 else 'Unknown Set'
                self.navigate_to_set_sorter(self.current_cards, set_name)
            else:
                self.navigate_to_group(self.current_path[-1], len(self.current_path) - 1)
        elif index == -1:
            self.navigate_to_root(self.current_cards, self.current_sort_order)

    def _create_and_show_view(self, view_type: str, **kwargs):
        if view_type not in self.view_factories:
            print(f'Warning: No factory registered for view type: {view_type}')
            return
        if self.results_stack.currentWidget():
            current_widget = self.results_stack.currentWidget()
            self.results_stack.removeWidget(current_widget)
            current_widget.deleteLater()
        factory_func = self.view_factories[view_type]
        new_view = factory_func(**kwargs)
        self.results_stack.addWidget(new_view)
        self.results_stack.setCurrentWidget(new_view)
        self.view_changed.emit(view_type)

    def _create_and_show_hierarchical_view(self, sort_groups: List[SortGroup], cards: List[Card]):
        self._create_and_show_view('hierarchical', sort_groups=sort_groups, cards=cards)

    def _create_and_show_card_list_view(self, cards: List[Card]):
        self._create_and_show_view('card_list', cards=cards)

    def _update_breadcrumbs(self):
        for i in reversed(range(self.breadcrumb_layout.count())):
            child = self.breadcrumb_layout.itemAt(i)
            if child:
                widget = child.widget()
                if widget:
                    self.breadcrumb_layout.removeWidget(widget)
                    widget.deleteLater()
        self._create_breadcrumb('Root', lambda: self.navigate_to_breadcrumb(-1))
        for i, path_element in enumerate(self.current_path):
            if i == len(self.current_path) - 1:
                current_label = QLabel(path_element)
                current_label.setStyleSheet('font-weight: bold; color: white;')
                self.breadcrumb_layout.addWidget(current_label)
            else:
                self._create_breadcrumb(path_element, lambda idx=i: self.navigate_to_breadcrumb(idx))
        self.breadcrumb_layout.addStretch()
        self.breadcrumb_updated.emit(self.current_path.copy())

    def _create_breadcrumb(self, label: str, callback):
        if self.breadcrumb_layout.count() > 0:
            separator = QLabel(' › ')
            separator.setStyleSheet('color: #666;')
            self.breadcrumb_layout.addWidget(separator)
        breadcrumb_button = QPushButton(label)
        breadcrumb_button.setObjectName('BreadcrumbButton')
        breadcrumb_button.clicked.connect(callback)
        self.breadcrumb_layout.addWidget(breadcrumb_button)

    def _add_to_history(self):
        state = {'path': self.current_path.copy(), 'sort_groups': self.current_sort_groups.copy(), 'cards': self.current_cards.copy(), 'sort_order': self.current_sort_order.copy()}
        if self.history_index < len(self.history) - 1:
            self.history = self.history[:self.history_index + 1]
        self.history.append(state)
        self.history_index = len(self.history) - 1
        if len(self.history) > 50:
            self.history = self.history[-50:]
            self.history_index = len(self.history) - 1

    def _restore_from_history(self):
        if 0 <= self.history_index < len(self.history):
            state = self.history[self.history_index]
            self.current_path = state['path'].copy()
            self.current_sort_groups = state['sort_groups'].copy()
            self.current_cards = state['cards'].copy()
            self.current_sort_order = state['sort_order'].copy()
            if not self.current_path:
                self._create_and_show_view('root')
            elif self.current_path[0] == 'Set Sorter':
                set_name = self.current_path[1] if len(self.current_path) > 1 else 'Unknown Set'
                self._create_and_show_view('set_sorter', cards=self.current_cards, set_name=set_name)
            else:
                cards_at_path = self.planner.get_cards_at_path(self.current_sort_groups, self.current_path)
                level = len(self.current_path) - 1
                if level < len(self.current_sort_order) - 1:
                    remaining_sort_order = self.current_sort_order[level + 1:]
                    sub_groups = self.planner.create_sorting_plan(cards_at_path, remaining_sort_order)
                    self._create_and_show_hierarchical_view(sub_groups, cards_at_path)
                else:
                    self._create_and_show_card_list_view(cards_at_path)
            self._update_breadcrumbs()

    def get_current_path(self) -> List[str]:
        return self.current_path.copy()

    def get_current_cards(self) -> List[Card]:
        return self.current_cards.copy()

    def can_navigate_back(self) -> bool:
        return self.history_index > 0

    def can_navigate_forward(self) -> bool:
        return self.history_index < len(self.history) - 1

    def clear_history(self):
        self.history.clear()
        self.history_index = -1