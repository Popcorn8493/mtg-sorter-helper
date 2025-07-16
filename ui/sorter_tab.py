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
from ui.sorter_tab_ui import SorterTabUi
from workers.threads import CsvImportWorker, ImageFetchWorker, cleanup_worker_thread


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
		
		# FIXED: Signal connections with deferred execution to prevent recursion
		try:
			self.tree.markAsortedRequested.connect(self.on_mark_piles_sorted)
			mark_pile_button.clicked.connect(lambda: self.on_mark_piles_sorted(self.tree.selectedItems()))
			self.tree.itemDoubleClicked.connect(lambda item: self.on_mark_piles_sorted([item]))
			# Use deferred execution to prevent stack overflow
			self.tree.itemClicked.connect(lambda item, col: QTimer.singleShot(10, lambda: self.on_item_clicked(item, col)))
		except Exception as e:
			print(f"Warning: Failed to connect signals: {e}")
	
	def on_item_clicked(self, item: QTreeWidgetItem, column: int = 0):
		"""FIXED: Lazy-load pile contents progressively to prevent stack overflow."""
		if self._is_destroyed or not item or self._in_item_click:
			return
		
		# Only populate top-level items (piles) that don't have children yet.
		if item.childCount() > 0 or item.parent() is not None:
			return
		
		# Set guard flag immediately. It will be cleared in the async callback or on error.
		self._in_item_click = True
		try:
			pile_data = item.data(0, Qt.ItemDataRole.UserRole)
			if not pile_data or not hasattr(pile_data, 'cards'):
				self._in_item_click = False
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
				self._in_item_click = False
				return
			
			# Provide user feedback and disable updates
			self.tree.setUpdatesEnabled(False)
			item.setText(1, f"{item.text(1)} (Loading...)")
			
			def on_population_finished():
				if self._is_destroyed:
					self._in_item_click = False
					return
				try:
					# Restore original text from stored data and expand
					pile_node_data = item.data(0, Qt.ItemDataRole.UserRole)
					if pile_node_data:
						original_count = pile_node_data.total_count if show_sorted else pile_node_data.unsorted_count
						item.setText(1, str(int(original_count)))
					item.setExpanded(True)
				finally:
					if not self._is_destroyed: self.tree.setUpdatesEnabled(True)
					self._in_item_click = False  # Clear guard flag
			
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
				
				# Use timer to defer refresh and prevent recursion
				QTimer.singleShot(100, self._safe_regenerate_plan)
		
		except Exception as e:
			print(f"Error in on_mark_piles_sorted: {e}")
	
	def _safe_regenerate_plan(self):
		"""Safe plan regeneration with guard"""
		if not self._is_destroyed and not self._is_generating:
			self.generate_plan()
	
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
			if self.parent_tab.group_low_count_check.isChecked():
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
		"""Clean up any running workers"""
		if self._is_destroyed:
			return
		
		self._is_destroyed = True
		cleanup_worker_thread(self.import_thread, self.import_worker)
		cleanup_worker_thread(self.image_thread, self.image_worker)
	
	def __del__(self):
		"""Ensure proper cleanup of workers"""
		self.cleanup_workers()
	
	def closeEvent(self, event):
		"""Handle widget close event"""
		self.cleanup_workers()
		super().closeEvent(event)
	
	def handle_item_click(self, item: QTreeWidgetItem, next_level: int):
		"""FIXED: Simple item click handling with drill-down"""
		if self._is_destroyed or not item:
			return
		
		try:
			print(f"DEBUG: handle_item_click called for item '{item.text(0)}', next_level: {next_level}")
			
			# Always update preview first
			self.update_card_preview(item)
			
			# Check if we should drill down (avoid for individual cards)
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			current_level = next_level - 1
			
			print(f"DEBUG: sort_order: {self.sort_order}, current_level: {current_level}")
			
			if 0 <= current_level < len(self.sort_order) and self.sort_order[current_level] == "Name":
				# This is a card item, just update preview
				print("DEBUG: This is a card item, not drilling down")
				return
			
			# This is a group item, drill down
			print("DEBUG: This is a group item, drilling down...")
			self.drill_down(item, next_level)
		
		except Exception as e:
			print(f"Error in handle_item_click: {e}")
	
	def drill_down(self, item: QTreeWidgetItem, next_level: int):
		"""Handle drill down with crash prevention"""
		if self._is_destroyed or not item or self._is_navigating:
			return
		
		try:
			self._is_navigating = True
			
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			
			if next_level > len(self.sort_order):
				self.show_status_message("Cannot drill down further - no more sort criteria available.", 3000)
				return
			
			# Special handling for Set → First Letter transition
			current_level_index = next_level - 1
			if 0 <= current_level_index < len(self.sort_order):
				current_criterion = self.sort_order[current_level_index]
				next_criterion = self.sort_order[next_level] if next_level < len(self.sort_order) else None
				
				if current_criterion == "Set" and next_criterion == "First Letter":
					cards_in_set = self._get_cards_from_item(item)
					if not cards_in_set:
						self.show_status_message("No cards found in selected set.", 2000)
						return
					
					self.navigate_to_level(current_level_index)
					breadcrumb_text = item.text(0).split(': ')[-1]
					self.add_breadcrumb(f"{breadcrumb_text} (Letter Sort)", next_level)
					self.create_set_sorter_view(cards_in_set, breadcrumb_text)
					return
			
			# Default drill-down behavior
			cards_in_group = self._get_cards_from_item(item)
			if not cards_in_group:
				self.show_status_message("No cards found in selected group.", 2000)
				return
			
			self.navigate_to_level(next_level - 1)
			self.add_breadcrumb(item.text(0), next_level)
			self.create_new_view(cards_in_group, next_level)
		
		except Exception as e:
			print(f"Error in drill_down: {e}")
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
			QTimer.singleShot(100, self._refresh_current_view)
	
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
				self.handle_item_click(item, level + 1)
			
			tree.itemClicked.connect(debug_item_clicked)
			print("DEBUG: itemClicked signal connected")
			
			tree.itemDoubleClicked.connect(lambda item: self.mark_item_as_sorted(item))
			print("DEBUG: itemDoubleClicked signal connected")
			
			tree.drillDownRequested.connect(lambda item: self.drill_down(item, level + 1))
			print("DEBUG: drillDownRequested signal connected")
			
			tree.navigateUpRequested.connect(lambda: self.navigate_and_refresh(level - 1) if level > 0 else None)
			print("DEBUG: navigateUpRequested signal connected")
			
			tree.currentItemChanged.connect(self.update_button_visibility)
			print("DEBUG: currentItemChanged signal connected to update_button_visibility")
			
			tree.currentItemChanged.connect(self.on_tree_selection_changed)
			print("DEBUG: currentItemChanged signal connected to on_tree_selection_changed")
			
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
		"""Show status message"""
		self.status_label.setText(message)
		QTimer.singleShot(timeout, lambda: self.status_label.setText(""))
	
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
		
		self.project_modified.emit()
		QTimer.singleShot(50, self._refresh_current_view)
	
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
