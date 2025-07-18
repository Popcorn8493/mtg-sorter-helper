# ui/set_sorter_view.py

import collections
import string
from typing import List, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, 
                             QLabel, QMessageBox, QPushButton, QSplitter, QTreeWidgetItem, 
                             QTreeWidgetItemIterator, QVBoxLayout, QWidget)
from PyQt6.QtGui import QPixmap

from core.models import Card, SortGroup
from ui.custom_widgets import NavigableTreeWidget

if TYPE_CHECKING:
    from ui.sorter_tab import ManaBoxSorterTab


class SetSorterView(QWidget):
    """A dedicated widget for the 'Sort This Set' view with simple stack overflow prevention."""
    
    def __init__(self, cards_to_sort: List[Card], set_name: str, parent_tab: 'ManaBoxSorterTab'):
        super().__init__()
        self.cards_to_sort = cards_to_sort
        self.set_name = set_name
        self.parent_tab = parent_tab
        
        # FIXED: Simple operation flag to prevent recursion
        self._is_generating = False
        self._is_destroyed = False
        self._in_item_click = False
        
        self.canvas = None
        self.ax = None
        self._setup_ui()
        
        # FIXED: Delayed startup
        QTimer.singleShot(200, self._safe_initial_setup)
    
    def _safe_initial_setup(self):
        """Safe initial setup"""
        if not self._is_destroyed and not self._is_generating:
            self.generate_plan()
    
    def cleanup(self):
        """Clean up resources"""
        if self._is_destroyed:
            return
        
        self._is_destroyed = True
        
        try:
            # Disconnect signals safely
            if hasattr(self, 'tree') and self.tree:
                self.tree.blockSignals(True)
                try:
                    self.tree.markAsortedRequested.disconnect()
                    self.tree.itemDoubleClicked.disconnect()
                    self.tree.itemClicked.disconnect()
                except:
                    pass
            
            # Clean up matplotlib canvas
            if self.canvas:
                try:
                    self.canvas.deleteLater()
                except:
                    pass
                self.canvas = None
            
            self.ax = None
        
        except Exception as e:
            print(f"Error in SetSorterView cleanup: {e}")
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        chart_group = QGroupBox(f"Optimal Sort Plan for {self.set_name}")
        chart_layout = QVBoxLayout(chart_group)
        
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.figure import Figure
            import matplotlib
            matplotlib.use('QtAgg')
            
            self.canvas = FigureCanvas(Figure(facecolor='#2b2b2b'))
            self.ax = self.canvas.figure.subplots()
            self.ax.tick_params(colors='white')
            for spine in self.ax.spines.values():
                spine.set_color('white')
            chart_layout.addWidget(self.canvas)
        
        except Exception as e:
            error_label = QLabel(f"Chart unavailable: {str(e)}")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet("color: orange; padding: 20px;")
            chart_layout.addWidget(error_label)
            self.canvas = None
            self.ax = None
        
        splitter.addWidget(chart_group)
        
        # Right panel setup
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        piles_group = QGroupBox("Sorting Piles")
        piles_layout = QVBoxLayout(piles_group)
        self.tree = NavigableTreeWidget()
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setHeaderLabels(["Pile", "Count"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setSortingEnabled(True)
        piles_layout.addWidget(self.tree)
        right_layout.addWidget(piles_group)
        
        controls_layout = QHBoxLayout()
        mark_pile_button = QPushButton("Mark Selected as Sorted")
        controls_layout.addWidget(mark_pile_button)
        right_layout.addLayout(controls_layout)
        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])
        
        # FIXED: Signal connections with checkbox system
        try:
            self.tree.markAsortedRequested.connect(self.on_mark_piles_sorted)
            mark_pile_button.clicked.connect(lambda: self.on_mark_piles_sorted(self.tree.selectedItems()))
            
            # Connect checkbox signal for sorted state toggle
            self.tree.itemSortedToggled.connect(self.on_item_sorted_toggled)
            
            # Direct signal connection for proper drill-down - no timer
            def debug_item_clicked(item, column):
                print(f"SUCCESS: SetSorterView itemClicked signal received for item: '{item.text(0) if item else 'None'}', column: {column}")
                self.on_item_clicked(item, column)
            
            def debug_item_double_clicked(item, column):
                print(f"SUCCESS: SetSorterView itemDoubleClicked signal received for item: '{item.text(0) if item else 'None'}', column: {column}")
                # Double-click still drills down for better UX
                print("DEBUG: Double-click drilling down")
                self.on_item_clicked(item, column)
            
            self.tree.itemClicked.connect(debug_item_clicked)
            self.tree.itemDoubleClicked.connect(debug_item_double_clicked)
            print("DEBUG: SetSorterView signals connected with checkbox system")
        except Exception as e:
            print(f"Warning: Failed to connect signals: {e}")
    
    def on_item_clicked(self, item: QTreeWidgetItem, column: int = 0):
        """FIXED: Handle item clicks with drill-down functionality."""
        if self._is_destroyed or not item or self._in_item_click:
            return
        
        # Set guard flag immediately
        self._in_item_click = True
        try:
            print(f"DEBUG: SetSorterView on_item_clicked called for item '{item.text(0)}'")
            
            # First, determine the current level based on the item's position in the tree
            current_level = 0
            parent_item = item.parent()
            while parent_item:
                current_level += 1
                parent_item = parent_item.parent()
            
            print(f"DEBUG: Current level: {current_level}")
            
            # If this is a top-level item (level 0), do progressive loading for children
            if current_level == 0 and item.childCount() == 0:
                print("DEBUG: Top-level item without children, doing progressive loading")
                self._populate_item_children(item)
            
            # FIXED: Always call parent drill-down handler for navigation
            print("DEBUG: Calling parent drill-down handler")
            print(f"DEBUG: Current widget in results_stack: {type(self.parent_tab.results_stack.currentWidget())}")
            self.parent_tab.handle_item_click(item, current_level + 1)
        
        except Exception as e:
            print(f"Error in on_item_clicked: {e}")
        finally:
            self._in_item_click = False
    
    def _populate_item_children(self, item: QTreeWidgetItem):
        """Populate children for a tree item progressively."""
        try:
            pile_data = item.data(0, Qt.ItemDataRole.UserRole)
            if not pile_data or not hasattr(pile_data, 'cards'):
                return
            
            cards_in_pile = sorted(pile_data.cards, key=lambda c: c.name or "")
            show_sorted = self.parent_tab.show_sorted_check.isChecked()
            
            # Prepare nodes for progressive population
            nodes_to_add = []
            for card in cards_in_pile:
                unsorted_count = card.quantity - card.sorted_count
                if not show_sorted and unsorted_count <= 0:
                    continue
                
                display_count = card.quantity if show_sorted else unsorted_count
                # Create a SortGroup-like object that the populator understands
                node = SortGroup(group_name=card.name, count=display_count, cards=[card])
                node.unsorted_count = unsorted_count
                node.is_card_leaf = True  # For styling
                nodes_to_add.append(node)
            
            if not nodes_to_add:
                return
            
            # Provide user feedback and disable updates
            self.tree.setUpdatesEnabled(False)
            item.setText(1, f"{item.text(1)} (Loading...)")
            
            def on_population_finished():
                if self._is_destroyed:
                    return
                try:
                    # Restore original text from stored data and expand
                    pile_node_data = item.data(0, Qt.ItemDataRole.UserRole)
                    if pile_node_data:
                        show_sorted = self.parent_tab.show_sorted_check.isChecked()
                        original_count = pile_node_data.total_count if show_sorted else pile_node_data.unsorted_count
                        item.setText(1, str(int(original_count)))
                    item.setExpanded(True)
                finally:
                    if not self._is_destroyed: self.tree.setUpdatesEnabled(True)
            
            self.tree._populate_tree_progressively(nodes_to_add, parent_item=item, on_finished=on_population_finished)
        
        except Exception as e:
            print(f"Error setting up progressive item population: {e}")
            self._in_item_click = False  # Ensure flag is reset on error
    
    def on_mark_piles_sorted(self, items_to_mark=None):
        """FIXED: Simple pile marking with deferred refresh"""
        if self._is_destroyed:
            return
        
        try:
            selected_items = items_to_mark or self.tree.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "No Selection", "Please select one or more piles from the list.")
                return
            
            is_toggle_mode = len(selected_items) == 1
            
            for item in selected_items:
                if self._is_destroyed:
                    return
                
                pile_data = item.data(0, Qt.ItemDataRole.UserRole)
                if pile_data and hasattr(pile_data, 'cards'):
                    cards_in_pile = pile_data.cards
                else:
                    cards_in_pile = self.parent_tab._get_cards_from_item(item)
                
                if not cards_in_pile:
                    continue
                
                is_already_sorted = all(c.is_fully_sorted for c in cards_in_pile)
                
                for card in cards_in_pile:
                    if is_toggle_mode and is_already_sorted:
                        card.sorted_count = 0
                    else:
                        card.sorted_count = card.quantity
            
            if not self._is_destroyed:
                self.parent_tab.show_status_message(f"Updated sorted status for {len(selected_items)} pile(s).")
                self.parent_tab.project_modified.emit()
                
                # Check if all cards in this set are now sorted
                all_sorted = all(c.is_fully_sorted for c in self.cards_to_sort)
                if all_sorted:
                    # All cards in this set are sorted, provide completion message and navigate back
                    QTimer.singleShot(200, lambda: self._handle_set_completion())
                else:
                    # Use timer to defer refresh and prevent recursion
                    QTimer.singleShot(100, self._safe_regenerate_plan)
        
        except Exception as e:
            print(f"Error in on_mark_piles_sorted: {e}")
    
    def on_item_sorted_toggled(self, item: QTreeWidgetItem, is_sorted: bool):
        """Handle checkbox toggle for sorted state in SetSorterView"""
        if self._is_destroyed or not item:
            return
        
        try:
            # Get cards from the item
            pile_data = item.data(0, Qt.ItemDataRole.UserRole)
            if pile_data and hasattr(pile_data, 'cards'):
                cards_in_pile = pile_data.cards
            else:
                cards_in_pile = self.parent_tab._get_cards_from_item(item)
            
            if not cards_in_pile:
                return
            
            # Update card sorted status
            for card in cards_in_pile:
                if is_sorted:
                    card.sorted_count = card.quantity
                else:
                    card.sorted_count = 0
            
            # Update visual state of the item
            self.tree.set_item_sorted_state(item, is_sorted)
            
            # Hide/show item based on sorted state and user preference
            show_sorted = self.parent_tab.show_sorted_check.isChecked()
            if is_sorted and not show_sorted:
                item.setHidden(True)
            else:
                item.setHidden(False)
            
            # Show status message
            action = "SORTED" if is_sorted else "UNSORTED"
            self.parent_tab.show_status_message(f"✓ Marked pile '{item.text(0)}' as {action}.")
            
            # Emit project modified signal
            self.parent_tab.project_modified.emit()
            
            # Refresh the chart to show updated progress
            self._refresh_chart()
            
            # Check if all cards in this set are now sorted for completion
            if is_sorted:
                all_sorted = all(c.is_fully_sorted for c in self.cards_to_sort)
                if all_sorted:
                    QTimer.singleShot(200, lambda: self._handle_set_completion())
            
        except Exception as e:
            print(f"Error in on_item_sorted_toggled: {e}")
    
    def _safe_regenerate_plan(self):
        """Safe plan regeneration with guard"""
        if not self._is_destroyed and not self._is_generating:
            self.generate_plan()
    
    def _handle_set_completion(self):
        """Handle completion of all cards in the set"""
        if self._is_destroyed:
            return
        
        try:
            # Show completion message
            QMessageBox.information(
                self, 
                "Set Complete!", 
                f"Congratulations! All cards in '{self.set_name}' have been sorted.\n\n"
                f"You can now proceed to the next set or return to the main view."
            )
            
            # Navigate back to the previous level
            self.parent_tab.show_status_message(f"✓ Set '{self.set_name}' completed! Returning to previous level.", 4000)
            
            # Check if there are more levels to navigate back
            current_index = self.parent_tab.results_stack.currentIndex()
            if current_index > 0:
                # Navigate back one level
                self.parent_tab.navigate_to_level(current_index - 1)
                self.parent_tab.update_button_visibility()
            
        except Exception as e:
            print(f"Error in _handle_set_completion: {e}")
    
    def _get_expanded_items(self):
        """Helper to get expanded items safely"""
        expanded = set()
        try:
            iterator = QTreeWidgetItemIterator(self.tree)
            while iterator.value():
                item = iterator.value()
                if item.isExpanded():
                    expanded.add(item.text(0))
                iterator += 1
        except:
            pass
        return expanded
    
    def generate_plan(self):
        """FIXED: Generate sorting plan with progressive population to prevent crashes."""
        if self._is_destroyed or self._is_generating:
            return
        
        self._is_generating = True
        try:
            
            # Save state for restoration
            expanded_items = self._get_expanded_items()
            selected_items = {item.text(0) for item in self.tree.selectedItems()}
            current_item_text = self.tree.currentItem().text(0) if self.tree.currentItem() else None
            
            # Generate piles data
            show_sorted = self.parent_tab.show_sorted_check.isChecked()
            piles = collections.defaultdict(lambda: {'cards': [], 'total': 0, 'unsorted': 0})
            
            # Process grouping logic
            if self.parent_tab.optimal_grouping_check.isChecked():
                # Optimal grouping algorithm with max 3 letters per group
                try:
                    threshold = int(self.parent_tab.group_threshold_edit.text())
                except ValueError:
                    threshold = 20
                
                mapping = self._create_optimal_letter_grouping(threshold)
                
                # Apply mapping to cards
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        first_letter = name[0].upper()
                        pile_key = mapping.get(first_letter, first_letter)
                        piles[pile_key]['cards'].append(card)
                        piles[pile_key]['total'] += card.quantity
                        piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)
                        
            elif self.parent_tab.group_low_count_check.isChecked():
                try:
                    threshold = int(self.parent_tab.group_threshold_edit.text())
                except ValueError:
                    threshold = 20
                
                # Create letter mapping for grouping
                raw_letter_totals = collections.defaultdict(int)
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        raw_letter_totals[name[0].upper()] += card.quantity
                
                mapping = {}
                buf, tot = "", 0
                
                def flush():
                    nonlocal buf, tot
                    if buf:
                        for ch in buf:
                            mapping[ch] = buf
                        buf, tot = "", 0
                
                letters = string.ascii_uppercase
                for i, l in enumerate(letters):
                    count = raw_letter_totals.get(l, 0)
                    if 0 < count < threshold:
                        buf += l
                        tot += count
                        if tot >= threshold or not (i < 25 and raw_letter_totals.get(letters[i + 1], 0) < threshold):
                            flush()
                    else:
                        flush()
                        mapping[l] = l
                flush()
                
                # Apply mapping to cards
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        first_letter = name[0].upper()
                        pile_key = mapping.get(first_letter, first_letter)
                        piles[pile_key]['cards'].append(card)
                        piles[pile_key]['total'] += card.quantity
                        piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)
            else:
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        pile_key = name[0].upper()
                        piles[pile_key]['cards'].append(card)
                        piles[pile_key]['total'] += card.quantity
                        piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)
            
            # Create display nodes
            nodes = []
            for name, pile_data in piles.items():
                node = SortGroup(group_name=name, count=pile_data['unsorted'], cards=pile_data['cards'])
                node.total_count = pile_data['total']
                node.unsorted_count = pile_data['unsorted']
                nodes.append(node)
            
            if show_sorted:
                display_nodes = sorted(nodes, key=lambda x: x.total_count, reverse=True)
                chart_title = f"Card Distribution in {self.set_name} (Total Cards)"
                tree_header = "Total Count"
            else:
                display_nodes = sorted([n for n in nodes if n.unsorted_count > 0], key=lambda x: x.unsorted_count,
                                       reverse=True)
                chart_title = f"Unsorted Cards in {self.set_name}"
                tree_header = "Unsorted Count"
            
            # Clear and prepare tree
            self.tree.setUpdatesEnabled(False)
            self.tree.clear()
            self.tree.setHeaderLabels(["Pile", tree_header])
            
            def on_population_finished():
                if self._is_destroyed:
                    self._is_generating = False
                    return
                try:
                    # Restore state
                    self.tree.blockSignals(True)
                    try:
                        iterator = QTreeWidgetItemIterator(self.tree)
                        while iterator.value():
                            item = iterator.value()
                            if item.text(0) in expanded_items:
                                item.setExpanded(True)
                            if item.text(0) in selected_items:
                                item.setSelected(True)
                            if item.text(0) == current_item_text:
                                self.tree.setCurrentItem(item)
                            iterator += 1
                    finally:
                        self.tree.blockSignals(False)
                    
                    # Sort tree and restore updates
                    self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
                    self.tree.setUpdatesEnabled(True)
                    
                    # Draw chart
                    self._draw_chart_safe(display_nodes, chart_title, show_sorted)
                
                except Exception as e:
                    print(f"Error in SetSorterView population callback: {e}")
                finally:
                    self._is_generating = False
            
            # Populate asynchronously
            self.tree._populate_tree_progressively(display_nodes, on_finished=on_population_finished)
        
        except Exception as e:
            print(f"Error in generate_plan setup: {e}")
            self._is_generating = False
    
    def _draw_chart_safe(self, display_nodes, chart_title, show_sorted):
        """Safe chart drawing"""
        if not self.ax or not self.canvas or self._is_destroyed:
            return
        
        try:
            self.ax.clear()
            
            if not display_nodes:
                self.ax.text(0.5, 0.5, "Set Complete! All cards sorted.",
                             ha='center', va='center', color='white', fontsize=16)
            else:
                chart_labels = [node.group_name for node in display_nodes]
                chart_counts = [node.total_count if show_sorted else node.unsorted_count for node in display_nodes]
                colors = ['#555555' if node.unsorted_count <= 0 else '#007acc' for node in
                          display_nodes] if show_sorted else '#007acc'
                
                bars = self.ax.bar(chart_labels, chart_counts, color=colors, zorder=3)
                
                for bar, count in zip(bars, chart_counts):
                    if (height := bar.get_height()) > 0:
                        self.ax.text(bar.get_x() + bar.get_width() / 2., height, f'{int(count)}',
                                     ha='center', va='bottom', color='white', fontsize=8)
                
                self.ax.set_title(chart_title, color='white')
                self.ax.set_ylabel("Card Count", color='white')
                self.ax.tick_params(axis='x', colors='white', rotation=45 if len(chart_labels) > 10 else 0)
                self.ax.tick_params(axis='y', colors='white')
                
                for spine in self.ax.spines.values():
                    spine.set_color('white')
                
                self.ax.grid(axis='y', color='#444444', linestyle='--', linewidth=0.5, zorder=0)
            
            self.canvas.figure.tight_layout()
            self.canvas.draw()
        
        except Exception as e:
            print(f"Error drawing chart: {e}")
    
    def _refresh_chart(self):
        """Refresh the chart to reflect current sorting state"""
        if self._is_destroyed or not self.cards_to_sort:
            return
        
        try:
            # Recalculate pile data based on current sorting state
            show_sorted = self.parent_tab.show_sorted_check.isChecked()
            piles = collections.defaultdict(lambda: {'cards': [], 'total': 0, 'unsorted': 0})
            
            # Rebuild pile data from current cards
            if self.parent_tab.optimal_grouping_check.isChecked():
                # Use optimal grouping mapping
                threshold = int(self.parent_tab.group_threshold_edit.text()) if self.parent_tab.group_threshold_edit.text() else 20
                mapping = self._create_optimal_letter_grouping(threshold)
                
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        first_letter = name[0].upper()
                        pile_key = mapping.get(first_letter, first_letter)
                        piles[pile_key]['cards'].append(card)
                        piles[pile_key]['total'] += card.quantity
                        piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)
                        
            elif self.parent_tab.group_low_count_check.isChecked():
                # Use standard grouping logic - recreate the mapping
                threshold = int(self.parent_tab.group_threshold_edit.text()) if self.parent_tab.group_threshold_edit.text() else 20
                
                raw_letter_totals = collections.defaultdict(int)
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        raw_letter_totals[name[0].upper()] += card.quantity
                
                mapping = {}
                buf, tot = "", 0
                
                def flush():
                    nonlocal buf, tot
                    if buf:
                        for ch in buf:
                            mapping[ch] = buf
                        buf, tot = "", 0
                
                letters = string.ascii_uppercase
                for i, l in enumerate(letters):
                    count = raw_letter_totals.get(l, 0)
                    if 0 < count < threshold:
                        buf += l
                        tot += count
                        if tot >= threshold or not (i < 25 and raw_letter_totals.get(letters[i + 1], 0) < threshold):
                            flush()
                    else:
                        flush()
                        mapping[l] = l
                flush()
                
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        first_letter = name[0].upper()
                        pile_key = mapping.get(first_letter, first_letter)
                        piles[pile_key]['cards'].append(card)
                        piles[pile_key]['total'] += card.quantity
                        piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)
            else:
                # No grouping
                for card in self.cards_to_sort:
                    name = getattr(card, 'name', '')
                    if name and name != 'N/A':
                        pile_key = name[0].upper()
                        piles[pile_key]['cards'].append(card)
                        piles[pile_key]['total'] += card.quantity
                        piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)
            
            # Create nodes from piles
            nodes = []
            for name, pile_data in piles.items():
                node = SortGroup(group_name=name, count=pile_data['unsorted'], cards=pile_data['cards'])
                node.total_count = pile_data['total']
                node.unsorted_count = pile_data['unsorted']
                nodes.append(node)
            
            # Sort and filter nodes
            if show_sorted:
                display_nodes = sorted(nodes, key=lambda x: x.total_count, reverse=True)
                chart_title = f"Card Distribution in {self.set_name} (Total Cards)"
            else:
                display_nodes = sorted([n for n in nodes if n.unsorted_count > 0], key=lambda x: x.unsorted_count, reverse=True)
                chart_title = f"Unsorted Cards in {self.set_name}"
            
            # Redraw the chart
            self._draw_chart_safe(display_nodes, chart_title, show_sorted)
            
        except Exception as e:
            print(f"Error refreshing chart: {e}")
    
    def _create_optimal_letter_grouping(self, threshold):
        """Create optimal letter grouping with max 3 letters per group"""
        import string
        
        # Calculate letter counts
        raw_letter_totals = collections.defaultdict(int)
        for card in self.cards_to_sort:
            name = getattr(card, 'name', '')
            if name and name != 'N/A':
                raw_letter_totals[name[0].upper()] += card.quantity
        
        # Convert to list of (letter, count) pairs and sort by count descending
        letter_counts = [(letter, raw_letter_totals.get(letter, 0)) for letter in string.ascii_uppercase]
        letter_counts.sort(key=lambda x: x[1], reverse=True)
        
        # Separate high and low count letters
        high_letters = [(l, c) for l, c in letter_counts if c >= threshold]
        low_letters = [(l, c) for l, c in letter_counts if 0 < c < threshold]
        
        mapping = {}
        
        # High count letters stay as individual piles
        for letter, count in high_letters:
            mapping[letter] = letter
        
        # Group low count letters optimally
        if low_letters:
            groups = self._optimal_bin_packing(low_letters, threshold)
            for group in groups:
                group_name = ''.join(sorted([letter for letter, _ in group]))
                for letter, _ in group:
                    mapping[letter] = group_name
        
        # Handle letters with 0 cards
        for letter in string.ascii_uppercase:
            if letter not in mapping:
                mapping[letter] = letter
        
        return mapping
    
    def _optimal_bin_packing(self, items, capacity):
        """Optimal bin packing algorithm with max 3 items per bin"""
        if not items:
            return []
        
        # Sort items by size descending for better packing
        items = sorted(items, key=lambda x: x[1], reverse=True)
        bins = []
        
        for item in items:
            letter, count = item
            
            # Find best bin to place this item (best fit decreasing)
            best_bin = None
            best_remaining_space = float('inf')
            
            for bin_items in bins:
                if len(bin_items) >= 3:  # Max 3 letters per group
                    continue
                    
                current_sum = sum(c for _, c in bin_items)
                if current_sum + count <= capacity:
                    remaining_space = capacity - (current_sum + count)
                    if remaining_space < best_remaining_space:
                        best_remaining_space = remaining_space
                        best_bin = bin_items
            
            if best_bin is not None:
                best_bin.append(item)
            else:
                # Create new bin
                bins.append([item])
        
        return bins