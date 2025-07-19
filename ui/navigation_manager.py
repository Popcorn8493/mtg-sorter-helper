# ui/navigation_manager.py

from typing import List, Optional, Dict, Any, Callable
from PyQt6.QtWidgets import QWidget, QStackedWidget, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QObject, pyqtSignal as Signal

from core.models import Card, SortGroup
from core.sorter_planner import SorterPlanner
from ui.custom_widgets import NavigableTreeWidget


class NavigationManager(QObject):
    """Manages navigation between different views in the sorting interface."""
    
    # Signals
    view_changed = Signal(str)  # Emitted when the view changes
    breadcrumb_updated = Signal(list)  # Emitted when breadcrumbs change
    
    def __init__(self, results_stack: QStackedWidget, breadcrumb_layout: QHBoxLayout):
        super().__init__()
        self.results_stack = results_stack
        self.breadcrumb_layout = breadcrumb_layout
        self.planner = SorterPlanner()
        
        # Navigation state
        self.current_path: List[str] = []
        self.current_sort_groups: List[SortGroup] = []
        self.current_cards: List[Card] = []
        self.current_sort_order: List[str] = []
        
        # View factory functions
        self.view_factories: Dict[str, Callable] = {}
        
        # Navigation history for back/forward
        self.history: List[Dict[str, Any]] = []
        self.history_index: int = -1
        
    def register_view_factory(self, view_type: str, factory_func: Callable):
        """Register a factory function for creating views of a specific type."""
        self.view_factories[view_type] = factory_func
    
    def navigate_to_root(self, cards: List[Card], sort_order: List[str]):
        """Navigate to the root sorting view."""
        self.current_cards = cards
        self.current_sort_order = sort_order
        self.current_path = []
        
        # Create root sorting plan
        self.current_sort_groups = self.planner.create_sorting_plan(cards, sort_order)
        
        # Create and display root view
        self._create_and_show_view('root')
        self._update_breadcrumbs()
        self._add_to_history()
    
    def navigate_to_group(self, group_name: str, level: int):
        """Navigate to a specific group at a given level."""
        if level > len(self.current_path):
            # Navigating deeper
            self.current_path.append(group_name)
        else:
            # Navigating to a different path at the same or higher level
            self.current_path = self.current_path[:level] + [group_name]
        
        # Get the cards for this path
        cards_at_path = self.planner.get_cards_at_path(self.current_sort_groups, self.current_path)
        
        # Determine what view to create
        if level < len(self.current_sort_order) - 1:
            # Still have more sorting levels - create hierarchical view
            remaining_sort_order = self.current_sort_order[level + 1:]
            sub_groups = self.planner.create_sorting_plan(cards_at_path, remaining_sort_order)
            self._create_and_show_hierarchical_view(sub_groups, cards_at_path)
        else:
            # At the deepest level - create card list view
            self._create_and_show_card_list_view(cards_at_path)
        
        self._update_breadcrumbs()
        self._add_to_history()
    
    def navigate_to_set_sorter(self, cards: List[Card], set_name: str):
        """Navigate to the set sorter view."""
        self.current_cards = cards
        self.current_path = ['Set Sorter', set_name]
        
        # Create set sorter view
        self._create_and_show_view('set_sorter', cards=cards, set_name=set_name)
        self._update_breadcrumbs()
        self._add_to_history()
    
    def navigate_back(self):
        """Navigate back in history."""
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_from_history()
    
    def navigate_forward(self):
        """Navigate forward in history."""
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self._restore_from_history()
    
    def navigate_to_breadcrumb(self, index: int):
        """Navigate to a specific breadcrumb level."""
        if 0 <= index < len(self.current_path):
            # Navigate to the specified level
            self.current_path = self.current_path[:index + 1]
            
            if index == 0 and self.current_path[0] == 'Set Sorter':
                # Navigate to set sorter
                set_name = self.current_path[1] if len(self.current_path) > 1 else 'Unknown Set'
                self.navigate_to_set_sorter(self.current_cards, set_name)
            else:
                # Navigate to group
                self.navigate_to_group(self.current_path[-1], len(self.current_path) - 1)
        elif index == -1:
            # Navigate to root
            self.navigate_to_root(self.current_cards, self.current_sort_order)
    
    def _create_and_show_view(self, view_type: str, **kwargs):
        """Create and display a view of the specified type."""
        if view_type not in self.view_factories:
            print(f"Warning: No factory registered for view type: {view_type}")
            return
        
        # Remove current view if it exists
        if self.results_stack.currentWidget():
            current_widget = self.results_stack.currentWidget()
            self.results_stack.removeWidget(current_widget)
            current_widget.deleteLater()
        
        # Create new view
        factory_func = self.view_factories[view_type]
        new_view = factory_func(**kwargs)
        
        # Add to stack and show
        self.results_stack.addWidget(new_view)
        self.results_stack.setCurrentWidget(new_view)
        
        # Emit signal
        self.view_changed.emit(view_type)
    
    def _create_and_show_hierarchical_view(self, sort_groups: List[SortGroup], cards: List[Card]):
        """Create and show a hierarchical tree view."""
        self._create_and_show_view('hierarchical', sort_groups=sort_groups, cards=cards)
    
    def _create_and_show_card_list_view(self, cards: List[Card]):
        """Create and show a card list view."""
        self._create_and_show_view('card_list', cards=cards)
    
    def _update_breadcrumbs(self):
        """Update the breadcrumb navigation."""
        # Clear existing breadcrumbs
        for i in reversed(range(self.breadcrumb_layout.count())):
            child = self.breadcrumb_layout.itemAt(i)
            if child:
                widget = child.widget()
                if widget:
                    self.breadcrumb_layout.removeWidget(widget)
                    widget.deleteLater()
        
        # Add root breadcrumb
        root_button = QPushButton("Root")
        root_button.setFlat(True)
        root_button.setStyleSheet("QPushButton { text-decoration: underline; color: #007acc; }")
        root_button.clicked.connect(lambda: self.navigate_to_breadcrumb(-1))
        self.breadcrumb_layout.addWidget(root_button)
        
        # Add breadcrumbs for current path
        for i, path_element in enumerate(self.current_path):
            # Add separator
            separator = QLabel(" > ")
            separator.setStyleSheet("color: #666666;")
            self.breadcrumb_layout.addWidget(separator)
            
            # Add breadcrumb button
            if i == len(self.current_path) - 1:
                # Current level - not clickable
                current_label = QLabel(path_element)
                current_label.setStyleSheet("font-weight: bold; color: white;")
                self.breadcrumb_layout.addWidget(current_label)
            else:
                # Previous level - clickable
                breadcrumb_button = QPushButton(path_element)
                breadcrumb_button.setFlat(True)
                breadcrumb_button.setStyleSheet("QPushButton { text-decoration: underline; color: #007acc; }")
                breadcrumb_button.clicked.connect(lambda checked, idx=i: self.navigate_to_breadcrumb(idx))
                self.breadcrumb_layout.addWidget(breadcrumb_button)
        
        # Add stretch to push breadcrumbs to the left
        self.breadcrumb_layout.addStretch()
        
        # Emit signal
        self.breadcrumb_updated.emit(self.current_path.copy())
    
    def _add_to_history(self):
        """Add current state to navigation history."""
        state = {
            'path': self.current_path.copy(),
            'sort_groups': self.current_sort_groups.copy(),
            'cards': self.current_cards.copy(),
            'sort_order': self.current_sort_order.copy()
        }
        
        # Remove any forward history if we're not at the end
        if self.history_index < len(self.history) - 1:
            self.history = self.history[:self.history_index + 1]
        
        self.history.append(state)
        self.history_index = len(self.history) - 1
        
        # Limit history size
        if len(self.history) > 50:
            self.history = self.history[-50:]
            self.history_index = len(self.history) - 1
    
    def _restore_from_history(self):
        """Restore state from history."""
        if 0 <= self.history_index < len(self.history):
            state = self.history[self.history_index]
            self.current_path = state['path'].copy()
            self.current_sort_groups = state['sort_groups'].copy()
            self.current_cards = state['cards'].copy()
            self.current_sort_order = state['sort_order'].copy()
            
            # Recreate the view based on current state
            if not self.current_path:
                # At root
                self._create_and_show_view('root')
            elif self.current_path[0] == 'Set Sorter':
                # In set sorter
                set_name = self.current_path[1] if len(self.current_path) > 1 else 'Unknown Set'
                self._create_and_show_view('set_sorter', cards=self.current_cards, set_name=set_name)
            else:
                # In hierarchical view
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
        """Get the current navigation path."""
        return self.current_path.copy()
    
    def get_current_cards(self) -> List[Card]:
        """Get the cards at the current navigation level."""
        return self.current_cards.copy()
    
    def can_navigate_back(self) -> bool:
        """Check if back navigation is possible."""
        return self.history_index > 0
    
    def can_navigate_forward(self) -> bool:
        """Check if forward navigation is possible."""
        return self.history_index < len(self.history) - 1
    
    def clear_history(self):
        """Clear navigation history."""
        self.history.clear()
        self.history_index = -1