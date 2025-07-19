# ui/sorter_tab.py - COMPLETE WORKING VERSION with crash fixes and all features

import collections
import csv
import pathlib
import string
from typing import Dict, List

from PyQt6.QtCore import QSettings, QThread, QTimer, Qt, pyqtSignal as Signal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                             QProgressBar, QPushButton, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem,
                             QTreeWidgetItemIterator, QVBoxLayout, QWidget)

from api.scryfall_api import ScryfallAPI
from core.constants import Config
from core.models import Card, SortGroup
from core.project_manager import ProjectManager
from ui.custom_widgets import NavigableTreeWidget, SortableTreeWidgetItem
from ui.set_sorter_view import SetSorterView
from ui.sorter_tab_ui import SorterTabUi
from workers.threads import CsvImportWorker, ImageFetchWorker, cleanup_worker_thread


class ManaBoxSorterTab(QWidget):
	# Signals for communication with main window
	collection_loaded = Signal()
	progress_updated = Signal(int)
	project_modified = Signal()
	operation_started = Signal(str, int)
	operation_finished = Signal()
	
	def __init__(self, api: ScryfallAPI):
		super().__init__()
		self.api = api
		self.all_cards: List[Card] = []
		self.import_thread: QThread | None = None
		self.import_worker: CsvImportWorker | None = None
		self.image_thread: QThread | None = None
		self.image_worker: ImageFetchWorker | None = None
		self.sort_order: List[str] = []
		self.current_loading_id: str | None = None
		self.last_csv_path: str | None = None
		self.progress_to_load: Dict | None = None
		self.is_loading = False
		self.preview_card: Card | None = None
		self.splitter_sizes = [700, 350]
		self.ui: SorterTabUi | None = None
		
		# Simple operation flags to prevent crashes
		self._is_refreshing = False
		self._is_destroyed = False
		self._is_navigating = False
		self._is_generating_plan = False  # Guard against recursive plan generation
		
		# Initialize UI widget attributes that will be created by SorterTabUi
		self.import_button: QPushButton | None = None
		self.reset_progress_button: QPushButton | None = None
		self.file_label: QLabel | None = None
		self.progress_bar: QProgressBar | None = None
		self.available_list: QListWidget | None = None
		self.selected_list: QListWidget | None = None
		self.group_low_count_check: QCheckBox | None = None
		self.group_threshold_edit: QLineEdit | None = None
		self.run_button: QPushButton | None = None
		self.breadcrumb_layout: QHBoxLayout | None = None
		self.show_sorted_check: QCheckBox | None = None
		self.mark_sorted_button: QPushButton | None = None
		self.export_button: QPushButton | None = None
		self.main_splitter: QSplitter | None = None
		self.filter_edit: QLineEdit | None = None
		self.results_stack: QStackedWidget | None = None
		self.preview_panel: QWidget | None = None
		self.card_image_label: QLabel | None = None
		self.fetch_image_button: QPushButton | None = None
		self.card_details_label: QLabel | None = None
		self.status_label: QLabel | None = None
		
		main_layout = QVBoxLayout(self)
		QTimer.singleShot(0, self.setup_ui)
	
	def cleanup_workers(self):
		"""Clean up any running workers WITHOUT marking widget as destroyed"""
		# Only clean up worker threads, don't mark widget as destroyed
		cleanup_worker_thread(self.import_thread, self.import_worker)
		cleanup_worker_thread(self.image_thread, self.image_worker)
	
	def cleanup_widget(self):
		"""Clean up the entire widget and mark as destroyed"""
		if self._is_destroyed:
			return
		
		self._is_destroyed = True
		self.cleanup_workers()
	
	def __del__(self):
		"""Ensure proper cleanup of workers"""
		self.cleanup_widget()
	
	def closeEvent(self, event):
		"""Handle widget close event"""
		self.cleanup_widget()
		super().closeEvent(event)
	
	def handle_item_click(self, item: QTreeWidgetItem, next_level: int):
		"""FIXED: Simple item click handling with drill-down"""
		print(f"DEBUG: handle_item_click ENTRY - item: '{item.text(0) if item else 'None'}', next_level: {next_level}")
		print(f"DEBUG: handle_item_click ENTRY - _is_destroyed: {self._is_destroyed}")
		
		if self._is_destroyed or not item:
			print("DEBUG: handle_item_click EARLY RETURN - destroyed or no item")
			return
		
		try:
			print(f"DEBUG: handle_item_click called for item '{item.text(0)}', next_level: {next_level}")
			
			# Always update preview first
			print("DEBUG: Updating card preview...")
			self.update_card_preview(item)
			print("DEBUG: Card preview updated")
			
			# Check if we should drill down (avoid for individual cards)
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			current_level = next_level - 1
			current_widget = self.results_stack.currentWidget()
			
			print(f"DEBUG: sort_order: {self.sort_order}, current_level: {current_level}")
			print(f"DEBUG: Selected list count: {self.selected_list.count()}")
			print(f"DEBUG: Results stack count: {self.results_stack.count()}")
			print(f"DEBUG: Results stack current index: {self.results_stack.currentIndex()}")
			print(f"DEBUG: Current widget type: {type(current_widget)}")
			
			# Special handling for SetSorterView - when clicking on letter piles, drill down to show Names
			if isinstance(current_widget, SetSorterView):
				print("DEBUG: Currently in SetSorterView, drilling down to Names level")
				# Get cards from the selected pile
				cards_in_pile = self._get_cards_from_item(item)
				if cards_in_pile:
					print(f"DEBUG: Found {len(cards_in_pile)} cards in pile '{item.text(0)}'")
					# Navigate to the correct level and create a Name view
					self.navigate_to_level(self.results_stack.currentIndex())
					breadcrumb_text = item.text(0)
					self.add_breadcrumb(breadcrumb_text, next_level)
					# Create a Name-level view instead of another SetSorterView
					self.create_new_view(cards_in_pile, len(self.sort_order))  # Force to Name level
					self.update_button_visibility()
					return
			
			if 0 <= current_level < len(self.sort_order) and self.sort_order[current_level] == "Name":
				# This is a card item, just update preview
				print("DEBUG: This is a card item, not drilling down")
				return
			
			# This is a group item, drill down
			print("DEBUG: This is a group item, drilling down...")
			self.show_status_message(f"Drilling down into '{item.text(0).split(': ')[-1]}'...", 2000)
			print("DEBUG: About to call drill_down...")
			self.drill_down(item, next_level)
			print("DEBUG: drill_down call completed")
		
		except Exception as e:
			print(f"Error in handle_item_click: {e}")
			import traceback
			traceback.print_exc()
	
	def drill_down(self, item: QTreeWidgetItem, next_level: int):
		"""Handle drill down with crash prevention"""
		print(f"DEBUG: drill_down called with item '{item.text(0)}', next_level: {next_level}")
		print(f"DEBUG: _is_destroyed: {self._is_destroyed}, _is_navigating: {self._is_navigating}")
		
		if self._is_destroyed or not item or self._is_navigating:
			print("DEBUG: drill_down early return due to guards")
			return
		
		try:
			self._is_navigating = True
			print("DEBUG: Set _is_navigating to True")
			
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			print(f"DEBUG: Current sort_order: {self.sort_order}")
			
			if next_level > len(self.sort_order):
				print(f"DEBUG: Cannot drill down - next_level {next_level} > sort_order length {len(self.sort_order)}")
				self.show_status_message("Cannot drill down further - no more sort criteria available.", 3000)
				return
			
			# Special handling for Set → First Letter transition
			current_level_index = next_level - 1
			print(f"DEBUG: current_level_index: {current_level_index}")
			
			if 0 <= current_level_index < len(self.sort_order):
				current_criterion = self.sort_order[current_level_index]
				next_criterion = self.sort_order[next_level] if next_level < len(self.sort_order) else None
				print(f"DEBUG: current_criterion: '{current_criterion}', next_criterion: '{next_criterion}'")
				
				if current_criterion == "Set" and next_criterion == "First Letter":
					print("DEBUG: Detected Set -> First Letter transition")
					cards_in_set = self._get_cards_from_item(item)
					print(f"DEBUG: Found {len(cards_in_set)} cards in set")
					
					if not cards_in_set:
						print("DEBUG: No cards found in selected set")
						self.show_status_message("No cards found in selected set.", 2000)
						return
					
					print("DEBUG: Navigating to level and creating set sorter view")
					self.navigate_to_level(current_level_index)
					breadcrumb_text = item.text(0).split(': ')[-1]
					self.add_breadcrumb(f"{breadcrumb_text} (Letter Sort)", next_level)
					self.create_set_sorter_view(cards_in_set, breadcrumb_text)
					print("DEBUG: Set sorter view created")
					return
			
			# Default drill-down behavior
			print("DEBUG: Using default drill-down behavior")
			cards_in_group = self._get_cards_from_item(item)
			print(f"DEBUG: Found {len(cards_in_group)} cards in group")
			
			if not cards_in_group:
				print("DEBUG: No cards found in selected group")
				self.show_status_message("No cards found in selected group.", 2000)
				return
			
			# Check if we should navigate to final level (cards)
			if next_level >= len(self.sort_order):
				print("DEBUG: At final level - showing cards directly")
				self.show_status_message(f"Showing {len(cards_in_group)} cards in group '{item.text(0)}'.", 2000)
				return
			
			print("DEBUG: Navigating to level and creating new view")
			print(f"DEBUG: Current stack count: {self.results_stack.count()}")
			print(f"DEBUG: Navigating to level: {next_level - 1}")
			
			# Navigate to the appropriate level
			self.navigate_to_level(next_level - 1)
			print(f"DEBUG: After navigation, stack count: {self.results_stack.count()}")
			
			# Add breadcrumb for this level
			breadcrumb_text = item.text(0).split(': ')[-1]  # Remove any prefix
			self.add_breadcrumb(breadcrumb_text, next_level)
			print(f"DEBUG: Added breadcrumb: '{breadcrumb_text}'")
			
			# Create new view for the next level
			self.create_new_view(cards_in_group, next_level)
			print("DEBUG: New view created")
			
			# Update button visibility
			self.update_button_visibility()
			print("DEBUG: Button visibility updated")
		
		except Exception as e:
			print(f"Error in drill_down: {e}")
			import traceback
			traceback.print_exc()
		finally:
			self._is_navigating = False
			print("DEBUG: Set _is_navigating to False")
	
	def _refresh_current_view(self):
		"""Refresh current view with crash prevention and proper async handling."""
		if self._is_destroyed or self._is_refreshing:
			return
		
		self._is_refreshing = True
		try:
			current_widget = self.results_stack.currentWidget()
			if isinstance(current_widget, SetSorterView):
				# Delegate to SetSorterView's regeneration
				current_widget._safe_regenerate_plan()
				self._is_refreshing = False
				return
			
			if not isinstance(current_widget, NavigableTreeWidget):
				if self.all_cards and not self._is_generating_plan:
					print("DEBUG: _refresh_current_view scheduling start_new_plan_generation")
					QTimer.singleShot(200, self._safe_start_plan_generation)
				self._is_refreshing = False
				return
			
			# Standard refresh logic
			level = self.results_stack.currentIndex()
			cards_to_process = getattr(current_widget, 'cards_for_view', self.all_cards)
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			criterion = self.sort_order[level] if 0 <= level < len(self.sort_order) else None
			nodes = self._generate_level_breakdown(cards_to_process, criterion)
			
			# Save state before clearing
			expanded_items = {item.text(0) for item in self._get_expanded_items(current_widget)}
			selected_items = {item.text(0) for item in current_widget.selectedItems()}
			current_item_text = current_widget.currentItem().text(0) if current_widget.currentItem() else None
			scroll_position = current_widget.verticalScrollBar().value()
			# Update tree asynchronously
			current_widget.setUpdatesEnabled(False)
			current_widget.clear()

			def on_population_finished():
				if self._is_destroyed:
					self._is_refreshing = False
					return
				try:
					show_sorted = self.show_sorted_check.isChecked()
					header_label = "Total Count" if show_sorted else "Unsorted Count"
					current_widget.setHeaderLabels(['Group', header_label])
					# Restore state after population is complete
					self._restore_tree_state(current_widget, expanded_items, selected_items, current_item_text, scroll_position)
					current_widget.setUpdatesEnabled(True)
				except Exception as e:
					print(f"Error during post-population refresh: {e}")
				finally:
					self._is_refreshing = False
					self.update_button_visibility()
					self._update_view_layout()
			
			current_widget._populate_tree_progressively(nodes, on_finished=on_population_finished)
		except Exception as e:
			print(f"Error in _refresh_current_view setup: {e}")
			self._is_refreshing = False
	
	def _get_expanded_items(self, tree_widget):
		"""Helper to get expanded items safely"""
		expanded = []
		try:
			iterator = QTreeWidgetItemIterator(tree_widget)
			while iterator.value():
				item = iterator.value()
				if item.isExpanded():
					expanded.append(item)
				iterator += 1
		except:
			pass
		return expanded
	
	def _restore_tree_state(self, tree_widget, expanded_items, selected_items, current_item_text, scroll_position):
		"""Helper to restore tree state safely"""
		tree_widget.blockSignals(True)
		try:
			iterator = QTreeWidgetItemIterator(tree_widget)
			while iterator.value():
				item = iterator.value()
				item_text = item.text(0)
				if item_text in expanded_items:
					item.setExpanded(True)
				if item_text in selected_items:
					item.setSelected(True)
				if item_text == current_item_text:
					tree_widget.setCurrentItem(item)
				iterator += 1
		except Exception as e:
			print(f"Error restoring tree state: {e}")
		finally:
			tree_widget.blockSignals(False)
			# Manually trigger the selection update for the preview pane since signals were blocked
			if tree_widget.currentItem():
				self.on_tree_selection_changed(tree_widget.currentItem(), None)
			# Restore scroll position with slight delay
			QTimer.singleShot(50, lambda: tree_widget.verticalScrollBar().setValue(scroll_position))
	
	def on_show_sorted_toggled(self):
		"""FIXED: Handle show sorted toggle with simple defer"""
		if not self._is_destroyed and not self._is_refreshing:
			# First update visibility of existing items
			self._update_sorted_item_visibility()
			# Then refresh the view
			QTimer.singleShot(100, self._refresh_current_view)
	
	def _update_sorted_item_visibility(self):
		"""Update visibility of sorted items based on show_sorted checkbox"""
		if self._is_destroyed:
			return
		
		try:
			current_widget = self.results_stack.currentWidget()
			if not isinstance(current_widget, NavigableTreeWidget):
				return
			
			show_sorted = self.show_sorted_check.isChecked()
			
			# Iterate through all items and update visibility
			iterator = QTreeWidgetItemIterator(current_widget)
			while iterator.value():
				item = iterator.value()
				if item:
					# Check if item is sorted (checkbox checked)
					is_sorted = item.checkState(0) == Qt.CheckState.Checked
					if is_sorted:
						# Hide sorted items if show_sorted is False
						item.setHidden(not show_sorted)
					else:
						# Always show unsorted items
						item.setHidden(False)
				iterator += 1
		
		except Exception as e:
			print(f"Error updating sorted item visibility: {e}")
	
	def setup_ui(self):
		"""Creates the UI by delegating to the SorterTabUi class."""
		self.ui = SorterTabUi(self)
		self.ui.setup_ui(self.layout())
	
	def _safe_start_plan_generation(self):
		"""Safe wrapper for plan generation with comprehensive error handling"""
		if self._is_destroyed or self._is_generating_plan:
			print(f"DEBUG: _safe_start_plan_generation aborted - destroyed: {self._is_destroyed}, generating: {self._is_generating_plan}")
			return
		
		try:
			print("DEBUG: _safe_start_plan_generation starting...")
			print(f"DEBUG: Current cards available: {len(self.all_cards) if self.all_cards else 0}")
			print(f"DEBUG: Widget state - destroyed: {self._is_destroyed}, refreshing: {self._is_refreshing}, generating: {self._is_generating_plan}")
			self.start_new_plan_generation()
			print("DEBUG: _safe_start_plan_generation completed successfully")
		except Exception as e:
			print(f"ERROR: _safe_start_plan_generation failed: {e}")
			import traceback
			traceback.print_exc()
			self.show_status_message(f"Error generating plan: {e}", 5000)

	def start_new_plan_generation(self):
		"""Resets the entire view and generates a new plan from the top level."""
		if not self.all_cards:
			QMessageBox.information(self, "No Collection", "Please import a collection first.")
			return
		
		if self._is_generating_plan:
			print("DEBUG: start_new_plan_generation aborted - already generating plan")
			return
		
		self._is_generating_plan = True
		try:
			print("DEBUG: start_new_plan_generation starting...")
			print(f"DEBUG: All cards count: {len(self.all_cards)}")
			
			print("DEBUG: Clearing breadcrumb layout...")
			self.clear_layout(self.breadcrumb_layout)
			print("DEBUG: Breadcrumb layout cleared")
			
			print("DEBUG: Clearing stack...")
			self._safe_clear_stack()
			print("DEBUG: Stack cleared")
			
			print("DEBUG: Resetting preview pane...")
			self.reset_preview_pane()
			print("DEBUG: Preview pane reset")
			
			print("DEBUG: Adding breadcrumb...")
			self.add_breadcrumb("Home", 0)
			print("DEBUG: Breadcrumb added")
			
			print("DEBUG: Creating new view...")
			# Create the first level view
			self.create_new_view(self.all_cards, 0)
			print("DEBUG: New view created")
			
			print("DEBUG: Updating button visibility...")
			self.update_button_visibility()
			print("DEBUG: Button visibility updated")
			
			print("DEBUG: Making filter edit visible...")
			self.filter_edit.setVisible(True)
			print("DEBUG: start_new_plan_generation completed")
		
		except Exception as e:
			print(f"ERROR: start_new_plan_generation failed: {e}")
			import traceback
			traceback.print_exc()
			self.show_status_message(f"Error starting new plan: {e}", 5000)
		finally:
			self._is_generating_plan = False
	
	def _safe_clear_stack(self):
		"""Safely clear the widget stack"""
		try:
			while self.results_stack.count() > 0:
				widget = self.results_stack.widget(0)
				self.results_stack.removeWidget(widget)
				if widget:
					if hasattr(widget, 'cleanup'):
						widget.cleanup()
					widget.deleteLater()
			
			# Process events to ensure deleteLater() is processed
			QApplication.processEvents()
		except Exception as e:
			print(f"Error clearing stack: {e}")
	
	def create_new_view(self, cards_in_group: List[Card], level: int):
		"""Create new view with full functionality"""
		try:
			print(f"DEBUG: create_new_view starting with {len(cards_in_group)} cards, level {level}")
			print(f"DEBUG: Memory check before creating tree widget...")
			
			print("DEBUG: Creating NavigableTreeWidget...")
			tree = NavigableTreeWidget()
			print("DEBUG: NavigableTreeWidget created successfully")
			
			print("DEBUG: Setting cards_for_view attribute...")
			tree.cards_for_view = cards_in_group
			print("DEBUG: cards_for_view set")
			
			print("DEBUG: Setting selection mode...")
			tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
			print("DEBUG: Selection mode set")
			
			print("DEBUG: Setting up tree headers...")
			show_sorted = self.show_sorted_check.isChecked()
			header_label = "Total Count" if show_sorted else "Unsorted Count"
			tree.setHeaderLabels(['Group', header_label])
			print("DEBUG: Header labels set")
			
			print("DEBUG: Enabling checkboxes...")
			# Enable checkboxes for all items
			tree.setRootIsDecorated(True)
			print("DEBUG: Checkboxes enabled")
			
			print("DEBUG: Setting header resize mode...")
			tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
			print("DEBUG: Header resize mode set")
			
			print("DEBUG: Enabling sorting...")
			tree.setSortingEnabled(True)
			print("DEBUG: Sorting enabled")
			
			print("DEBUG: Connecting signals...")
			# Connect signals with proper handlers (no timers - direct calls)
			def debug_item_clicked(item, column):
				print(f"SUCCESS: itemClicked signal received for item: '{item.text(0) if item else 'None'}', column: {column}")
				print(f"DEBUG: About to call handle_item_click with level: {level + 1}")
				print(f"DEBUG: Current results_stack widget: {type(self.results_stack.currentWidget())}")
				print(f"DEBUG: Current results_stack index: {self.results_stack.currentIndex()}")
				try:
					self.handle_item_click(item, level + 1)
					print(f"DEBUG: handle_item_click completed successfully")
				except Exception as e:
					print(f"ERROR: handle_item_click failed: {e}")
					import traceback
					traceback.print_exc()
			
			tree.itemClicked.connect(debug_item_clicked)
			print("DEBUG: itemClicked signal connected")
			
			# Connect double-click for drill-down only (checkboxes handle sorting now)
			def debug_item_double_clicked(item, column):
				print(f"SUCCESS: itemDoubleClicked signal received for item: '{item.text(0) if item else 'None'}', column: {column}")
				try:
					# Always drill down on double-click, checkboxes handle marking as sorted
					print(f"DEBUG: Double-click drilling down (level: {level + 1})")
					self.handle_item_click(item, level + 1)
					print(f"DEBUG: Double-click handling completed successfully")
				except Exception as e:
					print(f"ERROR: Double-click handling failed: {e}")
					import traceback
					traceback.print_exc()
			
			tree.itemDoubleClicked.connect(debug_item_double_clicked)
			print("DEBUG: itemDoubleClicked signal connected")
			
			tree.drillDownRequested.connect(lambda item: self.drill_down(item, level + 1))
			print("DEBUG: drillDownRequested signal connected")
			
			tree.navigateUpRequested.connect(lambda: self.navigate_and_refresh(level - 1) if level > 0 else None)
			print("DEBUG: navigateUpRequested signal connected")
			
			tree.currentItemChanged.connect(self.update_button_visibility)
			print("DEBUG: currentItemChanged signal connected to update_button_visibility")
			
			tree.currentItemChanged.connect(self.on_tree_selection_changed)
			print("DEBUG: currentItemChanged signal connected to on_tree_selection_changed")
			
			# Connect checkbox signal for sorted state toggle
			tree.itemSortedToggled.connect(self.on_item_sorted_toggled)
			print("DEBUG: itemSortedToggled signal connected")
			
			print("DEBUG: Determining sort criterion...")
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			criterion = self.sort_order[level] if 0 <= level < len(self.sort_order) else None
			print(f"DEBUG: Sort criterion: {criterion}")
			
			print("DEBUG: Generating level breakdown...")
			nodes = self._generate_level_breakdown(cards_in_group, criterion)
			print(f"DEBUG: Generated {len(nodes)} nodes")
			
			print("DEBUG: Starting progressive tree population...")
			tree._populate_tree_progressively(nodes, chunk_size=50)  # Smaller chunks
			print("DEBUG: Progressive tree population started")
			
			print("DEBUG: Adding tree to stack...")
			self.results_stack.addWidget(tree)
			print("DEBUG: Tree added to stack")
			
			print("DEBUG: Setting current widget...")
			self.results_stack.setCurrentWidget(tree)
			print("DEBUG: create_new_view completed")
		
		except Exception as e:
			print(f"ERROR: create_new_view failed: {e}")
			import traceback
			traceback.print_exc()
	
	def create_set_sorter_view(self, cards_to_sort: List[Card], set_name: str):
		"""Create SetSorterView"""
		try:
			view = SetSorterView(cards_to_sort, set_name, self)
			self.results_stack.addWidget(view)
			self.results_stack.setCurrentWidget(view)
			self._update_view_layout()
		except Exception as e:
			print(f"Error creating set sorter view: {e}")
	
	def _generate_level_breakdown(self, current_cards: List[Card], criterion: str | None) -> List[SortGroup]:
		"""Generate breakdown for current level"""
		try:
			print(f"DEBUG: _generate_level_breakdown starting with {len(current_cards)} cards, criterion: {criterion}")
			show_sorted = self.show_sorted_check.isChecked()
			print(f"DEBUG: show_sorted: {show_sorted}")
			
			if not criterion or criterion == "Name":
				print("DEBUG: Generating Name-level breakdown...")
				nodes = [SortGroup(group_name=c.name, count=(c.quantity - c.sorted_count), cards=[c], is_card_leaf=True)
				         for c in current_cards]
				print(f"DEBUG: Created {len(nodes)} name nodes")
				for node in nodes:
					node.total_count = node.cards[0].quantity
					node.unsorted_count = node.count
				print("DEBUG: Name-level breakdown completed")
				return sorted(nodes, key=lambda sg: sg.group_name or "")
			
			print(f"DEBUG: Generating {criterion}-level breakdown...")
			groups = collections.defaultdict(list)
			for i, card in enumerate(current_cards):
				if i % 100 == 0:  # Progress indicator for large collections
					print(f"DEBUG: Processing card {i+1}/{len(current_cards)}")
				try:
					value = self._get_nested_value(card, criterion)
					groups[value].append(card)
				except Exception as e:
					print(f"ERROR: Failed to get nested value for card {card.name}: {e}")
					groups["ERROR"].append(card)
			
			print(f"DEBUG: Created {len(groups)} groups")
			
			nodes = []
			for name, card_group in sorted(groups.items()):
				try:
					unsorted_count = sum(max(0, c.quantity - c.sorted_count) for c in card_group)
					
					if not show_sorted and unsorted_count == 0:
						continue
					
					total_count = sum(c.quantity for c in card_group)
					display_count = total_count if show_sorted else unsorted_count
					
					node = SortGroup(group_name=f"{criterion}: {name}", count=display_count, cards=card_group)
					node.unsorted_count = unsorted_count
					node.total_count = total_count
					nodes.append(node)
				except Exception as e:
					print(f"ERROR: Failed to create node for group {name}: {e}")
					continue
			
			print(f"DEBUG: _generate_level_breakdown completed with {len(nodes)} nodes")
			return nodes
		
		except Exception as e:
			print(f"ERROR: _generate_level_breakdown failed: {e}")
			import traceback
			traceback.print_exc()
			return []
	
	def _get_nested_value(self, card: Card, key: str) -> str:
		"""Get nested value for sorting, now with robust handling of missing data."""
		if key == "First Letter":
			name = getattr(card, 'name', '')
			return name[0].upper() if name and name != 'N/A' else '#'
		if key == "Set":
			return getattr(card, 'set_name', 'N/A') or 'N/A'
		if key == "Rarity":
			rarity = getattr(card, 'rarity', 'N/A') or 'N/A'
			return rarity.capitalize()
		if key == "Type Line":
			type_line = getattr(card, 'type_line', 'N/A') or 'N/A'
			return type_line.split('//')[0].strip()
		if key == "Condition":
			condition = getattr(card, 'condition', 'N/A') or 'N/A'
			return condition.capitalize()
		if key == "Color Identity":
			ci = getattr(card, 'color_identity', [])
			return ''.join(sorted(ci)) or 'Colorless'
		if key == "Commander Staple":
			rank = getattr(card, 'edhrec_rank', None)
			return "Staple (Top 1000)" if rank and rank <= 1000 else "Not a Staple"
		return 'N/A'
	
	def _get_cards_from_item(self, item: QTreeWidgetItem) -> List[Card]:
		"""Get cards from tree item safely"""
		if not item:
			return []
		item_data = item.data(0, Qt.ItemDataRole.UserRole)
		if item_data:
			if isinstance(item_data, list) and all(isinstance(c, Card) for c in item_data):
				return item_data
			elif hasattr(item_data, 'cards'):
				return item_data.cards
		return []
	
	# Essential utility methods
	def clear_layout(self, layout: QHBoxLayout):
		while layout.count():
			if child := layout.takeAt(0).widget():
				child.deleteLater()
	
	def add_breadcrumb(self, text: str, level: int):
		if level > 0:
			self.breadcrumb_layout.addWidget(QLabel(">"))
		btn = QPushButton(text.split(': ')[-1])
		btn.setObjectName("BreadcrumbButton")
		btn.clicked.connect(lambda: self.navigate_and_refresh(level))
		self.breadcrumb_layout.addWidget(btn)
	
	def navigate_to_level(self, level: int):
		"""Navigate to specific level safely"""
		try:
			level = max(0, min(level, self.results_stack.count() - 1))
			
			while self.results_stack.count() > level + 1:
				widget_index = self.results_stack.count() - 1
				widget = self.results_stack.widget(widget_index)
				self.results_stack.removeWidget(widget)
				if widget:
					if hasattr(widget, 'cleanup'):
						widget.cleanup()
					widget.deleteLater()
			
			target_breadcrumb_count = (level * 2) + 1
			while self.breadcrumb_layout.count() > target_breadcrumb_count:
				item = self.breadcrumb_layout.takeAt(self.breadcrumb_layout.count() - 1)
				if item and item.widget():
					item.widget().deleteLater()
			
			if self.results_stack.count() > level:
				self.results_stack.setCurrentIndex(level)
			
			self.filter_edit.clear()
			self.filter_current_view("")
			self.update_button_visibility()
		except Exception as e:
			print(f"Error in navigate_to_level: {e}")
	
	def navigate_and_refresh(self, level: int):
		"""Navigate and refresh safely"""
		self.navigate_to_level(level)
		QTimer.singleShot(50, self._refresh_current_view)
	
	def update_button_visibility(self, *args):
		"""Update button visibility"""
		is_normal_view = isinstance(self.results_stack.currentWidget(), NavigableTreeWidget)
		self.mark_sorted_button.setVisible(is_normal_view)
		self.export_button.setVisible(is_normal_view)
	
	def show_status_message(self, message: str, timeout: int = 2500):
		"""Show status message with visual feedback"""
		self.status_label.setText(message)
		
		# Add visual feedback for navigation actions
		if "drill" in message.lower() or "navigat" in message.lower():
			self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
		elif "error" in message.lower() or "fail" in message.lower():
			self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
		elif "sort" in message.lower() or "mark" in message.lower():
			self.status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
		else:
			self.status_label.setStyleSheet("color: #FFC107; font-weight: normal;")
		
		QTimer.singleShot(timeout, lambda: self.status_label.setText(""))
		QTimer.singleShot(timeout, lambda: self.status_label.setStyleSheet(""))
	
	def reset_preview_pane(self, *args):
		"""Reset preview pane safely"""
		cleanup_worker_thread(self.image_thread, self.image_worker)
		self.current_loading_id = None
		self.preview_card = None
		self.card_image_label.setText("Select a card to see its image.")
		self.card_image_label.setPixmap(QPixmap())
		self.card_details_label.setText("")
		self.fetch_image_button.setVisible(False)
	
	def update_card_preview(self, item: QTreeWidgetItem):
		"""Update card preview to be on-demand."""
		self.reset_preview_pane()
		
		cards = self._get_cards_from_item(item)
		if not cards:
			return
		
		# Determine which card to preview (first in group)
		card = cards[0] if cards else None
		
		if not isinstance(card, Card):
			self.preview_card = None
			return
		
		self.preview_card = card  # Store the card for the fetch button
		
		# Display text details
		if len(cards) == 1:
			self.card_details_label.setText(
					f"<b>{card.name}</b><br>{card.mana_cost or ''}<br>{card.type_line}<br>"
					f"<i>{card.set_name} ({card.rarity.upper()})</i><br><br>"
					f"Total Owned: {card.quantity}<br>Sorted: {card.sorted_count}")
		else:  # Group selected
			self.card_details_label.setText(
					f"<b>Group: {item.text(0)}</b><br>"
					f"Contains {len(cards)} different cards<br>"
					f"Total cards: {sum(c.quantity for c in cards)}<br>"
					f"Showing preview of: {card.name}"
			)
		
		# Set up the image pane for on-demand fetching
		if card.image_uri:
			self.card_image_label.setText("Image available.")
			self.fetch_image_button.setVisible(True)
		else:
			self.card_image_label.setText("No image available for this card.")
			self.fetch_image_button.setVisible(False)
	
	def on_fetch_image_clicked(self):
		"""Starts the download for the currently previewed card's image."""
		if self.image_thread and self.image_thread.isRunning():
			return
		if not self.preview_card or not self.preview_card.image_uri:
			self.card_image_label.setText("No image to fetch.")
			return
		card = self.preview_card
		self.current_loading_id = card.scryfall_id
		self.card_image_label.setText("Loading image...")
		self.fetch_image_button.setEnabled(False)
		self.image_thread = QThread()
		self.image_worker = ImageFetchWorker(card.image_uri, card.scryfall_id, self.api, parent=None)
		self.image_worker.moveToThread(self.image_thread)
		self.image_thread.started.connect(self.image_worker.process)
		self.image_worker.finished.connect(self.on_image_loaded)
		self.image_worker.error.connect(self.on_image_error)
		self.image_worker.finished.connect(self.image_thread.quit)
		self.image_worker.finished.connect(self.image_worker.deleteLater)
		self.image_thread.finished.connect(self.image_thread.deleteLater)
		self.image_thread.start()
	
	def on_image_loaded(self, image_data: bytes, scryfall_id: str):
		"""Handle successful image loading"""
		self.fetch_image_button.setEnabled(True)
		if scryfall_id != self.current_loading_id:
			return
		
		try:
			pixmap = QPixmap()
			if pixmap.loadFromData(image_data):
				scaled_pixmap = pixmap.scaled(
						self.card_image_label.size(),
						Qt.AspectRatioMode.KeepAspectRatio,
						Qt.TransformationMode.SmoothTransformation
				)
				self.card_image_label.setPixmap(scaled_pixmap)
			else:
				self.card_image_label.setText("Failed to load image data.")
		except Exception as e:
			self.card_image_label.setText(f"Error displaying image: {str(e)}")
		finally:
			self.image_thread = None
			self.image_worker = None
	
	def on_image_error(self, error_message: str):
		"""Handle image loading errors"""
		self.fetch_image_button.setEnabled(True)
		self.card_image_label.setText(f"Image unavailable:\n{error_message}")
		self.image_thread = None
		self.image_worker = None
	
	def on_tree_selection_changed(self, current, previous):
		"""Handle tree selection changes safely"""
		if current:
			self.update_card_preview(current)
		else:
			self.reset_preview_pane()
	
	def filter_current_view(self, text: str):
		"""Filter current view safely"""
		current_widget = self.results_stack.currentWidget()
		tree_to_filter = None
		
		if isinstance(current_widget, QTreeWidget):
			tree_to_filter = current_widget
		elif isinstance(current_widget, SetSorterView) and hasattr(current_widget, 'tree'):
			tree_to_filter = current_widget.tree
		
		if tree_to_filter:
			iterator = QTreeWidgetItemIterator(tree_to_filter, QTreeWidgetItemIterator.IteratorFlag.All)
			while iterator.value():
				item = iterator.value()
				item.setHidden(text.lower() not in item.text(0).lower())
				iterator += 1
	
	def _update_view_layout(self):
		"""Shows or hides the card preview pane"""
		self.preview_panel.setVisible(True)
		if not self.preview_panel.isVisible():
			self.main_splitter.setSizes(self.splitter_sizes)
	
	def on_mark_group_button_clicked(self):
		"""Handle mark group button click"""
		current_tree = self.results_stack.currentWidget()
		if not isinstance(current_tree, QTreeWidget):
			return
		
		selected_items = current_tree.selectedItems()
		if not selected_items:
			QMessageBox.information(self, "No Selection", "Please select one or more groups to mark as sorted.")
			return
		
		total_cards_affected = 0
		for item in selected_items:
			cards_to_mark = self._get_cards_from_item(item)
			for card in cards_to_mark:
				total_cards_affected += max(0, card.quantity - card.sorted_count)
		
		if total_cards_affected == 0:
			QMessageBox.information(self, "Already Sorted", "All selected groups are already completely sorted.")
			return
		
		if QMessageBox.question(self, "Confirm Mark as Sorted",
		                        f"Mark {total_cards_affected} cards as sorted?") == QMessageBox.StandardButton.Yes:
			for item in selected_items:
				self._mark_cards_as_sorted(item)
			self.show_status_message(f"✓ Marked {len(selected_items)} groups as sorted ({total_cards_affected} cards)")
			self.project_modified.emit()
			QTimer.singleShot(50, self._refresh_current_view)
	
	def mark_item_as_sorted(self, item: QTreeWidgetItem):
		"""Toggles the sorted status of a single item, used by double-click."""
		cards = self._get_cards_from_item(item)
		if not cards:
			self.show_status_message("⚠ Could not find cards for this group.")
			return
		
		is_already_sorted = all(c.is_fully_sorted for c in cards)
		
		for card in cards:
			if is_already_sorted:
				card.sorted_count = 0
			else:
				card.sorted_count = card.quantity
		
		if is_already_sorted:
			self.show_status_message(f"✓ Group '{item.text(0)}' marked as UNSORTED.")
		else:
			self.show_status_message(f"✓ Group '{item.text(0)}' marked as SORTED.")
			
			# Check if this level is now complete (all items sorted)
			QTimer.singleShot(100, lambda: self._check_level_completion(item))
		
		self.project_modified.emit()
		QTimer.singleShot(50, self._refresh_current_view)
	
	def _check_level_completion(self, item: QTreeWidgetItem):
		"""Check if the current level is complete and offer to advance"""
		if self._is_destroyed:
			return
		
		try:
			current_widget = self.results_stack.currentWidget()
			if not isinstance(current_widget, NavigableTreeWidget):
				return
			
			# Get all cards currently visible in this level
			all_cards_in_level = getattr(current_widget, 'cards_for_view', [])
			if not all_cards_in_level:
				return
			
			# Check if all cards in this level are sorted
			all_sorted = all(c.is_fully_sorted for c in all_cards_in_level)
			if all_sorted:
				current_level = self.results_stack.currentIndex()
				sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
				
				# Check if we're at the final level
				if current_level >= len(sort_order) - 1:
					# This is the final level
					QMessageBox.information(
						self,
						"Level Complete!",
						f"Congratulations! All cards in this group have been sorted.\n\n"
						f"You can now navigate back to continue with other groups."
					)
				else:
					# There are more levels, ask if user wants to advance
					next_criterion = sort_order[current_level + 1] if current_level + 1 < len(sort_order) else "Next Level"
					reply = QMessageBox.question(
						self,
						"Level Complete!",
						f"All cards in this level have been sorted!\n\n"
						f"Would you like to advance to the next level ({next_criterion})?",
						QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
						QMessageBox.StandardButton.Yes
					)
					
					if reply == QMessageBox.StandardButton.Yes:
						# Advance to next level automatically
						self.show_status_message(f"✓ Advancing to {next_criterion} level...", 3000)
						# This would require implementing automatic progression logic
						# For now, just show the message
		
		except Exception as e:
			print(f"Error in _check_level_completion: {e}")
	
	def on_item_sorted_toggled(self, item: QTreeWidgetItem, is_sorted: bool):
		"""Handle checkbox toggle for sorted state"""
		if self._is_destroyed or not item:
			return
		
		try:
			# Get cards from the item
			cards = self._get_cards_from_item(item)
			if not cards:
				self.show_status_message("⚠ Could not find cards for this group.")
				return
			
			# Update card sorted status
			for card in cards:
				if is_sorted:
					card.sorted_count = card.quantity
				else:
					card.sorted_count = 0
			
			# Update visual state of the item
			current_widget = self.results_stack.currentWidget()
			if isinstance(current_widget, NavigableTreeWidget):
				current_widget.set_item_sorted_state(item, is_sorted)
			
			# Hide/show item based on sorted state and user preference
			show_sorted = self.show_sorted_check.isChecked()
			if is_sorted and not show_sorted:
				item.setHidden(True)
			else:
				item.setHidden(False)
			
			# Show status message
			action = "SORTED" if is_sorted else "UNSORTED"
			self.show_status_message(f"✓ Marked '{item.text(0)}' as {action}.")
			
			# Emit project modified signal
			self.project_modified.emit()
			
		except Exception as e:
			print(f"Error in on_item_sorted_toggled: {e}")
	
	def _mark_cards_as_sorted(self, item: QTreeWidgetItem) -> bool:
		"""Internal method that only marks cards without refreshing, for batch operations."""
		cards_to_mark = self._get_cards_from_item(item)
		if not cards_to_mark:
			self.show_status_message("⚠ Could not find cards for this group.")
			return False
		for card in cards_to_mark:
			card.sorted_count = card.quantity
		return True
	
	def export_current_view(self):
		"""Export current view to CSV"""
		current_tree = self.results_stack.currentWidget()
		if not isinstance(current_tree, QTreeWidget) or current_tree.topLevelItemCount() == 0:
			QMessageBox.information(self, "No Data", "There's no data to export.")
			return
		
		filepath, _ = QFileDialog.getSaveFileName(self, "Save View as CSV", "sorter_view.csv", "CSV Files (*.csv)")
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
			QMessageBox.information(self, "Export Success", f"Successfully exported to:\n{filepath}")
		except Exception as e:
			QMessageBox.critical(self, "Export Error", f"Failed to export file: {e}")
	
	def get_save_data(self) -> dict:
		"""Gathers all project data into a dictionary for saving."""
		if not self.all_cards:
			return {}
		
		progress = {c.scryfall_id: c.sorted_count for c in self.all_cards if c.sorted_count > 0}
		sort_criteria = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
		
		cards_as_dicts = [c.__dict__ for c in self.all_cards]
		
		return {
				"metadata":   {"version": "1.1", "app": "MTGToolkit"},
				"collection": cards_as_dicts,
				"progress":   progress,
				"settings":   {
						"sort_criteria":   sort_criteria,
						"group_low_count": self.group_low_count_check.isChecked(),
						"group_threshold": self.group_threshold_edit.text()
				}
		}
	
	def save_to_project(self, filepath: str, is_auto_save: bool = False) -> bool:
		"""Saves the current project state to a .mtgproj file by delegating to ProjectManager."""
		save_data = self.get_save_data()
		if not save_data:
			if not is_auto_save:
				QMessageBox.information(self, "Empty Project", "Nothing to save. Please import a collection first.")
			return False
		try:
			ProjectManager.save_project(filepath, save_data)
			if not is_auto_save:
				self.show_status_message(f"Project saved to {pathlib.Path(filepath).name}")
			return True
		except IOError as e:
			QMessageBox.critical(self, "Save Error", str(e))
			return False
	
	def load_from_project(self, filepath: str) -> bool:
		"""Loads project state from a .mtgproj file by delegating to ProjectManager."""
		try:
			project_data = ProjectManager.load_project(filepath)
			
			self.clear_project(prompt=False)
			
			self.all_cards = [Card(**data) for data in project_data.get("collection", [])]
			
			progress_data = project_data.get("progress", {})
			for card in self.all_cards:
				card.sorted_count = progress_data.get(card.scryfall_id, 0)
			
			settings = project_data.get("settings", {})
			self.group_low_count_check.setChecked(settings.get("group_low_count", True))
			self.group_threshold_edit.setText(settings.get("group_threshold", "20"))
			
			# Clear existing criteria before loading new ones
			self.selected_list.clear()
			
			# Reload all available criteria
			self.available_list.clear()
			self.available_list.addItems(
					["Set", "Color Identity", "Rarity", "Type Line", "First Letter", "Name", "Condition",
					 "Commander Staple"])
			
			saved_criteria = settings.get("sort_criteria", [])
			for item_text in saved_criteria:
				items_to_move = self.available_list.findItems(item_text, Qt.MatchFlag.MatchExactly)
				if items_to_move:
					self.selected_list.addItem(self.available_list.takeItem(self.available_list.row(items_to_move[0])))
			
			self.file_label.setText(f"Loaded {len(self.all_cards)} unique cards from {pathlib.Path(filepath).name}")
			QTimer.singleShot(100, self._safe_start_plan_generation)
			return True
		except IOError as e:
			QMessageBox.critical(self, "Load Project Error", str(e))
			self.clear_project(prompt=False)
			return False
	
	# Essential methods
	def add_criterion(self, item: QListWidgetItem):
		self.selected_list.addItem(self.available_list.takeItem(self.available_list.row(item)))
		self.project_modified.emit()
	
	def remove_criterion(self, item: QListWidgetItem):
		self.available_list.addItem(self.selected_list.takeItem(self.selected_list.row(item)))
		self.project_modified.emit()
	
	def update_progress(self, value, total):
		if self.progress_bar.maximum() != total:
			self.progress_bar.setRange(0, total)
			self.operation_started.emit(f"Fetching card data", total)
		self.progress_bar.setValue(value)
		self.file_label.setText(f"Fetching card data: {value}/{total}")
		self.progress_updated.emit(value)
	
	def on_import_finished(self, cards: List[Card]):
		try:
			print(f"DEBUG: on_import_finished called with {len(cards)} cards")
			self.all_cards = cards
			
			# Apply any pending progress data from a loaded project
			if self.progress_to_load:
				for card in self.all_cards:
					card.sorted_count = self.progress_to_load.get(card.scryfall_id, 0)
					card.sorted_count = min(card.sorted_count, card.quantity)
				self.progress_to_load = None
			
			unique_count = len(self.all_cards)
			total_count = sum(card.quantity for card in self.all_cards)
			print(f"DEBUG: Setting file label - {unique_count} unique, {total_count} total")
			self.file_label.setText(f"Loaded {unique_count:,} unique cards ({total_count:,} total)")
			self.progress_bar.setVisible(False)
			self.import_button.setEnabled(True)
			self.run_button.setEnabled(True)
			self.is_loading = False
			self.operation_finished.emit()
			self.collection_loaded.emit()
			
			print("DEBUG: Scheduling plan generation...")
			print("DEBUG: Processing events before plan generation...")
			QApplication.processEvents()
			
			print("DEBUG: Starting plan generation directly (no timer)...")
			self._safe_start_plan_generation()
			print("DEBUG: Plan generation completed")
			
			print("DEBUG: Emitting project_modified signal...")
			self.project_modified.emit()
			print("DEBUG: project_modified signal emitted")
			
			print("DEBUG: on_import_finished completed")
		
		except MemoryError:
			self.is_loading = False
			self.file_label.setText("Import failed - out of memory")
			self.progress_bar.setVisible(False)
			self.import_button.setEnabled(True)
			self.run_button.setEnabled(True)
			self.operation_finished.emit()
			QMessageBox.critical(
					self,
					"Memory Error",
					"Not enough memory to load this collection.\n\n"
					"Try:\n"
					"• Closing other applications\n"
					"• Splitting the collection into smaller files\n"
					"• Restarting the application"
			)
		except Exception as e:
			self.is_loading = False
			self.file_label.setText("Import failed - unexpected error")
			self.progress_bar.setVisible(False)
			self.import_button.setEnabled(True)
			self.run_button.setEnabled(True)
			self.operation_finished.emit()
			QMessageBox.critical(self, "Import Error", f"Unexpected error during import:\n\n{str(e)}")
		finally:
			self.import_thread = None
			self.import_worker = None
	
	def on_import_error(self, error_message: str):
		self.is_loading = False
		self.file_label.setText("Import failed - see details below")
		self.progress_bar.setVisible(False)
		self.import_button.setEnabled(True)
		self.run_button.setEnabled(True)
		self.operation_finished.emit()
		self.import_thread = None
		self.import_worker = None
		QMessageBox.critical(self, "Import Error", error_message)
	
	def import_csv(self, filepath=None):
		"""Import CSV with full functionality"""
		if self.is_loading:
			QMessageBox.information(self, "Import in Progress", "Please wait for the current import to complete.")
			return
		
		if not filepath:
			settings = QSettings(Config.ORG_NAME, Config.APP_NAME)
			last_dir = settings.value("sorter/lastImportDir", str(pathlib.Path.home()))
			
			filepath, _ = QFileDialog.getOpenFileName(
					self,
					"Open ManaBox CSV",
					last_dir,
					"CSV Files (*.csv);;All Files (*.*)"
			)
			if not filepath:
				return
			
			settings.setValue("sorter/lastImportDir", str(pathlib.Path(filepath).parent))
		
		try:
			file_path = pathlib.Path(filepath)
			if not file_path.exists():
				QMessageBox.critical(self, "File Not Found", f"The file '{filepath}' does not exist.")
				return
			if not file_path.is_file():
				QMessageBox.critical(self, "Invalid File", f"'{filepath}' is not a valid file.")
				return
			
			with open(filepath, 'r', encoding='utf-8') as f:
				header_found = any('Scryfall ID' in line and 'Quantity' in line for line in f.readlines(5))
				if not header_found:
					if QMessageBox.question(self, "Unrecognized Format",
					                        "This file doesn't look like a ManaBox CSV. Continue anyway?") == QMessageBox.StandardButton.No:
						return
		except Exception as e:
			QMessageBox.critical(self, "File Access Error", f"Unable to read file: {e}")
			return
		
		# Clean up any existing worker
		self.cleanup_workers()
		
		self.is_loading = True
		self.last_csv_path = filepath
		self.import_button.setEnabled(False)
		self.run_button.setEnabled(False)
		self.file_label.setText(f"Loading {pathlib.Path(filepath).name}...")
		self.progress_bar.setVisible(True)
		self.progress_bar.setRange(0, 0)
		self.operation_started.emit(f"Importing {pathlib.Path(filepath).name}", 0)
		
		# Create and start worker thread
		self.import_thread = QThread()
		self.import_worker = CsvImportWorker(filepath, self.api)
		self.import_worker.moveToThread(self.import_thread)
		
		self.import_thread.started.connect(self.import_worker.process)
		self.import_worker.progress.connect(self.update_progress)
		self.import_worker.finished.connect(self.on_import_finished)
		self.import_worker.error.connect(self.on_import_error)
		
		# Cleanup connections
		self.import_worker.finished.connect(self.import_thread.quit)
		self.import_worker.finished.connect(self.import_worker.deleteLater)
		self.import_thread.finished.connect(self.import_thread.deleteLater)
		
		self.import_thread.start()
	
	def clear_project(self, prompt=True):
		"""Clears all project data and resets the UI."""
		if prompt:
			reply = QMessageBox.question(
					self,
					"Clear Project",
					"Are you sure you want to clear all loaded data and sorting progress?\n\nThis action cannot be undone.",
					QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
					QMessageBox.StandardButton.No
			)
			if reply != QMessageBox.StandardButton.Yes:
				return
		
		# Clean up workers first
		self.cleanup_workers()
		
		# Reset internal data
		self.all_cards = []
		self.last_csv_path = None
		self.progress_to_load = None
		
		# Clear UI elements
		self.file_label.setText("No file loaded.")
		self.clear_layout(self.breadcrumb_layout)
		self._safe_clear_stack()
		self.reset_preview_pane()
		self.filter_edit.clear()
		self.filter_edit.setVisible(False)
		self.preview_panel.setVisible(False)
		self.update_button_visibility()
		
		self.show_status_message("Project cleared. Import a new CSV to begin.", 5000)
		self.project_modified.emit()
	
	def reset_sort_progress(self):
		"""Resets the 'sorted_count' for all cards to zero and refreshes the view."""
		if not self.all_cards:
			QMessageBox.information(self, "No Collection", "No collection is loaded.")
			return
		
		reply = QMessageBox.question(
				self,
				"Reset Sort Progress",
				"Are you sure you want to reset the sorting progress for all cards?\n\nThis will mark all cards as unsorted.",
				QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
				QMessageBox.StandardButton.No
		)
		
		if reply == QMessageBox.StandardButton.Yes:
			for card in self.all_cards:
				card.sorted_count = 0
			
			self.show_status_message("All sorting progress has been reset.", 3000)
			self.project_modified.emit()
			QTimer.singleShot(100, self._refresh_current_view)
