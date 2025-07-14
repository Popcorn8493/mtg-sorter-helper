from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent


class SortableTreeWidgetItem(QTreeWidgetItem):
    """Enhanced tree widget item with improved sorting capabilities"""

    def __lt__(self, other):
        """Custom sorting logic for tree items"""
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0

        try:
            # For the count column (usually column 1), sort numerically
            if column == 1:
                self_value = int(self.text(column))
                other_value = int(other.text(column))
                return self_value < other_value
        except (ValueError, IndexError):
            # Fall back to string comparison if numeric conversion fails
            pass

        # For other columns, sort alphabetically (case-insensitive)
        self_text = self.text(column).lower()
        other_text = other.text(column).lower()

        # Handle special prefixes (like "Set: ", "Rarity: ", etc.)
        if ': ' in self_text and ': ' in other_text:
            # Extract the part after the colon for comparison
            self_suffix = self_text.split(': ', 1)[1]
            other_suffix = other_text.split(': ', 1)[1]
            return self_suffix < other_suffix

        return self_text < other_text


class NavigableTreeWidget(QTreeWidget):
    """Enhanced QTreeWidget with comprehensive keyboard navigation and user feedback"""

    # Signals for different navigation actions
    drillDownRequested = pyqtSignal(QTreeWidgetItem)
    navigateUpRequested = pyqtSignal()
    markAsortedRequested = pyqtSignal(list)  # List of selected items

    def __init__(self, parent=None):
        super().__init__(parent)

        # Enable tooltips and help text
        self.setToolTip(
            "Keyboard Navigation:\n"
            "• Enter/Return - Drill down into selected group\n"
            "• Backspace - Navigate back up one level\n"
            "• Space - Mark selected group(s) as sorted\n"
            "• Ctrl+A - Select all items\n"
            "• Arrow keys - Navigate between items\n"
            "• F2 - Show item details (if available)\n\n"
            "Mouse:\n"
            "• Double-click - Drill down\n"
            "• Right-click - Context menu (if available)"
        )

        # Track navigation history for better user experience
        self.navigation_history = []
        self.max_history_size = 10

        # Enable extended selection by default for multiple item operations
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)

        # Connect signals for enhanced feedback
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def keyPressEvent(self, event: QKeyEvent):
        """Enhanced keyboard event handling with comprehensive shortcuts"""
        key = event.key()
        modifiers = event.modifiers()

        # Get currently selected items
        selected_items = self.selectedItems()
        current_item = self.currentItem()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Drill down into selected item
            if current_item:
                self._add_to_history()
                self.drillDownRequested.emit(current_item)
                event.accept()
                return

        elif key == Qt.Key.Key_Backspace:
            # Navigate up one level
            self.navigateUpRequested.emit()
            event.accept()
            return

        elif key == Qt.Key.Key_Space:
            # Mark selected items as sorted
            if selected_items:
                self.markAsortedRequested.emit(selected_items)
                event.accept()
                return

        elif key == Qt.Key.Key_F2:
            # Show item details (if available)
            if current_item:
                self._show_item_details(current_item)
                event.accept()
                return

        elif key == Qt.Key.Key_Escape:
            # Clear selection
            self.clearSelection()
            event.accept()
            return

        elif key == Qt.Key.Key_Home:
            # Go to first item
            if self.topLevelItemCount() > 0:
                first_item = self.topLevelItem(0)
                self.setCurrentItem(first_item)
                event.accept()
                return

        elif key == Qt.Key.Key_End:
            # Go to last item
            if self.topLevelItemCount() > 0:
                last_item = self.topLevelItem(self.topLevelItemCount() - 1)
                self.setCurrentItem(last_item)
                event.accept()
                return

        elif key == Qt.Key.Key_PageUp:
            # Select multiple items upward
            if modifiers & Qt.KeyboardModifier.ShiftModifier and current_item:
                self._extend_selection_up(5)  # Select 5 items up
                event.accept()
                return

        elif key == Qt.Key.Key_PageDown:
            # Select multiple items downward
            if modifiers & Qt.KeyboardModifier.ShiftModifier and current_item:
                self._extend_selection_down(5)  # Select 5 items down
                event.accept()
                return

        elif key == Qt.Key.Key_A and modifiers & Qt.KeyboardModifier.ControlModifier:
            # Select all items (Ctrl+A)
            self.selectAll()
            event.accept()
            return

        elif key >= Qt.Key.Key_A and key <= Qt.Key.Key_Z:
            # Quick navigation by first letter
            if not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
                letter = chr(key).upper()
                self._navigate_to_letter(letter)
                event.accept()
                return

        # If no custom handling, pass to parent
        super().keyPressEvent(event)

    def _add_to_history(self):
        """Add current state to navigation history"""
        current_item = self.currentItem()
        if current_item:
            item_text = current_item.text(0)
            self.navigation_history.append(item_text)

            # Limit history size
            if len(self.navigation_history) > self.max_history_size:
                self.navigation_history.pop(0)

    def _show_item_details(self, item: QTreeWidgetItem):
        """Show detailed information about an item (if available)"""
        # This could be expanded to show a tooltip or status bar message
        # with detailed information about the selected group
        details = []
        details.append(f"Group: {item.text(0)}")

        if item.columnCount() > 1:
            details.append(f"Count: {item.text(1)}")

        # If the item has associated card data, show more details
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if item_data and isinstance(item_data, list):
            card_count = len(item_data)
            details.append(f"Contains {card_count} unique cards")

            # Show breakdown by type if available
            if hasattr(item_data[0], 'type_line'):
                type_counts = {}
                for card in item_data:
                    card_type = card.type_line.split('—')[0].strip()
                    type_counts[card_type] = type_counts.get(card_type, 0) + 1

                if type_counts:
                    details.append("Types: " + ", ".join(f"{t}({c})" for t, c in sorted(type_counts.items())))

        # Show details in tooltip (temporary)
        tooltip_text = "\n".join(details)
        self.setToolTip(tooltip_text)

        # Also emit a signal if parent wants to handle this
        # self.itemDetailsRequested.emit(item, tooltip_text)

    def _extend_selection_up(self, count: int):
        """Extend selection upward by count items"""
        current_item = self.currentItem()
        if not current_item:
            return

        current_index = self.indexOfTopLevelItem(current_item)
        if current_index == -1:
            return

        # Select items upward
        for i in range(max(0, current_index - count), current_index + 1):
            item = self.topLevelItem(i)
            if item:
                item.setSelected(True)

    def _extend_selection_down(self, count: int):
        """Extend selection downward by count items"""
        current_item = self.currentItem()
        if not current_item:
            return

        current_index = self.indexOfTopLevelItem(current_item)
        if current_index == -1:
            return

        # Select items downward
        for i in range(current_index, min(self.topLevelItemCount(), current_index + count + 1)):
            item = self.topLevelItem(i)
            if item:
                item.setSelected(True)

    def _navigate_to_letter(self, letter: str):
        """Navigate to the first item starting with the given letter"""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item:
                item_text = item.text(0).upper()
                # Handle items with prefixes like "Set: ABC"
                if ': ' in item_text:
                    item_text = item_text.split(': ', 1)[1]

                if item_text.startswith(letter):
                    self.setCurrentItem(item)
                    self.scrollToItem(item)
                    break

    def _on_selection_changed(self):
        """Handle selection changes to provide user feedback"""
        selected_count = len(self.selectedItems())

        if selected_count == 0:
            tooltip = (
                "No items selected.\n\n"
                "Use arrow keys to navigate, Enter to drill down, "
                "Space to mark as sorted."
            )
        elif selected_count == 1:
            current = self.currentItem()
            if current:
                tooltip = (
                    f"Selected: {current.text(0)}\n\n"
                    "Enter - Drill down\n"
                    "Space - Mark as sorted\n"
                    "Backspace - Go back"
                )
            else:
                tooltip = "1 item selected"
        else:
            tooltip = (
                f"{selected_count} items selected\n\n"
                "Space - Mark all selected as sorted\n"
                "Escape - Clear selection"
            )

        self.setToolTip(tooltip)

    def mousePressEvent(self, event):
        """Enhanced mouse handling"""
        super().mousePressEvent(event)

        # Update tooltip based on what was clicked
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item:
                self._show_item_details(item)

    def get_navigation_history(self):
        """Get the navigation history for debugging or advanced features"""
        return self.navigation_history.copy()

    def clear_navigation_history(self):
        """Clear the navigation history"""
        self.navigation_history.clear()


class EnhancedListWidget:
    """Enhanced list widget with better keyboard navigation (could be implemented if needed)"""
    pass


class StatusAwareWidget:
    """Mixin class for widgets that want to provide status updates"""

    def __init__(self):
        self._status_message = ""
        self._status_timeout = 0

    def set_status_message(self, message: str, timeout: int = 0):
        """Set a status message that can be displayed in UI"""
        self._status_message = message
        self._status_timeout = timeout

    def get_status_message(self) -> str:
        """Get the current status message"""
        return self._status_message

    def clear_status_message(self):
        """Clear the current status message"""
        self._status_message = ""
        self._status_timeout = 0