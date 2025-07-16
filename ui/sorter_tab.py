# ui/sorter_tab.py

import collections
import csv
import json
import pathlib
import string
import zipfile
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
from ui.custom_widgets import NavigableTreeWidget, SortableTreeWidgetItem
from workers.threads import CsvImportWorker, ImageFetchWorker, cleanup_worker_thread


# Fixed SetSorterView class - place this in sorter_tab.py

class SetSorterView(QWidget):
	"""A dedicated widget for the 'Sort This Set' view with stack overflow prevention."""
	
	def __init__(self, cards_to_sort: List[Card], set_name: str, parent_tab: 'ManaBoxSorterTab'):
		super().__init__()
		self.cards_to_sort = cards_to_sort
		self.set_name = set_name
		self.parent_tab = parent_tab
		
		# FIXED: Add recursion guards
		self._is_generating = False
		self._is_destroyed = False
		self._in_item_click = False
		self._in_mark_sorted = False
		self._all_display_nodes_for_chart = []  # To hold nodes for the chart
		
		self.canvas = None
		self.ax = None
		self._setup_ui()
		
		# FIXED: Use a longer delay to ensure UI is fully initialized
		QTimer.singleShot(200, self._safe_generate_plan)
	
	def __del__(self):
		"""Ensure proper cleanup"""
		self.cleanup()
	
	def cleanup(self):
		"""Clean up resources"""
		if self._is_destroyed:
			return
		self._is_destroyed = True

		# Block signals on the child tree to prevent events during shutdown.
		# Qt's ownership model will handle disconnecting signals when the widget is deleted.
		if hasattr(self, 'tree') and self.tree:
			self.tree.blockSignals(True)

		# Clean up matplotlib canvas
		if hasattr(self, 'canvas') and self.canvas:
			self.canvas.deleteLater()
		self.canvas = None
		self.ax = None
	
	def closeEvent(self, event):
		"""Handle widget close event"""
		self.cleanup()
		super().closeEvent(event)
	
	def _safe_generate_plan(self):
		"""FIXED: Safe wrapper for generate_plan with recursion guard"""
		if not self._is_destroyed and not self._is_generating:
			try:
				self.generate_plan()
			except Exception as e:
				print(f"Error in generate_plan: {e}")
	
	def _setup_ui(self):
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		splitter = QSplitter(Qt.Orientation.Horizontal)
		layout.addWidget(splitter)
		
		chart_group = QGroupBox(f"Optimal Sort Plan for {self.set_name}")
		chart_layout = QVBoxLayout(chart_group)
		
		try:
			# FIXED: Better matplotlib initialization with error handling
			from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
			from matplotlib.figure import Figure
			import matplotlib
			matplotlib.use('QtAgg')  # Ensure correct backend
			
			self.canvas = FigureCanvas(Figure(facecolor='#2b2b2b'))
			self.ax = self.canvas.figure.subplots()
			self.ax.tick_params(colors='white')
			for spine in self.ax.spines.values():
				spine.set_color('white')
			chart_layout.addWidget(self.canvas)
		
		except Exception as e:
			# FIXED: Fallback if matplotlib fails
			error_label = QLabel(f"Chart unavailable: {str(e)}")
			error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
			error_label.setStyleSheet("color: orange; padding: 20px;")
			chart_layout.addWidget(error_label)
			self.canvas = None
			self.ax = None
		
		splitter.addWidget(chart_group)
		
		# Rest of the UI setup...
		right_panel = QWidget()
		right_layout = QVBoxLayout(right_panel)
		piles_group = QGroupBox("Sorting Piles")
		piles_layout = QVBoxLayout(piles_group)
		self.tree = NavigableTreeWidget()
		self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
		self.tree.setHeaderLabels(["Pile", "Count"])
		self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
		self.tree.setSortingEnabled(True)
		self.tree.setToolTip("Single-click a pile to see its cards. Double-click to mark it as sorted.")
		piles_layout.addWidget(self.tree)
		right_layout.addWidget(piles_group)
		controls_layout = QHBoxLayout()
		mark_pile_button = QPushButton("Mark Selected as Sorted")
		mark_pile_button.setToolTip("Mark the selected pile(s) as completely sorted (Shortcut: Space)")
		controls_layout.addWidget(mark_pile_button)
		right_layout.addLayout(controls_layout)
		splitter.addWidget(right_panel)
		splitter.setSizes([600, 400])
		
		# FIXED: Connect signals more safely with recursion guards
		try:
			self.tree.markAsortedRequested.connect(self.on_mark_piles_sorted)
			mark_pile_button.clicked.connect(lambda: self.on_mark_piles_sorted(self.tree.selectedItems()))
			self.tree.itemDoubleClicked.connect(lambda item: self.on_mark_piles_sorted([item]))
			self.tree.itemClicked.connect(self.on_item_clicked)
		except Exception as e:
			print(f"Warning: Failed to connect signals in SetSorterView: {e}")
	
	def on_item_clicked(self, item: QTreeWidgetItem, column: int):
		"""FIXED: Stack overflow prevention in item click handler"""
		if self._is_destroyed or not item or self._in_item_click:
			return
		
		try:
			self._in_item_click = True
			
			# Lazily populate pile with cards when clicked
			if item.childCount() > 0 or item.parent() is not None:
				return
			
			pile_data = item.data(0, Qt.ItemDataRole.UserRole)
			if not pile_data or not hasattr(pile_data, 'cards'):
				return
			
			cards_in_pile = sorted(pile_data.cards, key=lambda c: c.name or "")
			show_sorted = self.parent_tab.show_sorted_check.isChecked()
			
			# FIXED: Remove batch processing and processEvents() to prevent recursion
			# Process all cards at once without calling processEvents
			for card in cards_in_pile:
				if self._is_destroyed:
					return
				
				unsorted_count = card.quantity - card.sorted_count
				if not show_sorted and unsorted_count == 0:
					continue
				
				display_count = card.quantity if show_sorted else unsorted_count
				child_item = SortableTreeWidgetItem(item, [card.name, str(display_count)])
				child_item.setData(0, Qt.ItemDataRole.UserRole, [card])
				
				if show_sorted and unsorted_count <= 0:
					font = child_item.font(0)
					font.setItalic(True)
					child_item.setFont(0, font)
					child_item.setFont(1, font)
					child_item.setForeground(0, QColor(Qt.GlobalColor.gray))
					child_item.setForeground(1, QColor(Qt.GlobalColor.gray))
			
			item.setExpanded(True)
		
		except Exception as e:
			print(f"Error in on_item_clicked: {e}")
		finally:
			self._in_item_click = False
	
	def on_mark_piles_sorted(self, items_to_mark=None):
		"""FIXED: Stack overflow prevention in pile marking"""
		if self._is_destroyed or self._in_mark_sorted:
			return
		
		try:
			self._in_mark_sorted = True
			
			selected_items = items_to_mark or self.tree.selectedItems()
			if not selected_items:
				QMessageBox.warning(self, "No Selection", "Please select one or more piles from the list.")
				return
			
			# If only one item is selected (from double-click), toggle its state. Otherwise, mark all as sorted.
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
						# Unsort the pile
						card.sorted_count = 0
					else:
						# Sort the pile
						card.sorted_count = card.quantity
			
			if not self._is_destroyed:
				self.parent_tab.show_status_message(f"Updated sorted status for {len(selected_items)} pile(s).")
				self.parent_tab.project_modified.emit()
				
				# FIXED: Use longer delay to prevent recursion
				QTimer.singleShot(100, self._safe_generate_plan)
		
		except Exception as e:
			print(f"Error in on_mark_piles_sorted: {e}")
		finally:
			self._in_mark_sorted = False
	
	def generate_plan(self):
		"""
		FIXED: Generate sorting plan with progressive loading to prevent stack overflows.
		"""
		if self._is_generating or self._is_destroyed:
			return
		
		try:
			self._is_generating = True

			# --- State Preservation (from the old tree, before clearing) ---
			expanded_items_text = set()
			selected_items_text = set()
			current_item_text = None
			scroll_position = 0
			try:
				iterator = QTreeWidgetItemIterator(self.tree)
				while iterator.value():
					item = iterator.value()
					if item.isExpanded():
						expanded_items_text.add(item.text(0))
					if item.isSelected():
						selected_items_text.add(item.text(0))
					iterator += 1
				if self.tree.currentItem():
					current_item_text = self.tree.currentItem().text(0)
				scroll_position = self.tree.verticalScrollBar().value()
			except Exception:
				pass

			# --- Data Processing (no UI changes here) ---
			show_sorted = self.parent_tab.show_sorted_check.isChecked()
			piles = collections.defaultdict(lambda: {'cards': [], 'total': 0, 'unsorted': 0})

			if self.parent_tab.group_low_count_check.isChecked():
				try:
					threshold = int(self.parent_tab.group_threshold_edit.text())
				except ValueError:
					threshold = 20
				raw_letter_totals = collections.defaultdict(int)
				for card in self.cards_to_sort:
					if card.name and card.name != 'N/A':
						raw_letter_totals[card.name[0].upper()] += card.quantity
				mapping = {}
				buf, tot = "", 0
				def flush():
					nonlocal buf, tot
					if buf:
						for ch in buf: mapping[ch] = buf
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
					if card.name and card.name != 'N/A':
						first_letter = card.name[0].upper()
						pile_key = mapping.get(first_letter, first_letter)
						piles[pile_key]['cards'].append(card)
						piles[pile_key]['total'] += card.quantity
						piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)
			else:
				for card in self.cards_to_sort:
					if card.name and card.name != 'N/A':
						pile_key = card.name[0].upper()
						piles[pile_key]['cards'].append(card)
						piles[pile_key]['total'] += card.quantity
						piles[pile_key]['unsorted'] += (card.quantity - card.sorted_count)

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
				display_nodes = sorted([n for n in nodes if n.unsorted_count > 0], key=lambda x: x.unsorted_count, reverse=True)
				chart_title = f"Unsorted Cards in {self.set_name}"
				tree_header = "Unsorted Count"

			# --- UI Update Kick-off ---
			self.tree.setUpdatesEnabled(False)
			self.tree.clear()
			self.tree.setHeaderLabels(["Pile", tree_header])

			# Store nodes for the chart, which is drawn at the very end.
			self._all_display_nodes_for_chart = display_nodes

			# Kick off progressive loading. The _is_generating flag will be reset inside this async flow.
			QTimer.singleShot(0, lambda: self._populate_tree_progressively(
				list(display_nodes),  # Pass a copy
				expanded_items_text, selected_items_text, current_item_text,
				scroll_position, chart_title, show_sorted
			))

		except Exception as e:
			print(f"Error in generate_plan setup: {e}")
			# Ensure we reset state on error
			if not self._is_destroyed:
				try:
					self.tree.setUpdatesEnabled(True)
				except:
					pass
			self._is_generating = False

	def _populate_tree_progressively(self, nodes_to_add: List[SortGroup],
	                                 expanded_items_text, selected_items_text, current_item_text,
	                                 scroll_position, chart_title, show_sorted, chunk_size=50):
		"""Adds items to the tree in chunks to prevent blocking the UI and causing stack overflows."""
		if self._is_destroyed:
			self._is_generating = False  # Ensure flag is reset
			try:
				if self.tree: self.tree.setUpdatesEnabled(True)
			except:
				pass
			return

		try:
			# Process one chunk
			chunk = nodes_to_add[:chunk_size]
			remaining_nodes = nodes_to_add[chunk_size:]

			show_sorted_flag = self.parent_tab.show_sorted_check.isChecked()

			for node in chunk:
				display_count = node.total_count if show_sorted_flag else node.unsorted_count
				tree_item = SortableTreeWidgetItem(self.tree.invisibleRootItem(), [node.group_name, str(display_count)])
				tree_item.setData(0, Qt.ItemDataRole.UserRole, node)

				if show_sorted_flag and node.unsorted_count <= 0:
					font = tree_item.font(0)
					font.setItalic(True)
					tree_item.setFont(0, font)
					tree_item.setFont(1, font)
					tree_item.setForeground(0, QColor(Qt.GlobalColor.gray))
					tree_item.setForeground(1, QColor(Qt.GlobalColor.gray))

			if remaining_nodes:
				# Schedule the next chunk
				QTimer.singleShot(0, lambda: self._populate_tree_progressively(
					remaining_nodes, expanded_items_text, selected_items_text, current_item_text,
					scroll_position, chart_title, show_sorted, chunk_size
				))
			else:
				# Finished populating, now do the final steps
				self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
				if not self._is_destroyed:
					self.tree.setUpdatesEnabled(True)

				# Restore state and draw chart
				self._restore_state_and_draw_chart(
					expanded_items_text, selected_items_text, current_item_text,
					scroll_position, self._all_display_nodes_for_chart, chart_title, show_sorted
				)
				# This is the true end of the generation process
				self._is_generating = False
		except Exception as e:
			print(f"Error in progressive population: {e}")
			self._is_generating = False
			if not self._is_destroyed:
				try:
					if self.tree: self.tree.setUpdatesEnabled(True)
				except:
					pass

	def _restore_state_and_draw_chart(self, expanded_items_text, selected_items_text, current_item_text, scroll_position,
	                                  display_nodes, chart_title, show_sorted):
		"""Restores tree state and draws the chart asynchronously to prevent UI lockup."""
		if self._is_destroyed:
			return

		# Step 1: Find all items that need to be re-expanded, but don't do it yet.
		items_to_expand = []
		iterator = QTreeWidgetItemIterator(self.tree)
		while iterator.value():
			item = iterator.value()
			if item.text(0) in expanded_items_text:
				items_to_expand.append(item)
			iterator += 1

		# Step 2: Kick off the progressive re-expansion.
		# Pass along all the state data needed for the final steps.
		self._progressively_re_expand(items_to_expand, selected_items_text, current_item_text, scroll_position,
		                              display_nodes, chart_title, show_sorted)

	def _progressively_re_expand(self, items_to_expand: list, selected_items_text, current_item_text, scroll_position,
	                             display_nodes, chart_title, show_sorted):
		"""Expands items one-by-one with a timer to prevent overwhelming the event loop."""
		if self._is_destroyed:
			return

		# If all items have been expanded, proceed to the final steps.
		if not items_to_expand:
			self._finish_restoration_and_draw_chart(selected_items_text, current_item_text, scroll_position,
			                                         display_nodes, chart_title, show_sorted)
			return

		# Pop one item from the list and populate it.
		item_to_process = items_to_expand.pop(0)
		self._populate_item_safely(item_to_process)

		# Schedule the next item to be processed.
		QTimer.singleShot(10, lambda: self._progressively_re_expand(
			items_to_expand, selected_items_text, current_item_text, scroll_position,
			display_nodes, chart_title, show_sorted
		))

	def _finish_restoration_and_draw_chart(self, selected_items_text, current_item_text, scroll_position,
	                                       display_nodes, chart_title, show_sorted):
		"""The final step: restore selection/scroll and draw the chart."""
		# Use another short delay before restoring selection and scroll to ensure expansion is processed
		def final_restore():
			if self._is_destroyed:
				return

			# Restore selection and current item
			iterator = QTreeWidgetItemIterator(self.tree)
			while iterator.value():
				item = iterator.value()
				item_text = item.text(0)
				if item_text in selected_items_text:
					item.setSelected(True)
				if item_text == current_item_text:
					self.tree.setCurrentItem(item)
				iterator += 1

			# Restore scroll position
			self.tree.verticalScrollBar().setValue(scroll_position)

		QTimer.singleShot(50, final_restore)

		# Draw chart
		if self.ax and self.canvas:
			try:
				self.ax.clear()
				if not display_nodes:
					self.ax.text(0.5, 0.5, "Set Complete! All cards sorted.", ha='center', va='center', color='white',
					             fontsize=16)
				else:
					chart_labels = [node.group_name for node in display_nodes]
					chart_counts = [node.total_count if show_sorted else node.unsorted_count for node in display_nodes]
					colors = ['#555555' if node.unsorted_count <= 0 else '#007acc' for node in
					          display_nodes] if show_sorted else '#007acc'
					
					bars = self.ax.bar(chart_labels, chart_counts, color=colors, zorder=3)
					for bar, count in zip(bars, chart_counts):
						if (height := bar.get_height()) > 0:
							self.ax.text(bar.get_x() + bar.get_width() / 2., height, f'{int(count)}', ha='center',
							             va='bottom', color='white', fontsize=8)
					
					self.ax.set_title(chart_title, color='white')
					self.ax.set_ylabel("Card Count", color='white')
					self.ax.tick_params(axis='x', colors='white', rotation=45 if len(chart_labels) > 10 else 0)
					self.ax.tick_params(axis='y', colors='white')
					[spine.set_color('white') for spine in self.ax.spines.values()]
					self.ax.grid(axis='y', color='#444444', linestyle='--', linewidth=0.5, zorder=0)

				self.canvas.figure.tight_layout()
				self.canvas.draw()
			except Exception as e:
				print(f"Error drawing chart: {e}")
	
	def _populate_item_safely(self, item):
		"""FIXED: Safely populate an item without triggering recursive events"""
		if self._is_destroyed or not item or self._in_item_click:
			return
		
		try:
			# Call the item click handler safely
			self.on_item_clicked(item, 0)
		except Exception as e:
			print(f"Error in _populate_item_safely: {e}")


class ManaBoxSorterTab(QWidget):
	# Signals for communication with main window
	collection_loaded = Signal()
	progress_updated = Signal(int)
	project_modified = Signal()
	operation_started = Signal(str, int)  # message, max_value
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
		self.splitter_sizes = [700, 350]
		
		# FIXED: Add recursion protection flags
		self._is_refreshing = False
		self._is_navigating = False
		self._is_destroyed = False
		self._in_refresh = False
		self._in_drill_down = False
		self._in_create_view = False
		self._in_handle_click = False
		self._in_navigate = False
		self._in_nav_refresh = False
		self._in_toggle = False
		
		main_layout = QVBoxLayout(self)
		# Defer heavy UI creation to prevent startup crash.
		QTimer.singleShot(0, self._setup_ui)
	
	def __del__(self):
		"""Ensure proper cleanup of workers"""
		self.cleanup_workers()
	
	def cleanup_workers(self):
		"""Clean up any running workers"""
		self._is_destroyed = True
		cleanup_worker_thread(self.import_thread, self.import_worker)
		cleanup_worker_thread(self.image_thread, self.image_worker)
	
	def closeEvent(self, event):
		"""Handle widget close event"""
		self.cleanup_workers()  # Ensure workers are stopped
		super().closeEvent(event)
	
	def _setup_ui(self):
		"""Creates and adds the main UI sections to the layout."""
		self._create_import_section(self.layout())
		self._create_options_section(self.layout())
		self._create_run_section(self.layout())
		self._create_results_section(self.layout())
	
	def _create_import_section(self, layout: QVBoxLayout):
		group = QGroupBox("1. Import Collection")
		layout.addWidget(group)
		group_layout = QVBoxLayout(group)
		
		button_layout = QHBoxLayout()
		self.import_button = QPushButton("Import ManaBox CSV")
		self.import_button.setObjectName("AccentButton")
		self.import_button.setToolTip("Import a ManaBox CSV export file containing your collection (Shortcut: Ctrl+O)")
		self.import_button.clicked.connect(self.import_csv)
		
		self.reset_progress_button = QPushButton("Reset Progress")
		self.reset_progress_button.setToolTip("Resets the sorting progress for all cards in the current collection.")
		self.reset_progress_button.clicked.connect(self.reset_sort_progress)
		
		button_layout.addWidget(self.import_button)
		button_layout.addStretch()
		button_layout.addWidget(self.reset_progress_button)
		
		self.file_label = QLabel("No file loaded.")
		self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.file_label.setToolTip("Shows the currently loaded collection file and status")
		self.progress_bar = QProgressBar()
		self.progress_bar.setVisible(False)
		self.progress_bar.setToolTip("Shows progress of card data fetching from Scryfall")
		
		group_layout.addLayout(button_layout)
		group_layout.addWidget(self.file_label)
		group_layout.addWidget(self.progress_bar)
	
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
		self.available_list = QListWidget()
		self.available_list.addItems(
				["Set", "Color Identity", "Rarity", "Type Line", "First Letter", "Name", "Condition",
				 "Commander Staple"])
		self.available_list.setToolTip("Available sorting criteria. Double-click an item to add it to the sort order.")
		self.available_list.itemDoubleClicked.connect(self.add_criterion)
		
		self.selected_list = QListWidget()
		self.selected_list.setToolTip(
				"Your sorting hierarchy. Double-click an item to remove it. Drag and drop to reorder.")
		self.selected_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
		self.selected_list.itemDoubleClicked.connect(self.remove_criterion)
		
		grid.addWidget(self.available_list, 0, 0)
		grid.addWidget(self.selected_list, 0, 1)
		grid.setColumnStretch(0, 1)
		grid.setColumnStretch(1, 1)
		
		set_plan_group = QGroupBox("Set Sorting Plan")
		set_plan_group.setToolTip("Options for optimizing letter-based sorting within sets")
		options_layout.addWidget(set_plan_group, 1)
		set_plan_layout = QVBoxLayout(set_plan_group)
		self.group_low_count_check = QCheckBox("Group low-count letters into piles")
		self.group_low_count_check.setChecked(True)
		self.group_low_count_check.setToolTip(
				"Combine letters with few cards into larger piles for more efficient sorting")
		set_plan_layout.addWidget(self.group_low_count_check)
		threshold_layout = QHBoxLayout()
		threshold_layout.addWidget(QLabel("Min pile total:"))
		self.group_threshold_edit = QLineEdit("20")
		self.group_threshold_edit.setToolTip("Minimum number of cards per pile when grouping letters together")
		threshold_layout.addWidget(self.group_threshold_edit)
		set_plan_layout.addLayout(threshold_layout)
		set_plan_layout.addStretch()
	
	def _create_run_section(self, layout: QVBoxLayout):
		group = QGroupBox("3. Generate Plan")
		layout.addWidget(group)
		h_layout = QHBoxLayout(group)
		h_layout.addStretch()
		self.run_button = QPushButton("Generate Sorting Plan")
		self.run_button.setToolTip("Create a visual sorting plan based on your criteria (Shortcut: Ctrl+G)")
		self.run_button.clicked.connect(self.start_new_plan_generation)
		h_layout.addWidget(self.run_button)
		h_layout.addStretch()
	
	def _create_results_section(self, layout: QVBoxLayout):
		group = QGroupBox("4. Sorting Plan")
		layout.addWidget(group)
		results_layout = QVBoxLayout(group)
		top_bar_layout = QHBoxLayout()
		self.breadcrumb_layout = QHBoxLayout()
		self.breadcrumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
		top_bar_layout.addLayout(self.breadcrumb_layout, 1)
		self.show_sorted_check = QCheckBox("Show Sorted Groups")
		self.show_sorted_check.setToolTip("Include already-sorted cards in the display")
		self.show_sorted_check.stateChanged.connect(self.on_show_sorted_toggled)
		top_bar_layout.addWidget(self.show_sorted_check)
		top_bar_layout.addStretch()
		self.mark_sorted_button = QPushButton("Mark Group as Sorted")
		self.mark_sorted_button.setToolTip("Mark all cards in the selected group(s) as sorted (Shortcut: Space)")
		self.mark_sorted_button.clicked.connect(self.on_mark_group_button_clicked)
		self.mark_sorted_button.setVisible(False)
		top_bar_layout.addWidget(self.mark_sorted_button)
		self.export_button = QPushButton("Export View")
		self.export_button.setToolTip("Export the current view to a CSV file (Shortcut: Ctrl+E)")
		self.export_button.clicked.connect(self.export_current_view)
		self.export_button.setVisible(False)
		top_bar_layout.addWidget(self.export_button)
		results_layout.addLayout(top_bar_layout)
		self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
		left_panel = QWidget()
		left_layout = QVBoxLayout(left_panel)
		self.filter_edit = QLineEdit()
		self.filter_edit.setPlaceholderText("Filter current view...")
		self.filter_edit.setToolTip("Type to filter the current view by group name")
		self.filter_edit.textChanged.connect(self.filter_current_view)
		self.filter_edit.setVisible(False)
		self.results_stack = QStackedWidget()
		left_layout.addWidget(self.filter_edit)
		left_layout.addWidget(self.results_stack)
		self.preview_panel = QWidget()
		right_layout = QVBoxLayout(self.preview_panel)
		self.card_image_label = QLabel("Select an individual card to see its image.")
		self.card_image_label.setObjectName("CardImageLabel")
		self.card_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.card_image_label.setMinimumSize(220, 308)
		self.card_image_label.setToolTip("Card images appear here when you select individual cards")
		self.card_details_label = QLabel()
		self.card_details_label.setAlignment(Qt.AlignmentFlag.AlignTop)
		self.card_details_label.setWordWrap(True)
		self.card_details_label.setToolTip("Detailed card information appears here")
		right_layout.addWidget(self.card_image_label)
		right_layout.addWidget(self.card_details_label)
		right_layout.addStretch()
		self.main_splitter.addWidget(left_panel)
		self.main_splitter.addWidget(self.preview_panel)
		self.main_splitter.setSizes(self.splitter_sizes)
		results_layout.addWidget(self.main_splitter)
		self.status_label = QLabel()
		self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
		results_layout.addWidget(self.status_label)
		layout.setStretchFactor(group, 1)
	
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
		
		# FIXED: Clean up workers first
		self.cleanup_workers()
		
		# Reset internal data
		self.all_cards = []
		self.last_csv_path = None
		self.progress_to_load = None
		
		# Clear UI elements with better error handling
		self.file_label.setText("No file loaded.")
		self.clear_layout(self.breadcrumb_layout)
		
		# FIXED: Safer widget cleanup
		self._safe_clear_stack()
		
		self.reset_preview_pane()
		self.filter_edit.clear()
		self.filter_edit.setVisible(False)
		self.preview_panel.setVisible(False)
		self.update_button_visibility()
		
		self.show_status_message("Project cleared. Import a new CSV to begin.", 5000)
		self.project_modified.emit()
	
	def _safe_clear_stack(self):
		"""FIXED: Safely clear the widget stack to prevent crashes"""
		try:
			# Now safely remove and delete widgets
			while self.results_stack.count() > 0:
				widget = self.results_stack.widget(0)
				self.results_stack.removeWidget(widget)
				if widget:
					# For SetSorterView, call cleanup method
					if hasattr(widget, 'cleanup'):
						widget.cleanup()
					widget.deleteLater()
			
			# Process events to ensure deleteLater() is processed
			QApplication.processEvents()
		
		except Exception as e:
			# If clearing fails, at least log it and continue
			print(f"Error clearing stack: {e}")
	
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
			
			# Refresh the current view to reflect the changes
			self._refresh_current_view()
	
	def on_show_sorted_toggled(self):
		"""FIXED: Handle show sorted toggle with recursion protection"""
		if getattr(self, '_in_toggle', False):
			return
		
		try:
			self._in_toggle = True
			# Use timer to prevent immediate recursion
			QTimer.singleShot(50, self._refresh_current_view)
		finally:
			self._in_toggle = False
	
	def import_csv(self, filepath=None):
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
			
			# Save the directory of the chosen file for next time
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
		
		# FIXED: Clean up any existing worker
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
	
	def update_progress(self, value, total):
		if self.progress_bar.maximum() != total:
			self.progress_bar.setRange(0, total)
			self.operation_started.emit(f"Fetching card data", total)
		self.progress_bar.setValue(value)
		self.file_label.setText(f"Fetching card data: {value}/{total}")
		self.progress_updated.emit(value)
	
	def on_import_finished(self, cards: List[Card]):
		try:
			# The worker now returns a clean, aggregated list of cards.
			self.all_cards = cards
			
			# Apply any pending progress data from a loaded project
			if self.progress_to_load:
				# This operation should be fast enough on the main thread
				# without needing to call processEvents().
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
			
			self.start_new_plan_generation()
			self.project_modified.emit()
		
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
			# FIXED: Always clean up worker
			self.import_thread = None
			self.import_worker = None
	
	def on_import_error(self, error_message: str):
		self.is_loading = False
		self.file_label.setText("Import failed - see details below")
		self.progress_bar.setVisible(False)
		self.import_button.setEnabled(True)
		self.run_button.setEnabled(True)
		self.operation_finished.emit()
		# Worker and thread will be cleaned up by deleteLater signals
		self.import_thread = None
		self.import_worker = None
		QMessageBox.critical(self, "Import Error", error_message)
	
	def add_criterion(self, item: QListWidgetItem):
		self.selected_list.addItem(self.available_list.takeItem(self.available_list.row(item)))
		self.project_modified.emit()
	
	def remove_criterion(self, item: QListWidgetItem):
		self.available_list.addItem(self.selected_list.takeItem(self.selected_list.row(item)))
		self.project_modified.emit()
	
	def start_new_plan_generation(self):
		"""Resets the entire view and generates a new plan from the top level."""
		if not self.all_cards:
			QMessageBox.information(self, "No Collection", "Please import a collection first.")
			return
		
		try:
			# Perform a full reset of the navigation state
			self.clear_layout(self.breadcrumb_layout)
			self._safe_clear_stack()  # FIXED: Use safer clearing method
			self.reset_preview_pane()
			self.add_breadcrumb("Home", 0)
			
			# Create the first level view
			self.create_new_view(self.all_cards, 0)
			self.update_button_visibility()
			self.filter_edit.setVisible(True)
		
		except Exception as e:
			self.show_status_message(f"Error starting new plan: {e}", 5000)
			self._force_complete_reset()
	
	def _refresh_current_view(self):
		"""
		FIXED: Non-destructively refreshes the content of the current view with stack overflow prevention.
		"""
		if (self._is_refreshing or self.is_loading or self._is_destroyed or
				getattr(self, '_in_refresh', False)):
			return
		
		try:
			self._in_refresh = True
			self._is_refreshing = True
			
			current_widget = self.results_stack.currentWidget()
			if isinstance(current_widget, SetSorterView):
				# Use timer to avoid recursion - longer delay for safety
				QTimer.singleShot(150, current_widget._safe_generate_plan)
				return
			
			if not isinstance(current_widget, NavigableTreeWidget):
				# This can happen if the view is in a weird state.
				# The best recovery is to start a fresh plan.
				if self.all_cards:
					QTimer.singleShot(200, self.start_new_plan_generation)
				return
			
			# --- State Preservation ---
			expanded_items_text = set()
			selected_items_text = set()
			current_item_text = None
			scroll_position = 0
			
			try:
				# FIXED: Safer state preservation without triggering events
				for i in range(current_widget.topLevelItemCount()):
					item = current_widget.topLevelItem(i)
					if item and item.isExpanded():
						expanded_items_text.add(item.text(0))
				
				for item in current_widget.selectedItems():
					selected_items_text.add(item.text(0))
				
				if current_widget.currentItem():
					current_item_text = current_widget.currentItem().text(0)
				
				scroll_position = current_widget.verticalScrollBar().value()
			except:
				pass
			# --- End State Preservation ---
			
			current_widget.setUpdatesEnabled(False)
			try:
				level = self.results_stack.currentIndex()
				cards_to_process = getattr(current_widget, 'cards_for_view', self.all_cards)
				
				# Update sort order and get current criterion
				self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
				criterion = self.sort_order[level] if 0 <= level < len(self.sort_order) else None
				
				nodes = self._generate_level_breakdown(cards_to_process, criterion)
				
				current_widget.clear()
				self._populate_tree_safe(current_widget.invisibleRootItem(), nodes)
				
				show_sorted = self.show_sorted_check.isChecked()
				header_label = "Total Count" if show_sorted else "Unsorted Count"
				current_widget.setHeaderLabels(['Group', header_label])
				
				# --- State Restoration ---
				for i in range(current_widget.topLevelItemCount()):
					item = current_widget.topLevelItem(i)
					if item:
						item_text = item.text(0)
						if item_text in expanded_items_text:
							item.setExpanded(True)
						if item_text in selected_items_text:
							item.setSelected(True)
						if item_text == current_item_text:
							current_widget.setCurrentItem(item)
				
				# FIXED: Use timer for scroll position to avoid immediate event triggers
				QTimer.singleShot(50, lambda: current_widget.verticalScrollBar().setValue(scroll_position))
			# --- End State Restoration ---
			
			finally:
				current_widget.setUpdatesEnabled(True)
		
		except Exception as e:
			print(f"Error in _refresh_current_view: {e}")
		
		finally:
			self._is_refreshing = False
			self._in_refresh = False
			self.update_button_visibility()
			self._update_view_layout()
	
	def generate_plan(self):
		"""This method now acts as a router to the correct plan generation/refresh function."""
		if self.results_stack.count() == 0 and self.all_cards:
			self.start_new_plan_generation()
			return
		
		current_widget = self.results_stack.currentWidget()
		if isinstance(current_widget, SetSorterView):
			# This is a special view that handles its own state. Delegate to it.
			current_widget.generate_plan()
			return
		
		if not self.all_cards:
			QMessageBox.information(self, "No Collection", "Please import a collection first.")
			return
		
		try:
			# FIXED: Always refresh sort order and validate everything upfront
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			
			# FIXED: Get current level with bounds checking
			current_level = max(0, min(self.results_stack.currentIndex(), len(self.sort_order)))
			
			# FIXED: If no sort criteria, force level 0 and show all cards
			if not self.sort_order and current_level > 0:
				self.navigate_to_level(0)
				return
			if not self.sort_order:
				current_level = 0
			
			# FIXED: If current level exceeds sort criteria, reset to max valid level
			max_valid_level = len(self.sort_order) - 1 if self.sort_order else 0
			if current_level > max_valid_level:
				target_level = max(0, max_valid_level)
				self.navigate_to_level(target_level)
				QTimer.singleShot(100, self._refresh_current_view)  # Retry after navigation
				return
			
			level = current_level
			
			# Large collection warning
			if len(self.all_cards) > 25000:
				reply = QMessageBox.question(
						self,
						"Large Collection Warning",
						f"Your collection has {len(self.all_cards):,} unique cards.\n\n"
						"Processing very large collections may cause performance issues.\n\n"
						"Continue anyway?",
						QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
						QMessageBox.StandardButton.No
				)
				if reply == QMessageBox.StandardButton.No:
					return
			
			# Determine cards to process
			current_view = self.results_stack.currentWidget()
			if level > 0 and isinstance(current_view, NavigableTreeWidget) and hasattr(current_view, 'cards_for_view'):
				cards_to_process = current_view.cards_for_view
			else:
				cards_to_process = self.all_cards
				# Reset to clean state when processing all cards
				self.clear_layout(self.breadcrumb_layout)
				self._safe_clear_stack()  # FIXED: Use safer clearing
				self.reset_preview_pane()
				self.add_breadcrumb("Home", 0)
			
			if not cards_to_process:
				self.show_status_message("No cards to process in current view.", 3000)
				return
			
			# Check if sorting is complete
			unsorted_total = sum(max(0, card.quantity - card.sorted_count) for card in cards_to_process)
			if unsorted_total == 0 and not self.show_sorted_check.isChecked():
				self.show_status_message("🎉 Sorting Complete! All cards in this view are sorted.", 5000)
				return
			
			# Ensure we have a home breadcrumb
			if level == 0 and self.breadcrumb_layout.count() < 1:
				self.add_breadcrumb("Home", 0)
			
			# Create or refresh view
			if level == 0 and not isinstance(current_view, NavigableTreeWidget):
				self.create_new_view(cards_to_process, 0)
			else:
				# FIXED: Ultra-safe criterion access
				criterion = None
				try:
					if self.sort_order and 0 <= level < len(self.sort_order):
						criterion = self.sort_order[level]
				except (IndexError, TypeError):
					criterion = None
				
				nodes = self._generate_level_breakdown(cards_to_process, criterion)
				
				if isinstance(current_view, NavigableTreeWidget):
					current_view.clear()
					self._populate_tree(current_view.invisibleRootItem(), nodes)
					show_sorted = self.show_sorted_check.isChecked()
					header_label = "Total Count" if show_sorted else "Unsorted Count"
					current_view.setHeaderLabels(['Group', header_label])
				else:
					self.create_new_view(cards_to_process, level)
			
			self.filter_edit.setVisible(True)
			self.update_button_visibility()
		
		except IndexError as e:
			# FIXED: Specific index error handling
			self.show_status_message(f"⚠ Navigation error: {e}", 3000)
			try:
				self._force_complete_reset()
			except:
				QMessageBox.critical(self, "Critical Error",
				                     "Unable to recover from navigation error. Please restart the application.")
		
		except MemoryError:
			QMessageBox.critical(
					self,
					"Memory Error",
					"Not enough memory to generate the sorting plan.\n\n"
					"Try:\n"
					"• Reducing the collection size\n"
					"• Restarting the application\n"
					"• Using fewer sorting criteria"
			)
		except Exception as e:
			# FIXED: General error handling
			error_msg = f"Error generating plan: {str(e)}"
			self.show_status_message(f"⚠ Error occurred: {e}", 3000)
			try:
				self._force_complete_reset()
			except:
				QMessageBox.critical(self, "Critical Error", f"{error_msg}\n\nPlease restart the application.")
	
	def create_new_view(self, cards_in_group: List[Card], level: int):
		"""FIXED: More robust create_new_view with comprehensive bounds checking and recursion guards"""
		if getattr(self, '_in_create_view', False):
			return
		
		try:
			self._in_create_view = True
			
			tree = NavigableTreeWidget()
			tree.cards_for_view = cards_in_group
			tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
			
			show_sorted = self.show_sorted_check.isChecked()
			header_label = "Total Count" if show_sorted else "Unsorted Count"
			tree.setHeaderLabels(['Group', header_label])
			
			tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
			tree.setSortingEnabled(True)
			
			# FIXED: Connect signals with recursion protection
			def safe_item_click(item):
				# Use timer to prevent immediate recursion
				QTimer.singleShot(10, lambda: self.handle_item_click(item, level + 1))
			
			def safe_drill_down(item):
				# Use timer to prevent immediate recursion
				QTimer.singleShot(10, lambda: self.drill_down(item, level + 1))
			
			def safe_navigate_up():
				if level > 0:
					QTimer.singleShot(10, lambda: self.navigate_and_refresh(level - 1))
			
			tree.itemClicked.connect(safe_item_click)
			tree.itemDoubleClicked.connect(lambda item: self.mark_item_as_sorted(item))
			tree.drillDownRequested.connect(safe_drill_down)
			tree.navigateUpRequested.connect(safe_navigate_up)
			tree.currentItemChanged.connect(self.update_button_visibility)
			tree.currentItemChanged.connect(self.on_tree_selection_changed)
			
			# FIXED: Always refresh sort_order and validate bounds
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			
			# FIXED: Ultra-safe criterion selection
			criterion = None
			try:
				if 0 <= level < len(self.sort_order):
					criterion = self.sort_order[level]
				else:
					# Level is out of bounds - show individual cards
					criterion = None
					if level >= len(self.sort_order) and len(self.sort_order) > 0:
						self.show_status_message(
								f"Reached end of sort criteria at level {level}. Showing individual cards.", 3000)
			except (IndexError, TypeError):
				criterion = None
				self.show_status_message("Error accessing sort criteria. Showing individual cards.", 3000)
			
			# Generate and populate nodes
			nodes = self._generate_level_breakdown(cards_in_group, criterion)
			self._populate_tree_safe(tree.invisibleRootItem(), nodes)
			tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
			
			self.results_stack.addWidget(tree)
			self.results_stack.setCurrentWidget(tree)
		
		except Exception as e:
			# FIXED: Handle any errors in view creation
			error_msg = f"Error creating view at level {level}: {str(e)}"
			self.show_status_message("⚠ Error creating view - resetting to home.", 3000)
			
			# Clean up any partially created widgets
			if 'tree' in locals():
				try:
					tree.deleteLater()
				except:
					pass
			
			# Force reset to level 0
			try:
				QTimer.singleShot(300, lambda: self.navigate_to_level(0))
			except:
				# If navigation also fails, force a complete reset
				self._force_complete_reset()
		finally:
			self._in_create_view = False
	
	def _update_view_layout(self):
		"""FIXED: Shows or hides the card preview pane and ensures it's always available for individual cards."""
		current_widget = self.results_stack.currentWidget()
		
		# FIXED: Always show preview panel for better user experience
		# Users should be able to see card images whenever they select individual cards,
		# regardless of the view type
		self.preview_panel.setVisible(True)
		
		# Restore splitter sizes when showing preview
		if not self.preview_panel.isVisible():
			self.main_splitter.setSizes(self.splitter_sizes)
	
	def _force_complete_reset(self):
		"""FIXED: Nuclear option - completely reset the UI state"""
		try:
			# FIXED: Clean up workers first
			self.cleanup_workers()
			
			# Clear all widgets from stack safely
			self._safe_clear_stack()
			
			# Clear breadcrumbs
			self.clear_layout(self.breadcrumb_layout)
			
			# Reset preview pane
			self.reset_preview_pane()
			
			# Hide filter and buttons
			self.filter_edit.setVisible(False)
			self.filter_edit.clear()
			self.update_button_visibility()
			
			# Add home breadcrumb back
			self.add_breadcrumb("Home", 0)
			
			self.show_status_message("UI reset to safe state. Try generating plan again.", 5000)
		
		except Exception as e:
			# If even this fails, just show an error
			QMessageBox.critical(self, "Critical Error",
			                     f"Unable to reset UI state: {str(e)}\n\nPlease restart the application.")
	
	def on_tree_selection_changed(self, current, previous):
		"""FIXED: Handle tree selection changes and update card preview"""
		if current:
			# Always try to update preview when a tree item is selected
			self.update_card_preview(current)
		else:
			self.reset_preview_pane()
	
	def create_set_sorter_view(self, cards_to_sort: List[Card], set_name: str):
		view = SetSorterView(cards_to_sort, set_name, self)
		self.results_stack.addWidget(view)
		self.results_stack.setCurrentWidget(view)
		self._update_view_layout()
	
	def handle_item_click(self, item: QTreeWidgetItem, next_level: int):
		"""FIXED: Safer item click handling with recursion protection"""
		if (self._is_destroyed or not item or
				getattr(self, '_in_handle_click', False)):
			return
		
		try:
			self._in_handle_click = True
			
			# Always update preview first
			self.update_card_preview(item)
			
			# FIXED: Refresh sort order and validate
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			
			# Check if this is an individual card view where we don't want to drill down
			current_level = next_level - 1
			
			if 0 <= current_level < len(self.sort_order) and self.sort_order[current_level] == "Name":
				# This is a card item, just update preview (already done above)
				return
		
		except Exception as e:
			print(f"Error in handle_item_click: {e}")
		finally:
			self._in_handle_click = False
	
	def drill_down(self, item: QTreeWidgetItem, next_level: int):
		"""FIXED: Safer drill down with enhanced navigation protection"""
		if (self._is_navigating or self._is_destroyed or not item or
				getattr(self, '_in_drill_down', False)):
			return
		
		try:
			self._in_drill_down = True
			self._is_navigating = True
			
			# Refresh sort order and validate
			self.sort_order = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
			
			# FIXED: Check if next_level is valid
			if next_level > len(self.sort_order):
				self.show_status_message("Cannot drill down further - no more sort criteria available.", 3000)
				return
			
			# If drilling from 'Set' to 'Name', show the optimized letter-sorting view
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
					
					# Use longer timer to avoid recursion
					QTimer.singleShot(200, lambda: self.create_set_sorter_view(cards_in_set, breadcrumb_text))
					return
			
			# Default drill-down behavior
			cards_in_group = self._get_cards_from_item(item)
			if not cards_in_group:
				self.show_status_message("No cards found in selected group.", 2000)
				return
			
			self.navigate_to_level(next_level - 1)
			self.add_breadcrumb(item.text(0), next_level)
			
			# Use longer timer to avoid recursion
			QTimer.singleShot(200, lambda: self.create_new_view(cards_in_group, next_level))
		
		finally:
			self._is_navigating = False
			self._in_drill_down = False
	
	def add_breadcrumb(self, text: str, level: int):
		if level > 0:
			self.breadcrumb_layout.addWidget(QLabel(">"))
		btn = QPushButton(text.split(': ')[-1])
		btn.setObjectName("BreadcrumbButton")
		btn.setToolTip(f"Navigate back to {text}")
		btn.clicked.connect(lambda: self.navigate_and_refresh(level))
		self.breadcrumb_layout.addWidget(btn)
	
	def navigate_to_level(self, level: int):
		"""FIXED: Enhanced navigate_to_level with recursion protection"""
		if getattr(self, '_in_navigate', False):
			return
		
		try:
			self._in_navigate = True
			
			# FIXED: Ensure level is within valid bounds
			max_level = self.results_stack.count() - 1
			level = max(0, min(level, max_level))
			
			# Remove widgets beyond target level
			while self.results_stack.count() > level + 1:
				widget_index = self.results_stack.count() - 1
				widget = self.results_stack.widget(widget_index)
				self.results_stack.removeWidget(widget)
				if widget:
					if hasattr(widget, 'cleanup'):
						widget.cleanup()
					widget.deleteLater()
			
			# Remove breadcrumbs beyond target level
			target_breadcrumb_count = (level * 2) + 1  # Each level adds a label + arrow, except first
			while self.breadcrumb_layout.count() > target_breadcrumb_count:
				item = self.breadcrumb_layout.takeAt(self.breadcrumb_layout.count() - 1)
				if item and item.widget():
					item.widget().deleteLater()
			
			# FIXED: Safely set current index
			if self.results_stack.count() > level:
				self.results_stack.setCurrentIndex(level)
			
			# Clear and reset filter
			self.filter_edit.clear()
			self.filter_current_view("")
			self.update_button_visibility()
		
		except Exception as e:
			# FIXED: Handle navigation errors gracefully
			self.show_status_message(f"⚠ Navigation error: {str(e)}", 3000)
			
			# Force reset to level 0 as a fallback
			try:
				while self.results_stack.count() > 1:
					widget = self.results_stack.widget(1)
					self.results_stack.removeWidget(widget)
					if widget:
						if hasattr(widget, 'cleanup'):
							widget.cleanup()
						widget.deleteLater()
				
				self.clear_layout(self.breadcrumb_layout)
				self.add_breadcrumb("Home", 0)
				self.results_stack.setCurrentIndex(0)
			
			except Exception:
				# If all else fails, do a complete UI reset
				self.show_status_message("⚠ Severe navigation error - performing complete reset.", 5000)
		finally:
			self._in_navigate = False
	
	def navigate_and_refresh(self, level: int):
		"""Navigates to a specific level and refreshes the view by regenerating the plan."""
		self.navigate_to_level(level)  # This just changes the view
		QTimer.singleShot(0, self._refresh_current_view)  # This populates it
	
	def _generate_level_breakdown(self, current_cards: List[Card], criterion: str | None) -> List[SortGroup]:
		show_sorted = self.show_sorted_check.isChecked()
		
		if not criterion or criterion == "Name":
			nodes = [SortGroup(group_name=c.name, count=(c.quantity - c.sorted_count), cards=[c], is_card_leaf=True) for
			         c in current_cards]
			for node in nodes:
				node.total_count = node.cards[0].quantity
				node.unsorted_count = node.count
			return sorted(nodes, key=lambda sg: sg.group_name or "")
		
		groups = collections.defaultdict(list)
		for card in current_cards:
			groups[self._get_nested_value(card, criterion)].append(card)
		
		nodes = []
		for name, card_group in sorted(groups.items()):
			unsorted_count = sum(max(0, c.quantity - c.sorted_count) for c in card_group)
			
			if not show_sorted and unsorted_count == 0:
				continue
			
			total_count = sum(c.quantity for c in card_group)
			display_count = total_count if show_sorted else unsorted_count
			
			node = SortGroup(
					group_name=f"{criterion}: {name}",
					count=display_count,
					cards=card_group
			)
			node.unsorted_count = unsorted_count
			node.total_count = total_count
			nodes.append(node)
		
		return nodes
	
	def _populate_tree_safe(self, parent_item: QTreeWidgetItem, nodes: List[SortGroup]):
		"""FIXED: Populate tree without processEvents to prevent stack overflow"""
		try:
			# FIXED: Remove batch processing and processEvents to prevent recursion
			for node in nodes:
				tree_item = SortableTreeWidgetItem(parent_item, [node.group_name, str(node.count)])
				tree_item.setData(0, Qt.ItemDataRole.UserRole, node.cards)
				
				if hasattr(node, 'unsorted_count') and node.unsorted_count <= 0:
					font = tree_item.font(0)
					font.setStrikeOut(True)
					tree_item.setFont(0, font)
					tree_item.setFont(1, font)
					tree_item.setForeground(0, QColor(Qt.GlobalColor.gray))
					tree_item.setForeground(1, QColor(Qt.GlobalColor.gray))
				
				if node.is_card_leaf:
					font = tree_item.font(0)
					font.setItalic(True)
					for j in range(2):
						tree_item.setFont(j, font)
		
		except Exception as e:
			raise RuntimeError(f"Error populating tree: {str(e)}")
	
	def _get_nested_value(self, card: Card, key: str) -> str:
		if key == "First Letter":
			return card.name[0].upper() if card.name and card.name != 'N/A' else '#'
		if key == "Set": return card.set_name
		if key == "Rarity": return card.rarity.capitalize()
		if key == "Type Line": return card.type_line.split('//')[0].strip()
		if key == "Condition": return card.condition.capitalize()
		if key == "Color Identity": return ''.join(sorted(card.color_identity)) or 'Colorless'
		if key == "Commander Staple": return "Staple (Top 1000)" if card.edhrec_rank and card.edhrec_rank <= 1000 else "Not a Staple"
		return 'N/A'
	
	def clear_layout(self, layout: QHBoxLayout):
		while layout.count():
			if child := layout.takeAt(0).widget():
				child.deleteLater()
	
	def reset_preview_pane(self, *args):
		"""FIXED: Clean up image worker and reset preview"""
		cleanup_worker_thread(self.image_thread, self.image_worker)
		self.current_loading_id = None
		self.card_image_label.setText("Select a card to see its image.")
		self.card_image_label.setPixmap(QPixmap())
		self.card_details_label.setText("")
	
	def update_card_preview(self, item: QTreeWidgetItem):
		"""FIXED: Improved card preview with proper threading and better error handling"""
		self.reset_preview_pane()  # Stop any previous image fetch
		
		cards = self._get_cards_from_item(item)
		if not cards:
			return
		
		# FIXED: Show preview for single cards or first card in group
		if len(cards) == 1:
			card = cards[0]
		elif len(cards) > 1:
			# Show details for the group but preview the first card's image
			card = cards[0]
			# Update details label to show group info
			self.card_details_label.setText(
					f"<b>Group: {item.text(0)}</b><br>"
					f"Contains {len(cards)} different cards<br>"
					f"Total cards: {sum(c.quantity for c in cards)}<br>"
					f"Showing preview of: {card.name}"
			)
		else:
			return
		
		if not isinstance(card, Card):
			return
		
		# FIXED: Always show card details, even if no image
		if len(cards) == 1:
			self.card_details_label.setText(
					f"<b>{card.name}</b><br>{card.mana_cost or ''}<br>{card.type_line}<br>"
					f"<i>{card.set_name} ({card.rarity.upper()})</i><br><br>"
					f"Total Owned: {card.quantity}<br>Sorted: {card.sorted_count}")
		
		# FIXED: Only try to load image if we have a valid URI
		if not card.image_uri:
			self.card_image_label.setText("No image available for this card.")
			return
		
		self.current_loading_id = card.scryfall_id
		self.card_image_label.setText("Loading image...")
		
		# Setup worker thread
		self.image_thread = QThread()
		self.image_worker = ImageFetchWorker(card.image_uri, card.scryfall_id, self.api, parent=None)
		self.image_worker.moveToThread(self.image_thread)
		
		# Connect signals
		self.image_thread.started.connect(self.image_worker.process)
		self.image_worker.finished.connect(self.on_image_loaded)
		self.image_worker.error.connect(self.on_image_error)
		
		# Cleanup connections
		self.image_worker.finished.connect(self.image_thread.quit)
		self.image_worker.finished.connect(self.image_worker.deleteLater)
		self.image_thread.finished.connect(self.image_thread.deleteLater)
		
		self.image_thread.start()
	
	def on_image_loaded(self, image_data: bytes, scryfall_id: str):
		"""FIXED: Handle successful image loading"""
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
			# FIXED: Clean up worker
			self.image_thread = None
			self.image_worker = None
	
	def on_image_error(self, error_message: str):
		"""FIXED: Handle image loading errors"""
		self.card_image_label.setText(f"Image unavailable:\n{error_message}")
		self.image_thread = None
		self.image_worker = None
	
	def export_current_view(self):
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
	
	def filter_current_view(self, text: str):
		"""Filter the current view, whether it's a standard tree or the SetSorterView."""
		current_widget = self.results_stack.currentWidget()
		tree_to_filter = None
		
		if isinstance(current_widget, QTreeWidget):
			tree_to_filter = current_widget
		elif isinstance(current_widget, SetSorterView) and hasattr(current_widget, 'tree'):
			tree_to_filter = current_widget.tree
		
		if not tree_to_filter:
			return
		
		iterator = QTreeWidgetItemIterator(tree_to_filter, QTreeWidgetItemIterator.IteratorFlag.All)
		while iterator.value():
			item = iterator.value()
			item.setHidden(text.lower() not in item.text(0).lower())
			iterator += 1
	
	def _get_cards_from_item(self, item: QTreeWidgetItem) -> List[Card]:
		if not item:
			return []
		item_data = item.data(0, Qt.ItemDataRole.UserRole)
		if item_data:
			if isinstance(item_data, list) and all(isinstance(c, Card) for c in item_data):
				return item_data
			elif hasattr(item_data, 'cards'):
				return item_data.cards
		return []
	
	def on_mark_group_button_clicked(self):
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
			self._refresh_current_view()
	
	def mark_item_as_sorted(self, item: QTreeWidgetItem):
		"""Toggles the sorted status of a single item, used by double-click."""
		cards = self._get_cards_from_item(item)
		if not cards:
			self.show_status_message("⚠ Could not find cards for this group.")
			return
		
		is_already_sorted = all(c.is_fully_sorted for c in cards)
		
		if is_already_sorted:
			for card in cards:
				card.sorted_count = 0
			self.show_status_message(f"✓ Group '{item.text(0)}' marked as UNSORTED.")
		else:
			for card in cards:
				card.sorted_count = card.quantity
			self.show_status_message(f"✓ Group '{item.text(0)}' marked as SORTED.")
		
		self.project_modified.emit()
		self._refresh_current_view()
	
	def _mark_cards_as_sorted(self, item: QTreeWidgetItem) -> bool:
		"""
		Internal method that only marks cards without refreshing, for batch operations.
		Returns True if cards were marked, False otherwise.
		"""
		cards_to_mark = self._get_cards_from_item(item)
		if not cards_to_mark:
			self.show_status_message("⚠ Could not find cards for this group.")
			return False
		for card in cards_to_mark:
			card.sorted_count = card.quantity
		return True
	
	def update_button_visibility(self, *args):
		is_normal_view = isinstance(self.results_stack.currentWidget(), NavigableTreeWidget)
		self.mark_sorted_button.setVisible(is_normal_view)
		self.export_button.setVisible(is_normal_view)
	
	def show_status_message(self, message: str, timeout: int = 2500):
		self.status_label.setText(message)
		QTimer.singleShot(timeout, lambda: self.status_label.setText(""))
	
	def handle_enter_key(self):
		current_tree = self.results_stack.currentWidget()
		if isinstance(current_tree, NavigableTreeWidget) and current_tree.currentItem():
			level = self.results_stack.currentIndex()
			self.drill_down(current_tree.currentItem(), level + 1)
	
	def handle_escape_key(self):
		if self.filter_edit.text():
			self.filter_edit.clear()
		else:
			if isinstance(current_tree := self.results_stack.currentWidget(), QTreeWidget):
				current_tree.clearSelection()
	
	def handle_backspace_key(self):
		level = self.results_stack.currentIndex()
		if level > 0:
			self.navigate_and_refresh(level - 1)
	
	def get_save_data(self) -> dict:
		"""Gathers all project data into a dictionary for saving."""
		if not self.all_cards:
			return {}
		
		progress = {c.scryfall_id: c.sorted_count for c in self.all_cards if c.sorted_count > 0}
		sort_criteria = [self.selected_list.item(i).text() for i in range(self.selected_list.count())]
		
		cards_as_dicts = [c.__dict__ for c in self.all_cards]
		
		return {
				"metadata": {"version": "1.1", "app": "MTGToolkit"},
				"collection": cards_as_dicts,
				"progress": progress,
				"settings": {
						"sort_criteria": sort_criteria,
						"group_low_count": self.group_low_count_check.isChecked(),
						"group_threshold": self.group_threshold_edit.text()
				}
		}
	
	def save_to_project(self, filepath: str, is_auto_save: bool = False) -> bool:
		"""Saves the current project state to a .mtgproj file."""
		save_data = self.get_save_data()
		if not save_data:
			if not is_auto_save:
				QMessageBox.information(self, "Empty Project", "Nothing to save. Please import a collection first.")
			return False
		try:
			with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
				zf.writestr('project_data.json', json.dumps(save_data, indent=2))
			if not is_auto_save:
				self.show_status_message(f"Project saved to {pathlib.Path(filepath).name}")
			return True
		except Exception as e:
			QMessageBox.critical(self, "Save Error", f"Failed to save project file:\n{e}")
			return False
	
	def load_from_project(self, filepath: str) -> bool:
		"""Loads project state from a .mtgproj file."""
		try:
			with zipfile.ZipFile(filepath, 'r') as zf:
				project_data = json.loads(zf.read('project_data.json'))
			
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
			self.start_new_plan_generation()
			return True
		except Exception as e:
			QMessageBox.critical(self, "Load Project Error", f"Failed to load project file:\n\n{e}")
			self.clear_project(prompt=False)
			return False
