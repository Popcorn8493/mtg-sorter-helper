# ui/sorter_navigation.py - Navigation and breadcrumb logic for sorter tab

import collections
from typing import List
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
)

from core.models import Card, SortGroup
from ui.custom_widgets import NavigableTreeWidget
from ui.set_sorter_view import SetSorterView


class SorterNavigation:
    """Handles navigation and breadcrumb logic for the sorter tab"""

    def __init__(self, parent):
        self.parent = parent

    def add_breadcrumb(self, text: str, level: int):
        """Add breadcrumb to navigation"""
        if level > 0:
            self.parent.breadcrumb_layout.addWidget(QLabel(">"))
        btn = QPushButton(text.split(": ")[-1])
        btn.setObjectName("BreadcrumbButton")
        btn.clicked.connect(lambda: self.parent.navigate_and_refresh(level))
        self.parent.breadcrumb_layout.addWidget(btn)

    def navigate_to_level(self, level: int):
        """Navigate to specific level safely"""
        try:
            level = max(0, min(level, self.parent.results_stack.count() - 1))

            while self.parent.results_stack.count() > level + 1:
                widget_index = self.parent.results_stack.count() - 1
                widget = self.parent.results_stack.widget(widget_index)
                self.parent.results_stack.removeWidget(widget)
                if widget:
                    if hasattr(widget, "cleanup"):
                        widget.cleanup()
                    widget.deleteLater()

            target_breadcrumb_count = (level * 2) + 1
            while self.parent.breadcrumb_layout.count() > target_breadcrumb_count:
                item = self.parent.breadcrumb_layout.takeAt(
                    self.parent.breadcrumb_layout.count() - 1
                )
                if item and item.widget():
                    item.widget().deleteLater()

            if self.parent.results_stack.count() > level:
                self.parent.results_stack.setCurrentIndex(level)

            self.parent.filter_edit.clear()
            self.parent.filter_current_view("")
            self.parent.update_button_visibility()
        except Exception as e:
            self.parent.handle_ui_error(
                "navigate_to_level",
                e,
                additional_context=f"target_level: {level}, stack_count: {self.parent.results_stack.count() if self.parent.results_stack else 'None'}",
            )

    def navigate_and_refresh(self, level: int):
        """Navigate and refresh safely"""
        self.navigate_to_level(level)
        QTimer.singleShot(50, self.parent._refresh_current_view)

    def create_new_view(self, cards_in_group: List[Card], level: int):
        """Create new view with full functionality"""
        try:
            tree = NavigableTreeWidget()
            tree.cards_for_view = cards_in_group
            tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

            # Set up tree headers
            show_sorted = self.parent.show_sorted_check.isChecked()
            header_label = "Total Count" if show_sorted else "Unsorted Count"
            tree.setHeaderLabels(["Group", header_label])

            # Enable checkboxes for all items
            tree.setRootIsDecorated(True)
            tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            tree.setSortingEnabled(True)

            # Connect signals with proper handlers
            def item_clicked(item, column):
                try:
                    self.parent.handle_item_click(item, level + 1)
                except Exception as e:
                    self.parent.handle_ui_error("handle_item_click", e)

            tree.itemClicked.connect(item_clicked)

            # Connect double-click for drill-down
            def item_double_clicked(item, column):
                try:
                    self.parent.handle_item_click(item, level + 1)
                except Exception as e:
                    self.parent.handle_ui_error("Double-click handling", e)

            tree.itemDoubleClicked.connect(item_double_clicked)
            tree.drillDownRequested.connect(
                lambda item: self.parent.drill_down(item, level + 1)
            )
            tree.navigateUpRequested.connect(
                lambda: (
                    self.parent.navigate_and_refresh(level - 1) if level > 0 else None
                )
            )
            tree.currentItemChanged.connect(self.parent.update_button_visibility)
            tree.currentItemChanged.connect(self.parent.on_tree_selection_changed)
            tree.itemSortedToggled.connect(self.parent.on_item_sorted_toggled)

            # Determine sort criterion and generate breakdown
            self.parent.sort_order = self.parent._get_sort_order_safely()
            criterion = (
                self.parent.sort_order[level]
                if 0 <= level < len(self.parent.sort_order)
                else None
            )
            nodes = self.parent._generate_level_breakdown(cards_in_group, criterion)

            # Populate tree progressively
            tree._populate_tree_progressively(nodes, chunk_size=50)

            # Add to stack and set as current
            self.parent.results_stack.addWidget(tree)
            self.parent.results_stack.setCurrentWidget(tree)

        except Exception as e:
            self.parent.handle_ui_error(
                "create_new_view",
                e,
                additional_context=f"cards_count: {len(cards_in_group) if cards_in_group else 0}, level: {level}",
            )

    def create_set_sorter_view(self, cards_to_sort: List[Card], set_name: str):
        """Create SetSorterView"""
        try:
            view = SetSorterView(cards_to_sort, set_name, self.parent)
            self.parent.results_stack.addWidget(view)
            self.parent.results_stack.setCurrentWidget(view)
            self.parent._update_view_layout()
        except Exception as e:
            self.parent.handle_ui_error(
                "creating set sorter view",
                e,
                additional_context=f"set_name: {set_name}, cards_count: {len(cards_to_sort) if cards_to_sort else 0}",
            )

    def _generate_level_breakdown(
        self, current_cards: List[Card], criterion: str | None
    ) -> List[SortGroup]:
        """Generate breakdown for current level"""
        try:
            show_sorted = self.parent.show_sorted_check.isChecked()

            if not criterion or criterion == "Name":
                nodes = [
                    SortGroup(
                        group_name=c.name,
                        count=(c.quantity - c.sorted_count),
                        cards=[c],
                        is_card_leaf=True,
                    )
                    for c in current_cards
                ]
                for node in nodes:
                    node.total_count = node.cards[0].quantity
                    node.unsorted_count = node.count
                return sorted(nodes, key=lambda sg: sg.group_name or "")

            groups = collections.defaultdict(list)
            for i, card in enumerate(current_cards):
                try:
                    value = self.parent._get_nested_value(card, criterion)
                    groups[value].append(card)
                except Exception as e:
                    self.parent.handle_silent_error(
                        f"getting nested value for card {card.name}", e
                    )
                    groups["ERROR"].append(card)

            nodes = []
            for name, card_group in sorted(groups.items()):
                try:
                    unsorted_count = sum(
                        max(0, c.quantity - c.sorted_count) for c in card_group
                    )

                    if not show_sorted and unsorted_count == 0:
                        continue

                    total_count = sum(c.quantity for c in card_group)
                    display_count = total_count if show_sorted else unsorted_count

                    node = SortGroup(
                        group_name=f"{criterion}: {name}",
                        count=display_count,
                        cards=card_group,
                    )
                    node.unsorted_count = unsorted_count
                    node.total_count = total_count
                    nodes.append(node)
                except Exception as e:
                    self.parent.handle_silent_error(
                        f"creating node for group {name}", e
                    )
                    continue

            return nodes

        except Exception as e:
            self.parent.handle_ui_error(
                "_generate_level_breakdown",
                e,
                additional_context=f"criterion: {criterion}, cards_count: {len(current_cards) if current_cards else 0}",
            )
            return []

    def _get_nested_value(self, card: Card, key: str) -> str:
        """Get nested value for sorting, now with robust handling of missing data."""
        if key == "First Letter":
            name = getattr(card, "name", "")
            return name[0].upper() if name and name != "N/A" else "#"
        if key == "Set":
            return getattr(card, "set_name", "N/A") or "N/A"
        if key == "Rarity":
            rarity = getattr(card, "rarity", "N/A") or "N/A"
            return rarity.capitalize()
        if key == "Type Line":
            type_line = getattr(card, "type_line", "N/A") or "N/A"
            return type_line.split("//")[0].strip()
        if key == "Condition":
            condition = getattr(card, "condition", "N/A") or "N/A"
            return condition.capitalize()
        if key == "Color Identity":
            ci = getattr(card, "color_identity", [])
            return "".join(sorted(ci)) or "Colorless"
        if key == "Commander Staple":
            rank = getattr(card, "edhrec_rank", None)
            return "Staple (Top 1000)" if rank and rank <= 1000 else "Not a Staple"
        return "N/A"

    def _get_cards_from_item(self, item: QTreeWidgetItem) -> List[Card]:
        """Get cards from tree item safely"""
        if not item:
            return []
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if item_data:
            if isinstance(item_data, list) and all(
                isinstance(c, Card) for c in item_data
            ):
                return item_data
            elif hasattr(item_data, "cards"):
                return item_data.cards
        return []

    def _get_sort_order_safely(self) -> List[str]:
        """Safely retrieve sort order from selected_list"""
        try:
            if not self.parent.selected_list:
                print("ERROR: selected_list is None")
                return []

            sort_order = []
            for i in range(self.parent.selected_list.count()):
                item = self.parent.selected_list.item(i)
                if item is None:
                    print(f"WARNING: selected_list.item({i}) returned None")
                    continue
                text = item.text()
                if text:
                    sort_order.append(text)
                else:
                    print(f"WARNING: item {i} has empty text")
            return sort_order

        except Exception as e:
            self.parent.handle_ui_error(
                "retrieving sort order",
                e,
                additional_context=f"selected_list_count: {self.parent.selected_list.count() if self.parent.selected_list else 'None'}",
            )
            return []

    def _should_show_card_preview(self, item: QTreeWidgetItem, next_level: int) -> bool:
        """Determine if card preview should be shown for this item"""
        if not item:
            return False

        # Check if we're currently in SetSorterView (letter piles view)
        current_widget = self.parent.results_stack.currentWidget()
        if isinstance(current_widget, SetSorterView):
            # Never show card preview for letter piles in SetSorterView
            return False

        # Get current sort order to determine what level we're at
        sort_order = self.parent._get_sort_order_safely()
        if not sort_order:
            return False

        current_level = next_level - 1

        # If we're already at or past the final level (Name), this should be an individual card
        if current_level >= len(sort_order) - 1:
            return True

        # If the current level is Name, then we're clicking on individual cards
        if 0 <= current_level < len(sort_order) and sort_order[current_level] == "Name":
            return True

        # For all other cases (groups like Set, Rarity, Type, etc.), don't show preview
        return False

    def _should_show_card_preview_for_selection(self, item: QTreeWidgetItem) -> bool:
        """Determine if card preview should be shown for tree selection changes"""
        if not item:
            return False

        # Check if we're currently in SetSorterView (letter piles view)
        current_widget = self.parent.results_stack.currentWidget()
        if isinstance(current_widget, SetSorterView):
            # Never show card preview for letter piles in SetSorterView
            return False

        # For regular tree widgets, check if this represents individual cards
        # We can infer this by checking if the item has card data vs group data
        cards = self._get_cards_from_item(item)
        if not cards:
            return False

        # If there's only one card and we're at a deep enough level, show preview
        # This is a heuristic: groups typically have many cards, individual items have 1
        if len(cards) == 1:
            return True

        # For groups with multiple cards, don't show preview
        return False

    def clear_layout(self, layout: QHBoxLayout):
        """Clear layout widgets"""
        while layout.count():
            if child := layout.takeAt(0).widget():
                child.deleteLater()
