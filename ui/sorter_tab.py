# ui/sorter_tab.py - Collection sorting interface

import collections
import csv
import os
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
from .status_manager import StatusManager, StatusAwareMixin
from ui.custom_widgets import NavigableTreeWidget, SortableTreeWidgetItem
from ui.set_sorter_view import SetSorterView
from ui.sorter_tab_ui import SorterTabUi
from workers.threads import CsvImportWorker, ImageFetchWorker, BackgroundImageCacheWorker, WorkerManager


class ManaBoxSorterTab(QWidget, StatusAwareMixin):
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
		
		# Centralized worker management
		self.worker_manager = WorkerManager()
		
		# Legacy thread/worker attributes for backward compatibility
		self.import_thread: QThread | None = None
		self.import_worker: CsvImportWorker | None = None
		self.image_thread: QThread | None = None
		self.image_worker: ImageFetchWorker | None = None
		self.background_cache_thread: QThread | None = None
		self.background_cache_worker: BackgroundImageCacheWorker | None = None
		
		self.cached_images: dict[str, str] = {}  # scryfall_id -> cache_path
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
		
		# UI widget attributes will be created by SorterTabUi using factory pattern
		# All widget attributes are dynamically created and assigned by the factory
		
		main_layout = QVBoxLayout(self)
		QTimer.singleShot(0, self.setup_ui)
	
	def cleanup_workers(self):
		"""Clean up any running workers WITHOUT marking widget as destroyed"""
		# Use centralized worker management
		self.worker_manager.cleanup_all()
		
		# Legacy cleanup for backward compatibility
		from workers.threads import cleanup_worker_thread
		cleanup_worker_thread(self.import_thread, self.import_worker)
		cleanup_worker_thread(self.image_thread, self.image_worker)
		cleanup_worker_thread(self.background_cache_thread, self.background_cache_worker)
	
	def handle_error(self, operation: str, error: Exception, show_message: bool = True, 
	                 message_timeout: int = 5000, log_prefix: str = "ERROR", 
	                 error_category: str = "GENERAL", additional_context: str = None) -> None:
		"""Centralized error handling with enhanced categorization and context"""
		try:
			# Enhanced logging with structured information
			context_info = f" | Context: {additional_context}" if additional_context else ""
			error_type = type(error).__name__
			timestamp = __import__('datetime').datetime.now().strftime("%H:%M:%S")
			
			# Log with enhanced formatting
			print(f"[{timestamp}] {log_prefix}[{error_category}]: {operation} failed")
			print(f"  Error Type: {error_type}")
			print(f"  Error Message: {error}")
			if context_info:
				print(f"  {context_info}")
			
			# Print full traceback for debugging
			import traceback
			traceback.print_exc()
			
			# Show user message if requested
			if show_message and hasattr(self, 'show_status_message'):
				# Truncate long error messages for better UX
				error_msg = str(error)
				if len(error_msg) > 100:
					error_msg = error_msg[:97] + "..."
				
				# Add category-specific messaging
				if error_category == "CRITICAL":
					error_msg = f"Critical Error: {error_msg}"
				elif error_category == "UI":
					error_msg = f"Interface Error: {error_msg}"
				elif error_category == "BACKGROUND":
					error_msg = f"Background Task Error: {error_msg}"
				
				self.show_status_message(f"Error: {error_msg}", message_timeout, style='error')
		
		except Exception as handler_error:
			# Fallback error handling to prevent infinite loops
			print(f"CRITICAL: Error handler itself failed: {handler_error}")
			import traceback
			traceback.print_exc()
	
	def handle_silent_error(self, operation: str, error: Exception, log_prefix: str = "ERROR", 
	                       error_category: str = "SILENT", additional_context: str = None) -> None:
		"""Handle errors silently without user notification"""
		self.handle_error(operation, error, show_message=False, log_prefix=log_prefix, 
		                 error_category=error_category, additional_context=additional_context)
	
	def handle_ui_error(self, operation: str, error: Exception, show_message: bool = True, 
	                   additional_context: str = None) -> None:
		"""Handle UI-specific errors with appropriate logging"""
		self.handle_error(operation, error, show_message=show_message, log_prefix="[UI]", 
		                 error_category="UI", additional_context=additional_context)
	
	def handle_background_error(self, operation: str, error: Exception, show_message: bool = False, 
	                           additional_context: str = None) -> None:
		"""Handle background operation errors"""
		self.handle_error(operation, error, show_message=show_message, log_prefix="[Background]", 
		                 error_category="BACKGROUND", additional_context=additional_context)
	
	def handle_critical_error(self, operation: str, error: Exception, show_message: bool = True, 
	                         additional_context: str = None) -> None:
		"""Handle critical errors that may require user attention"""
		self.handle_error(operation, error, show_message=show_message, log_prefix="[CRITICAL]", 
		                 error_category="CRITICAL", additional_context=additional_context)
	
	def handle_network_error(self, operation: str, error: Exception, show_message: bool = True, 
	                        additional_context: str = None) -> None:
		"""Handle network-related errors with specific messaging"""
		context = f"Network operation failed{': ' + additional_context if additional_context else ''}"
		self.handle_error(operation, error, show_message=show_message, log_prefix="[Network]", 
		                 error_category="NETWORK", additional_context=context)
	
	def handle_file_error(self, operation: str, error: Exception, show_message: bool = True, 
	                     additional_context: str = None) -> None:
		"""Handle file I/O errors with specific messaging"""
		context = f"File operation failed{': ' + additional_context if additional_context else ''}"
		self.handle_error(operation, error, show_message=show_message, log_prefix="[File]", 
		                 error_category="FILE", additional_context=context)

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
		"""Handle item click with drill-down navigation"""
		if self._is_destroyed or not item:
			return
		
		try:
			# Update preview for individual cards, not for groups
			if self._should_show_card_preview(item, next_level):
				self.update_card_preview(item)
			else:
				self.reset_preview_pane()
			
			# Check if we should drill down (avoid for individual cards)
			self.sort_order = self._get_sort_order_safely()
			current_level = next_level - 1
			current_widget = self.results_stack.currentWidget()
			
			# Special handling for SetSorterView - when clicking on letter piles, drill down to next level
			if isinstance(current_widget, SetSorterView):
				cards_in_pile = self._get_cards_from_item(item)
				if cards_in_pile:
					# Navigate to the correct level and create a Name view
					self.navigate_to_level(self.results_stack.currentIndex())
					breadcrumb_text = item.text(0)
					self.add_breadcrumb(breadcrumb_text, next_level)
					# Jump directly to individual cards (Name level) - skip intermediate sorting levels
					final_level = len(self.sort_order)  # This is the Name level (individual cards)
					self.create_new_view(cards_in_pile, final_level)
					self.update_button_visibility()
					return
			
			if 0 <= current_level < len(self.sort_order) and self.sort_order[current_level] == "Name":
				# This is a card item, just update preview
				return
			
			# This is a group item, drill down
			self.show_status_message(f"Drilling down into '{item.text(0).split(': ')[-1]}'...", 2000, style='info')
			self.drill_down(item, next_level)
		
		except Exception as e:
			self.handle_ui_error("handle_item_click", e, additional_context=f"item: {item.text(0) if item else 'None'}, level: {next_level}")
	
	def drill_down(self, item: QTreeWidgetItem, next_level: int):
		"""Handle drill down with crash prevention"""
		if self._is_destroyed or not item or self._is_navigating:
			return
		
		try:
			self._is_navigating = True
			
			# Safe sort_order retrieval
			self.sort_order = self._get_sort_order_safely()
			if not self.sort_order:
				self.show_status_message("Configuration error: Sort criteria not available.", 3000, style='error')
				return
			
			# Check if we can drill down further
			if next_level > len(self.sort_order):
				self.show_status_message("Cannot drill down further - no more sort criteria available.", 3000, style='warning')
				return
			
			# Special handling for Set → First Letter transition
			current_level_index = next_level - 1
			
			if 0 <= current_level_index < len(self.sort_order):
				current_criterion = self.sort_order[current_level_index]
				next_criterion = self.sort_order[next_level] if next_level < len(self.sort_order) else None
				
				if current_criterion == "Set" and next_criterion == "First Letter":
					cards_in_set = self._get_cards_from_item(item)
					
					if not cards_in_set:
						self.show_status_message("No cards found in selected set.", 2000, style='warning')
						return
					
					self.navigate_to_level(current_level_index)
					breadcrumb_text = item.text(0).split(': ')[-1]
					self.add_breadcrumb(f"{breadcrumb_text} (Letter Sort)", next_level)
					self.create_set_sorter_view(cards_in_set, breadcrumb_text)
					return
			
			# Default drill-down behavior
			cards_in_group = self._get_cards_from_item(item)
			
			if not cards_in_group:
				self.show_status_message("No cards found in selected group.", 2000, style='warning')
				return
			
			# Navigate to the appropriate level with error handling
			try:
				self.navigate_to_level(next_level - 1)
			except Exception as nav_error:
				print(f"ERROR: Navigation failed: {nav_error}")
				import traceback
				traceback.print_exc()
				self.show_status_message("Navigation error occurred.", 3000, style='error')
				return
			
			# Add breadcrumb for this level with error handling
			try:
				breadcrumb_text = item.text(0).split(': ')[-1]  # Remove any prefix
				self.add_breadcrumb(breadcrumb_text, next_level)
			except Exception as breadcrumb_error:
				print(f"ERROR: Breadcrumb creation failed: {breadcrumb_error}")
				# Continue - breadcrumb failure shouldn't stop the process
			
			# Create new view for the next level with error handling
			try:
				self.create_new_view(cards_in_group, next_level)
			except Exception as create_error:
				print(f"ERROR: View creation failed: {create_error}")
				import traceback
				traceback.print_exc()
				self.show_status_message("Failed to create view for next level.", 3000, style='error')
				return
			
			# Update button visibility with error handling
			try:
				self.update_button_visibility()
			except Exception as button_error:
				print(f"ERROR: Button visibility update failed: {button_error}")
				# Continue - button visibility failure shouldn't stop the process
		
		except Exception as e:
			self.handle_ui_error("drill_down", e, additional_context=f"item: {item.text(0) if item else 'None'}, level: {next_level}, navigating: {self._is_navigating}")
		finally:
			self._is_navigating = False
	
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
					QTimer.singleShot(200, self._safe_start_plan_generation)
				self._is_refreshing = False
				return
			
			# Standard refresh logic
			level = self.results_stack.currentIndex()
			cards_to_process = getattr(current_widget, 'cards_for_view', self.all_cards)
			self.sort_order = self._get_sort_order_safely()
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
					self.handle_silent_error("post-population refresh", e)
				finally:
					self._is_refreshing = False
					self.update_button_visibility()
					self._update_view_layout()
			
			current_widget._populate_tree_progressively(nodes, on_finished=on_population_finished)
		except Exception as e:
			self.handle_ui_error("_refresh_current_view setup", e, additional_context=f"destroyed: {self._is_destroyed}, refreshing: {self._is_refreshing}")
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
			self.handle_silent_error("restoring tree state", e)
		finally:
			tree_widget.blockSignals(False)
			# Manually trigger the selection update for the preview pane since signals were blocked
			if tree_widget.currentItem():
				self.on_tree_selection_changed(tree_widget.currentItem(), None)
			# Restore scroll position with slight delay
			QTimer.singleShot(50, lambda: tree_widget.verticalScrollBar().setValue(scroll_position))
	
	def on_show_sorted_toggled(self):
		"""Handle show sorted toggle with simple defer"""
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
			self.handle_silent_error("updating sorted item visibility", e)
	
	def setup_ui(self):
		"""Creates the UI by delegating to the SorterTabUi class."""
		self.ui = SorterTabUi(self)
		self.ui.setup_ui(self.layout())
		
		# Initialize StatusAwareMixin after UI is set up
		StatusAwareMixin.__init__(self)
		self._init_status_manager()
	
	def _safe_start_plan_generation(self):
		"""Safe wrapper for plan generation with comprehensive error handling"""
		if self._is_destroyed or self._is_generating_plan:
			return
		
		try:
			self.start_new_plan_generation()
		except Exception as e:
			self.handle_error("_safe_start_plan_generation", e, message_timeout=5000)

	def start_new_plan_generation(self):
		"""Resets the entire view and generates a new plan from the top level."""
		if not self.all_cards:
			QMessageBox.information(self, "No Collection", "Please import a collection first.")
			return
		
		if self._is_generating_plan:
			return
		
		self._is_generating_plan = True
		try:
			# Clear existing layout and stack
			self.clear_layout(self.breadcrumb_layout)
			self._safe_clear_stack()
			self.reset_preview_pane()
			
			# Add home breadcrumb and create first level view
			self.add_breadcrumb("Home", 0)
			self.create_new_view(self.all_cards, 0)
			self.update_button_visibility()
			self.filter_edit.setVisible(True)
		
		except Exception as e:
			self.handle_critical_error("start_new_plan_generation", e, additional_context=f"cards_count: {len(self.all_cards) if self.all_cards else 0}, generating: {self._is_generating_plan}")
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
			self.handle_silent_error("clearing stack", e)
	
	def create_new_view(self, cards_in_group: List[Card], level: int):
		"""Create new view with full functionality"""
		try:
			tree = NavigableTreeWidget()
			tree.cards_for_view = cards_in_group
			tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
			
			# Set up tree headers
			show_sorted = self.show_sorted_check.isChecked()
			header_label = "Total Count" if show_sorted else "Unsorted Count"
			tree.setHeaderLabels(['Group', header_label])
			
			# Enable checkboxes for all items
			tree.setRootIsDecorated(True)
			tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
			tree.setSortingEnabled(True)
			
			# Connect signals with proper handlers
			def item_clicked(item, column):
				try:
					self.handle_item_click(item, level + 1)
				except Exception as e:
					self.handle_ui_error("handle_item_click", e)
			
			tree.itemClicked.connect(item_clicked)
			
			# Connect double-click for drill-down
			def item_double_clicked(item, column):
				try:
					self.handle_item_click(item, level + 1)
				except Exception as e:
					self.handle_ui_error("Double-click handling", e)
			
			tree.itemDoubleClicked.connect(item_double_clicked)
			tree.drillDownRequested.connect(lambda item: self.drill_down(item, level + 1))
			tree.navigateUpRequested.connect(lambda: self.navigate_and_refresh(level - 1) if level > 0 else None)
			tree.currentItemChanged.connect(self.update_button_visibility)
			tree.currentItemChanged.connect(self.on_tree_selection_changed)
			tree.itemSortedToggled.connect(self.on_item_sorted_toggled)
			
			# Determine sort criterion and generate breakdown
			self.sort_order = self._get_sort_order_safely()
			criterion = self.sort_order[level] if 0 <= level < len(self.sort_order) else None
			nodes = self._generate_level_breakdown(cards_in_group, criterion)
			
			# Populate tree progressively
			tree._populate_tree_progressively(nodes, chunk_size=50)
			
			# Add to stack and set as current
			self.results_stack.addWidget(tree)
			self.results_stack.setCurrentWidget(tree)
		
		except Exception as e:
			self.handle_ui_error("create_new_view", e, additional_context=f"cards_count: {len(cards_in_group) if cards_in_group else 0}, level: {level}")
	
	def create_set_sorter_view(self, cards_to_sort: List[Card], set_name: str):
		"""Create SetSorterView"""
		try:
			view = SetSorterView(cards_to_sort, set_name, self)
			self.results_stack.addWidget(view)
			self.results_stack.setCurrentWidget(view)
			self._update_view_layout()
		except Exception as e:
			self.handle_ui_error("creating set sorter view", e, additional_context=f"set_name: {set_name}, cards_count: {len(cards_to_sort) if cards_to_sort else 0}")
	
	def _generate_level_breakdown(self, current_cards: List[Card], criterion: str | None) -> List[SortGroup]:
		"""Generate breakdown for current level"""
		try:
			show_sorted = self.show_sorted_check.isChecked()
			
			if not criterion or criterion == "Name":
				nodes = [SortGroup(group_name=c.name, count=(c.quantity - c.sorted_count), cards=[c], is_card_leaf=True)
				         for c in current_cards]
				for node in nodes:
					node.total_count = node.cards[0].quantity
					node.unsorted_count = node.count
				return sorted(nodes, key=lambda sg: sg.group_name or "")
			
			groups = collections.defaultdict(list)
			for i, card in enumerate(current_cards):
				try:
					value = self._get_nested_value(card, criterion)
					groups[value].append(card)
				except Exception as e:
					self.handle_silent_error(f"getting nested value for card {card.name}", e)
					groups["ERROR"].append(card)
			
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
					self.handle_silent_error(f"creating node for group {name}", e)
					continue
			
			return nodes
		
		except Exception as e:
			self.handle_ui_error("_generate_level_breakdown", e, additional_context=f"criterion: {criterion}, cards_count: {len(current_cards) if current_cards else 0}")
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
	
	def _get_sort_order_safely(self) -> List[str]:
		"""Safely retrieve sort order from selected_list"""
		try:
			if not self.selected_list:
				print("ERROR: selected_list is None")
				return []
			
			sort_order = []
			for i in range(self.selected_list.count()):
				item = self.selected_list.item(i)
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
			self.handle_ui_error("retrieving sort order", e, additional_context=f"selected_list_count: {self.selected_list.count() if self.selected_list else 'None'}")
			return []
	
	def _should_show_card_preview(self, item: QTreeWidgetItem, next_level: int) -> bool:
		"""Determine if card preview should be shown for this item"""
		if not item:
			return False
		
		# Check if we're currently in SetSorterView (letter piles view)
		current_widget = self.results_stack.currentWidget()
		if isinstance(current_widget, SetSorterView):
			# Never show card preview for letter piles in SetSorterView
			return False
		
		# Get current sort order to determine what level we're at
		sort_order = self._get_sort_order_safely()
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
		current_widget = self.results_stack.currentWidget()
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
			self.handle_ui_error("navigate_to_level", e, additional_context=f"target_level: {level}, stack_count: {self.results_stack.count() if self.results_stack else 'None'}")
	
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
		"""Show status message with visual feedback using StatusManager"""
		# Use the StatusAwareMixin method which delegates to StatusManager
		super().show_status_message(message, timeout)
	
	def reset_preview_pane(self, *args):
		"""Reset preview pane safely"""
		# Use centralized worker management
		self.worker_manager.cleanup_worker('image_worker')
		
		# Legacy cleanup for backward compatibility
		from workers.threads import cleanup_worker_thread
		cleanup_worker_thread(self.image_thread, self.image_worker)
		
		self.current_loading_id = None
		self.preview_card = None
		self.card_image_label.setText("Select an individual card to see its image.")
		self.card_image_label.setPixmap(QPixmap())
		self.card_details_label.setText("Navigate to individual cards to see details.")
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
		
		# Set up the image pane - check cache first, then on-demand fetching
		if card.image_uri:
			# Try to load cached image first
			if self.load_cached_image(card.scryfall_id):
				# Image loaded from cache, fetch button already hidden
				pass
			else:
				# Image not cached, show fetch button
				self.card_image_label.setText("Image available - click to load.")
				self.fetch_image_button.setVisible(True)
		else:
			self.card_image_label.setText("No image available for this card.")
			self.fetch_image_button.setVisible(False)
	
	def on_fetch_image_clicked(self):
		"""Starts the download for the currently previewed card's image."""
		try:
			# Check if another fetch is already running - safely handle deleted Qt objects
			try:
				if hasattr(self, 'image_thread') and self.image_thread and self.image_thread.isRunning():
					return
			except RuntimeError as e:
				# Qt object was deleted, clear the reference and continue
				self.image_thread = None
				self.image_worker = None
			
			# Validate preview card
			if not hasattr(self, 'preview_card') or not self.preview_card:
				self.card_image_label.setText("No card selected.")
				return
			
			if not self.preview_card.image_uri:
				self.card_image_label.setText("No image available for this card.")
				return
			
			card = self.preview_card
			
			# Store current loading ID for validation
			self.current_loading_id = card.scryfall_id
			
			# Update UI state
			self.card_image_label.setText("Loading image...")
			self.fetch_image_button.setEnabled(False)
			
			# Clean up any existing thread/worker
			try:
				# Use centralized worker management
				self.worker_manager.cleanup_worker('image_worker')
				
				# Legacy cleanup for backward compatibility
				if hasattr(self, 'image_thread') and self.image_thread:
					from workers.threads import cleanup_worker_thread
					cleanup_worker_thread(self.image_thread, getattr(self, 'image_worker', None))
			except Exception as cleanup_error:
				print(f"[UI] Error during thread cleanup: {cleanup_error}")
			
			# Create new thread and worker
			self.image_thread = QThread()
			self.image_worker = ImageFetchWorker(card.image_uri, card.scryfall_id, self.api, parent=None)
			
			# Move worker to thread
			self.image_worker.moveToThread(self.image_thread)
			
			# Connect signals with error handling
			try:
				self.image_thread.started.connect(self.image_worker.process)
				self.image_worker.finished.connect(self.on_image_loaded)
				self.image_worker.error.connect(self.on_image_error)
				self.image_worker.finished.connect(self.image_thread.quit)
				self.image_worker.finished.connect(self.image_worker.deleteLater)
				self.image_thread.finished.connect(self.image_thread.deleteLater)
			except Exception as signal_error:
				print(f"[UI] Error connecting signals: {signal_error}")
				self.on_image_error(f"Failed to setup image fetch: {signal_error}")
				return
			
			# Start the thread
			self.image_thread.start()
			
		except Exception as e:
			self.handle_ui_error("on_fetch_image_clicked", e, additional_context=f"preview_card: {self.preview_card.name if self.preview_card else 'None'}, thread_running: {self.image_thread.isRunning() if self.image_thread else 'None'}")
			
			# Reset UI state on error
			try:
				self.fetch_image_button.setEnabled(True)
				self.card_image_label.setText(f"Error starting image fetch: {str(e)}")
			except:
				pass  # Don't crash the UI
	
	def on_image_loaded(self, image_data: bytes, scryfall_id: str):
		"""Handle successful image loading"""
		try:
			# Safe button re-enable
			try:
				if hasattr(self, 'fetch_image_button') and self.fetch_image_button:
					self.fetch_image_button.setEnabled(True)
			except Exception as button_error:
				print(f"[UI] Button enable error: {button_error}")
			
			# Check if this is still the current request
			try:
				if hasattr(self, 'current_loading_id') and scryfall_id != self.current_loading_id:
					return
			except Exception as id_check_error:
				print(f"[UI] ID check error: {id_check_error}")
			
			# Validate image data with multiple checks
			try:
				if not image_data:
					self._safe_set_label_text("No image data received.")
					return
				
				if not isinstance(image_data, bytes):
					self._safe_set_label_text("Invalid image data format.")
					return
				
				if len(image_data) < 100:
					self._safe_set_label_text("Image data too small.")
					return
				
			except Exception as validation_error:
				print(f"[UI] Data validation error: {validation_error}")
				self._safe_set_label_text("Data validation failed.")
				return
			
			# Create and load pixmap with maximum protection
			try:
				pixmap = QPixmap()
				if not pixmap.loadFromData(image_data):
					self._safe_set_label_text("Failed to decode image.")
					return
				
				if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
					self._safe_set_label_text("Invalid image format.")
					return
				
			except Exception as pixmap_error:
				print(f"[UI] Pixmap creation error: {pixmap_error}")
				self._safe_set_label_text("Image creation failed.")
				return
			
			# Scale and display with protection
			try:
				if hasattr(self, 'card_image_label') and self.card_image_label:
					label_size = self.card_image_label.size()
					
					if label_size.width() > 10 and label_size.height() > 10:
						scaled_pixmap = pixmap.scaled(
							label_size,
							Qt.AspectRatioMode.KeepAspectRatio,
							Qt.TransformationMode.SmoothTransformation
						)
						self.card_image_label.setPixmap(scaled_pixmap)
					else:
						self.card_image_label.setPixmap(pixmap)
			
			except Exception as display_error:
				print(f"[UI] Image display error: {display_error}")
				self._safe_set_label_text("Display failed.")
		
		except Exception as critical_error:
			print(f"[UI] CRITICAL ERROR in on_image_loaded: {critical_error}")
			try:
				import traceback
				traceback.print_exc()
			except:
				pass
			self._safe_set_label_text("Critical error occurred.")
		
		finally:
			# Safe cleanup with proper Qt object handling
			try:
				# Use the same safe cleanup pattern as background cache
				if hasattr(self, 'image_worker') and self.image_worker:
					self.image_worker.deleteLater()
				if hasattr(self, 'image_thread') and self.image_thread:
					self.image_thread.quit()
					self.image_thread.wait(1000)  # Wait up to 1 second
					self.image_thread.deleteLater()
				# Only set to None after Qt cleanup is scheduled
				self.image_thread = None
				self.image_worker = None
			except Exception as cleanup_error:
				print(f"[UI] Cleanup error: {cleanup_error}")
	
	def _safe_set_label_text(self, text: str):
		"""Safely set label text with error protection"""
		try:
			if hasattr(self, 'card_image_label') and self.card_image_label:
				self.card_image_label.setText(text)
		except Exception as label_error:
			print(f"[UI] Label text error: {label_error}")
			try:
				# Last resort - try to set some text
				if hasattr(self, 'card_image_label'):
					self.card_image_label.setText("Error")
			except:
				print(f"[UI] Could not set any label text")
	
	def on_image_error(self, error_message: str):
		"""Handle image loading errors"""
		try:
			# Safe button re-enable
			try:
				if hasattr(self, 'fetch_image_button') and self.fetch_image_button:
					self.fetch_image_button.setEnabled(True)
			except Exception as button_error:
				print(f"[UI] Error re-enabling button: {button_error}")
			
			# Safe error message display
			try:
				if isinstance(error_message, str):
					display_message = error_message
					if len(display_message) > 150:
						display_message = display_message[:150] + "..."
					self._safe_set_label_text(f"Image unavailable:\n{display_message}")
				else:
					self._safe_set_label_text("Image fetch failed (invalid error)")
			
			except Exception as message_error:
				print(f"[UI] Error displaying message: {message_error}")
				self._safe_set_label_text("Image fetch failed")
		
		except Exception as critical_error:
			print(f"[UI] CRITICAL ERROR in on_image_error: {critical_error}")
			try:
				import traceback
				traceback.print_exc()
			except:
				pass
			self._safe_set_label_text("Error handler failed")
		
		finally:
			# Safe cleanup
			try:
				if hasattr(self, 'image_thread'):
					self.image_thread = None
				if hasattr(self, 'image_worker'):
					self.image_worker = None
			except Exception as cleanup_error:
				print(f"[UI] Error during error cleanup: {cleanup_error}")
	
	def start_background_image_cache(self, cards: List[Card]):
		"""Start background caching of card images"""
		try:
			# Don't start if already running
			if (hasattr(self, 'background_cache_thread') and 
				self.background_cache_thread and 
				self.background_cache_thread.isRunning()):
				return
			
			# Clean up any existing thread
			# Use centralized worker management
			self.worker_manager.cleanup_worker('background_cache_worker')
			
			# Legacy cleanup for backward compatibility
			from workers.threads import cleanup_worker_thread
			cleanup_worker_thread(self.background_cache_thread, self.background_cache_worker)
			
			# Create new thread and worker
			self.background_cache_thread = QThread()
			self.background_cache_worker = BackgroundImageCacheWorker(cards, self.api, max_concurrent=2)
			
			# Move worker to thread
			self.background_cache_worker.moveToThread(self.background_cache_thread)
			
			# Connect signals
			self.background_cache_thread.started.connect(self.background_cache_worker.process)
			self.background_cache_worker.image_cached.connect(self.on_image_cached)
			self.background_cache_worker.progress.connect(self.on_cache_progress)
			self.background_cache_worker.finished.connect(self.on_cache_finished)
			self.background_cache_worker.error.connect(self.on_cache_error)
			
			# Safe cleanup: let Qt handle the deletion after thread finishes
			self.background_cache_worker.finished.connect(self.background_cache_thread.quit)
			self.background_cache_thread.finished.connect(self._cleanup_background_cache)
			
			# Start the thread
			self.background_cache_thread.start()
			
		except Exception as e:
			self.handle_background_error("starting background cache", e, additional_context=f"cards_count: {len(cards) if cards else 0}, thread_running: {self.background_cache_thread.isRunning() if self.background_cache_thread else 'None'}")
	
	def on_image_cached(self, scryfall_id: str, cache_path: str):
		"""Handle successful background image caching"""
		self.cached_images[scryfall_id] = cache_path
		
		# If this is the currently previewed card, update the display
		if (hasattr(self, 'preview_card') and 
			self.preview_card and 
			self.preview_card.scryfall_id == scryfall_id):
			self.load_cached_image(scryfall_id)
	
	def on_cache_progress(self, current: int, total: int):
		"""Handle background cache progress updates"""
		pass  # Progress is handled silently
	
	def on_cache_finished(self, total_cached: int):
		"""Handle background cache completion"""
		# Don't set references to None here - let Qt cleanup handle it
		pass
	
	def _cleanup_background_cache(self):
		"""Safely cleanup background cache thread and worker after Qt finishes"""
		if self.background_cache_worker:
			self.background_cache_worker.deleteLater()
		if self.background_cache_thread:
			self.background_cache_thread.deleteLater()
		# Only set to None after Qt cleanup is scheduled
		self.background_cache_worker = None
		self.background_cache_thread = None
	
	def on_cache_error(self, scryfall_id: str, error_message: str):
		"""Handle background cache errors"""
		if scryfall_id != "SYSTEM":  # Don't log individual card failures
			pass  # Silently handle individual failures
		else:
			print(f"[BackgroundCache] System error: {error_message}")
	
	def load_cached_image(self, scryfall_id: str):
		"""Load a cached image directly from disk"""
		try:
			cache_path = self.cached_images.get(scryfall_id)
			if not cache_path:
				# Check if file exists in standard cache location
				cache_file = Config.IMAGE_CACHE_DIR / f"{scryfall_id}.jpg"
				if cache_file.exists():
					cache_path = str(cache_file)
					self.cached_images[scryfall_id] = cache_path
			
			if cache_path and os.path.exists(cache_path):
				# Load image data
				with open(cache_path, 'rb') as f:
					image_data = f.read()
				
				# Create and display pixmap
				pixmap = QPixmap()
				if pixmap.loadFromData(image_data):
					scaled_pixmap = pixmap.scaled(
						self.card_image_label.size(),
						Qt.AspectRatioMode.KeepAspectRatio,
						Qt.TransformationMode.SmoothTransformation
					)
					self.card_image_label.setPixmap(scaled_pixmap)
					
					# Hide the fetch button since image is already displayed
					self.fetch_image_button.setVisible(False)
					return True
		
		except Exception as e:
			self.handle_silent_error("loading cached image", e)
		
		return False
	
	def on_tree_selection_changed(self, current, previous):
		"""Handle tree selection changes safely"""
		if current:
			# Check if we should show preview for selection changes
			if self._should_show_card_preview_for_selection(current):
				self.update_card_preview(current)
			else:
				self.reset_preview_pane()
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
			self.show_status_message(f"Marked {len(selected_items)} groups as sorted ({total_cards_affected} cards)", style='success')
			self.project_modified.emit()
			QTimer.singleShot(50, self._refresh_current_view)
	
	def mark_item_as_sorted(self, item: QTreeWidgetItem):
		"""Toggles the sorted status of a single item, used by double-click."""
		cards = self._get_cards_from_item(item)
		if not cards:
			self.show_status_message(" Could not find cards for this group.", style='warning')
			return
		
		is_already_sorted = all(c.is_fully_sorted for c in cards)
		
		for card in cards:
			if is_already_sorted:
				card.sorted_count = 0
			else:
				card.sorted_count = card.quantity
		
		if is_already_sorted:
			self.show_status_message(f" Group '{item.text(0)}' marked as UNSORTED.", style='warning')
		else:
			self.show_status_message(f" Group '{item.text(0)}' marked as SORTED.", style='success')
			
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
				sort_order = self._get_sort_order_safely()
				
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
						self.show_status_message(f" Advancing to {next_criterion} level...", 3000, style='info')
						# This would require implementing automatic progression logic
						# For now, just show the message
		
		except Exception as e:
			self.handle_silent_error("_check_level_completion", e)
	
	def on_item_sorted_toggled(self, item: QTreeWidgetItem, is_sorted: bool):
		"""Handle checkbox toggle for sorted state"""
		if self._is_destroyed or not item:
			return
		
		try:
			# Get cards from the item
			cards = self._get_cards_from_item(item)
			if not cards:
				self.show_status_message(" Could not find cards for this group.", style='warning')
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
			self.show_status_message(f" Marked '{item.text(0)}' as {action}.", style='success')
			
			# Emit project modified signal
			self.project_modified.emit()
			
		except Exception as e:
			self.handle_ui_error("on_item_sorted_toggled", e)
	
	def _mark_cards_as_sorted(self, item: QTreeWidgetItem) -> bool:
		"""Internal method that only marks cards without refreshing, for batch operations."""
		cards_to_mark = self._get_cards_from_item(item)
		if not cards_to_mark:
			self.show_status_message(" Could not find cards for this group.", style='warning')
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
			self.handle_file_error("exporting file", e, additional_context=f"filepath: {filepath}, tree_items: {current_tree.topLevelItemCount() if current_tree else 'None'}")
			QMessageBox.critical(self, "Export Error", f"Failed to export file: {e}")
	
	def get_save_data(self) -> dict:
		"""Gathers all project data into a dictionary for saving."""
		if not self.all_cards:
			return {}
		
		progress = {c.scryfall_id: c.sorted_count for c in self.all_cards if c.sorted_count > 0}
		sort_criteria = self._get_sort_order_safely()
		
		cards_as_dicts = [c.__dict__ for c in self.all_cards]
		
		return {
				"metadata":   {"version": "1.1", "app": "MTGToolkit"},
				"collection": cards_as_dicts,
				"progress":   progress,
				"settings":   {
						"sort_criteria":   sort_criteria,
						"group_low_count": self.group_low_count_check.isChecked(),
						"optimal_grouping": self.optimal_grouping_check.isChecked(),
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
				self.show_status_message(f"Project saved to {pathlib.Path(filepath).name}", style='success')
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
			self.optimal_grouping_check.setChecked(settings.get("optimal_grouping", False))
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
			self.all_cards = cards
			
			# Apply any pending progress data from a loaded project
			if self.progress_to_load:
				for card in self.all_cards:
					card.sorted_count = self.progress_to_load.get(card.scryfall_id, 0)
					card.sorted_count = min(card.sorted_count, card.quantity)
				self.progress_to_load = None
			
			unique_count = len(self.all_cards)
			total_count = sum(card.quantity for card in self.all_cards)
			self.file_label.setText(f"Loaded {unique_count:,} unique cards ({total_count:,} total)")
			self.progress_bar.setVisible(False)
			self.import_button.setEnabled(True)
			self.run_button.setEnabled(True)
			self.is_loading = False
			self.operation_finished.emit()
			self.collection_loaded.emit()
			
			# Process events and start plan generation
			QApplication.processEvents()
			self._safe_start_plan_generation()
			self.project_modified.emit()
			
			# Start background image caching for better user experience
			self.start_background_image_cache(cards)
		
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
			self.handle_critical_error("import process", e, additional_context=f"cards_count: {len(self.all_cards) if self.all_cards else 0}, loading: {self.is_loading}")
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
			self.handle_file_error("file access", e, additional_context=f"filepath: {filepath}, exists: {file_path.exists() if 'file_path' in locals() else 'Unknown'}")
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
		
		self.show_status_message("Project cleared. Import a new CSV to begin.", 5000, style='info')
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
			
			self.show_status_message("All sorting progress has been reset.", 3000, style='info')
			self.project_modified.emit()
			QTimer.singleShot(100, self._refresh_current_view)
