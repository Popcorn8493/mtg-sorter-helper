# ui/custom_widgets.py - CORRECTED WORKING VERSION

from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent


class SortableTreeWidgetItem(QTreeWidgetItem):
	"""Enhanced tree widget item with improved sorting capabilities"""

	def __lt__(self, other):
		"""
		Custom sorting logic for tree items.

		- Column 1 (Count): Sorts numerically, treating empty strings as smallest.
		- Other Columns: Sorts alphabetically (case-insensitive).
		- Special Prefixes: For text like "Set: XYZ", it sorts based on "XYZ".
		"""
		if not isinstance(other, QTreeWidgetItem):
			return NotImplemented

		tree = self.treeWidget()
		column = tree.sortColumn() if tree else 0

		try:
			# For the count column (usually column 1), sort numerically
			if column == 1:
				self_text = self.text(column)
				other_text = other.text(column)

				# Handle empty strings to sort them at the top
				if not self_text:
					return True
				if not other_text:
					return False

				self_value = int(self_text)
				other_value = int(other_text)
				return self_value < other_value
		except (ValueError, IndexError):
			# Fall back to string comparison if numeric conversion fails
			pass

		# For other columns, sort alphabetically (case-insensitive)
		self_text = self.text(column).lower()
		other_text = other.text(column).lower()

		# For columns with "key: value" format, sort by value for more natural sorting.
		if ': ' in self_text and ': ' in other_text:
			try:
				# Extract the part after the colon for comparison
				self_suffix = self_text.split(': ', 1)[1]
				other_suffix = other_text.split(': ', 1)[1]
				return self_suffix < other_suffix
			except IndexError:
				# If split fails, fall back to comparing the full text
				pass

		return self_text < other_text


class NavigableTreeWidget(QTreeWidget):
	"""CORRECTED: Stack overflow prevention with proper implementation"""
	
	# Signals for different navigation actions
	drillDownRequested = pyqtSignal(QTreeWidgetItem)
	navigateUpRequested = pyqtSignal()
	markAsortedRequested = pyqtSignal(list)  # List of selected items
	itemSortedToggled = pyqtSignal(QTreeWidgetItem, bool)  # Item, is_sorted
	
	def __init__(self, parent=None):
		super().__init__(parent)
		
		# FIXED: Proper initialization of all attributes
		self._is_destroyed = False
		self._signals_connected = False
		self._signals_blocked_count = 0
		self._in_operation = False  # Simple flag to prevent recursion
		
		# Navigation history
		self.navigation_history = []
		self.max_history_size = 10
		
		# Operation timer for deferred execution
		self._operation_timer = QTimer()
		self._operation_timer.timeout.connect(self._process_pending_operations)
		self._operation_timer.setSingleShot(True)
		self._pending_operations = []
		
		# Enhanced tooltips
		self.setToolTip(
				"Keyboard Navigation:\n"
				"• Enter/Return - Drill down into selected group\n"
				"• Backspace - Navigate back up one level\n"
				"• Space - Mark selected group(s) as sorted\n"
				"• Ctrl+A - Select all items\n"
				"• Arrow keys - Navigate between items\n"
				"• F2 - Show item details (if available)\n\n"
				"Mouse:\n"
				"• Click checkbox - Mark group as sorted/unsorted\n"
				"• Click item name - Select item\n"
				"• Double-click - Drill down into group\n"
				"• Right-click - Context menu (if available)\n\n"
				"Note: Sorted items are hidden unless 'Show Sorted' is checked"
		)
		
		# Enable extended selection by default
		self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
		
		# FIXED: Deferred signal connection
		QTimer.singleShot(100, self._safe_connect_signals)
	
	def _safe_connect_signals(self):
		"""FIXED: Safely connect signals with error handling"""
		if self._is_destroyed or self._signals_connected:
			return
		
		try:
			self.blockSignals(True)
			self.itemSelectionChanged.connect(self._safe_on_selection_changed)
			self.blockSignals(False)
			self._signals_connected = True
		except Exception as e:
			print(f"Warning: Failed to connect selection signal: {e}")
			self.blockSignals(False)
	
	def _safe_block_signals(self):
		"""FIXED: Safe signal blocking with reference counting"""
		self._signals_blocked_count += 1
		if self._signals_blocked_count == 1:
			self.blockSignals(True)
	
	def _safe_unblock_signals(self):
		"""FIXED: Safe signal unblocking with reference counting"""
		self._signals_blocked_count = max(0, self._signals_blocked_count - 1)
		if self._signals_blocked_count == 0:
			self.blockSignals(False)
	
	def _queue_operation(self, operation_func, delay_ms=10):
		"""Queue operations for safe deferred execution"""
		if self._is_destroyed:
			return
		
		self._pending_operations.append(operation_func)
		if not self._operation_timer.isActive():
			self._operation_timer.start(delay_ms)
	
	def _process_pending_operations(self):
		"""Process queued operations safely"""
		if self._is_destroyed or not self._pending_operations:
			return
		
		# Process one operation at a time
		operation = self._pending_operations.pop(0)
		
		try:
			operation()
		except Exception as e:
			print(f"Error processing pending operation: {e}")
		
		# Schedule next operation if more are pending
		if self._pending_operations and not self._is_destroyed:
			self._operation_timer.start(10)
	
	def cleanup(self):
		"""FIXED: Comprehensive cleanup"""
		if self._is_destroyed:
			return
		
		self._is_destroyed = True
		
		# Stop any pending operations
		if hasattr(self, '_operation_timer'):
			self._operation_timer.stop()
		if hasattr(self, '_pending_operations'):
			self._pending_operations.clear()
			
		# Block signals to prevent any last-minute events on a widget that is being destroyed.
		# Qt's object ownership model will handle the actual disconnection of signals
		# when this widget is deleted by its parent or by deleteLater().
		self.blockSignals(True)
	
	def closeEvent(self, event):
		"""Handle widget close event"""
		self.cleanup()
		super().closeEvent(event)
	
	def mouseDoubleClickEvent(self, event: QMouseEvent):
		"""FIXED: Safe mouse double click handling"""
		if self._is_destroyed or self._in_operation:
			return
		
		try:
			self._in_operation = True
			
			if event.button() == Qt.MouseButton.RightButton:
				self._safe_emit_signal(lambda: self.navigateUpRequested.emit())
				event.accept()
			else:
				super().mouseDoubleClickEvent(event)
		except Exception as e:
			print(f"Error in mouseDoubleClickEvent: {e}")
		finally:
			self._in_operation = False
	
	def keyPressEvent(self, event: QKeyEvent):
		"""FIXED: Safe keyboard event handling by dispatching to specialized handlers."""
		if self._is_destroyed or self._in_operation:
			return

		try:
			self._in_operation = True

			# Sequentially try handlers. If a handler processes the key, accept the event and return.
			if self._handle_item_action_keys(event) or \
			   self._handle_navigation_keys(event) or \
			   self._handle_selection_keys(event):
				event.accept()
				return

			# If no custom handler processed the key, pass it to the base class.
			super().keyPressEvent(event)

		except Exception as e:
			print(f"Error in keyPressEvent: {e}")
			# Fallback to base class to avoid swallowing the event on error.
			try:
				super().keyPressEvent(event)
			except:
				pass
		finally:
			self._in_operation = False

	def _handle_item_action_keys(self, event: QKeyEvent) -> bool:
		"""Handles key presses that perform actions on the current/selected item(s)."""
		key = event.key()
		current_item = self.currentItem()

		if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
			if current_item:
				self._add_to_history()
				self._safe_emit_signal(lambda: self.drillDownRequested.emit(current_item))
				return True
		elif key == Qt.Key.Key_Space:
			selected_items = self.selectedItems()
			if selected_items:
				self._safe_emit_signal(lambda: self.markAsortedRequested.emit(selected_items))
				return True
		elif key == Qt.Key.Key_F2:
			if current_item:
				self._show_item_details(current_item)
				return True
		return False

	def _handle_navigation_keys(self, event: QKeyEvent) -> bool:
		"""Handles key presses for navigating within the tree."""
		key = event.key()
		modifiers = event.modifiers()

		if key == Qt.Key.Key_Backspace:
			self._safe_emit_signal(lambda: self.navigateUpRequested.emit())
			return True
		elif key == Qt.Key.Key_Home:
			if self.topLevelItemCount() > 0:
				item = self.topLevelItem(0)
				if item:
					self._safe_block_signals()
					try:
						self.setCurrentItem(item)
					finally:
						self._safe_unblock_signals()
				return True
		elif key == Qt.Key.Key_End:
			if self.topLevelItemCount() > 0:
				item = self.topLevelItem(self.topLevelItemCount() - 1)
				if item:
					self._safe_block_signals()
					try:
						self.setCurrentItem(item)
					finally:
						self._safe_unblock_signals()
				return True
		elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
			if not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
				letter = chr(key).upper()
				self._navigate_to_letter(letter)
				return True
		return False

	def _handle_selection_keys(self, event: QKeyEvent) -> bool:
		"""Handles key presses related to item selection."""
		key = event.key()
		modifiers = event.modifiers()

		if key == Qt.Key.Key_Escape:
			self._safe_block_signals()
			try:
				self.clearSelection()
			finally:
				self._safe_unblock_signals()
			return True
		elif key == Qt.Key.Key_A and modifiers & Qt.KeyboardModifier.ControlModifier:
			self._safe_block_signals()
			try:
				self.selectAll()
			finally:
				self._safe_unblock_signals()
			return True
		return False

	def _safe_emit_signal(self, emit_func):
		"""FIXED: Safely emit signals with deferred execution"""
		if self._is_destroyed:
			return
		
		try:
			# Queue the signal emission for safe deferred execution
			self._queue_operation(emit_func, 20)
		except Exception as e:
			print(f"Error in _safe_emit_signal: {e}")
	
	def _add_to_history(self):
		"""Add current state to navigation history"""
		if self._is_destroyed:
			return
		
		try:
			current_item = self.currentItem()
			if current_item:
				item_text = current_item.text(0)
				self.navigation_history.append(item_text)
				
				# Limit history size
				if len(self.navigation_history) > self.max_history_size:
					self.navigation_history.pop(0)
		except Exception as e:
			print(f"Error adding to history: {e}")
	
	def _show_item_details(self, item: QTreeWidgetItem):
		"""Show detailed information about an item"""
		if self._is_destroyed or not item:
			return
		
		try:
			details = [f"Group: {item.text(0)}"]
			
			if item.columnCount() > 1:
				details.append(f"Count: {item.text(1)}")
			
			# If the item has associated card data, show more details
			item_data = item.data(0, Qt.ItemDataRole.UserRole)
			if item_data and isinstance(item_data, list) and len(item_data) > 0:
				card_count = len(item_data)
				details.append(f"Contains {card_count} unique cards")
				
				# Show breakdown by type if available
				if hasattr(item_data[0], 'type_line'):
					type_counts = {}
					for card in item_data:
						try:
							card_type = card.type_line.split('—')[0].strip()
							type_counts[card_type] = type_counts.get(card_type, 0) + 1
						except:
							pass
					
					if type_counts:
						details.append("Types: " + ", ".join(f"{t}({c})" for t, c in sorted(type_counts.items())))
			
			# Show details in tooltip
			tooltip_text = "\n".join(details)
			self.setToolTip(tooltip_text)
		
		except Exception as e:
			print(f"Error showing item details: {e}")
	
	def _navigate_to_letter(self, letter: str):
		"""Navigate to the first item starting with the given letter"""
		if self._is_destroyed:
			return
		
		try:
			self._safe_block_signals()
			
			for i in range(self.topLevelItemCount()):
				item = self.topLevelItem(i)
				if item:
					item_text = item.text(0).upper()
					# Handle items with prefixes like "Set: ABC"
					if ': ' in item_text:
						try:
							item_text = item_text.split(': ', 1)[1]
						except IndexError:
							pass
					
					if item_text.startswith(letter):
						self.setCurrentItem(item)
						self.scrollToItem(item)
						break
		except Exception as e:
			print(f"Error navigating to letter: {e}")
		finally:
			self._safe_unblock_signals()
	
	def _safe_on_selection_changed(self):
		"""FIXED: Safe selection change handling"""
		if self._is_destroyed or not self._signals_connected or self._in_operation:
			return
		
		try:
			# Queue the actual selection handling to prevent immediate recursion
			self._queue_operation(self._do_selection_changed, 5)
		except Exception as e:
			print(f"Error in _safe_on_selection_changed: {e}")
	
	def _do_selection_changed(self):
		"""Handle selection change with safety measures"""
		if self._is_destroyed:
			return
		
		try:
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
		except Exception as e:
			print(f"Error in selection changed handler: {e}")
	
	def mousePressEvent(self, event):
		"""FIXED: Safe mouse press handling that allows itemClicked signal emission"""
		if self._is_destroyed:
			return
		
		try:
			# Don't set _in_operation flag here as it blocks Qt's signal emission
			# Call parent first to allow normal Qt event processing and signal emission
			super().mousePressEvent(event)
			
			# Update tooltip based on what was clicked (deferred to avoid interference)
			if event.button() == Qt.MouseButton.LeftButton:
				item = self.itemAt(event.pos())
				if item:
					# Queue the details showing with longer delay to avoid interference with signals
					self._queue_operation(lambda: self._show_item_details(item), 50)
		
		except Exception as e:
			print(f"Error in mousePressEvent: {e}")
	
	def get_navigation_history(self):
		"""Get the navigation history for debugging"""
		try:
			return self.navigation_history.copy() if not self._is_destroyed else []
		except:
			return []
	
	def clear_navigation_history(self):
		"""Clear the navigation history"""
		try:
			if not self._is_destroyed:
				self.navigation_history.clear()
		except:
			self.navigation_history = []

	def _populate_tree_progressively(self, nodes, parent_item=None, chunk_size=100, on_finished=None):
		"""Populates the tree in chunks to prevent stack overflow"""
		if self._is_destroyed:
			print("DEBUG: _populate_tree_progressively aborted - widget destroyed")
			return

		if parent_item is None:
			parent_item = self.invisibleRootItem()

		chunk = nodes[:chunk_size]
		remaining_nodes = nodes[chunk_size:]
		
		print(f"DEBUG: Processing chunk of {len(chunk)} nodes, {len(remaining_nodes)} remaining")

		try:
			for i, node in enumerate(chunk):
				try:
					tree_item = SortableTreeWidgetItem(parent_item, [node.group_name, str(node.count)])
					tree_item.setData(0, Qt.ItemDataRole.UserRole, node.cards)
					
					# Add checkbox functionality
					tree_item.setFlags(tree_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
					
					# Check if all cards in this group are sorted
					if hasattr(node, 'cards') and node.cards:
						all_sorted = all(c.is_fully_sorted for c in node.cards)
						if all_sorted:
							tree_item.setCheckState(0, Qt.CheckState.Checked)
							# Make sorted items visually muted
							for col in range(2):
								tree_item.setForeground(col, QColor(128, 128, 128))
							
							# Hide sorted items if show_sorted is disabled
							# Check if parent has show_sorted_check attribute
							parent_widget = self.parent()
							while parent_widget and not hasattr(parent_widget, 'show_sorted_check'):
								parent_widget = parent_widget.parent()
							
							if parent_widget and hasattr(parent_widget, 'show_sorted_check'):
								show_sorted = parent_widget.show_sorted_check.isChecked()
								if not show_sorted:
									tree_item.setHidden(True)
						else:
							tree_item.setCheckState(0, Qt.CheckState.Unchecked)

					if hasattr(node, 'unsorted_count') and node.unsorted_count <= 0:
						font = tree_item.font(0)
						font.setStrikeOut(True)
						tree_item.setFont(0, font)
						tree_item.setFont(1, font)
						tree_item.setForeground(0, QColor(Qt.GlobalColor.gray))
						tree_item.setForeground(1, QColor(Qt.GlobalColor.gray))

					if getattr(node, 'is_card_leaf', False):
						font = tree_item.font(0)
						font.setItalic(True)
						for j in range(2):
							tree_item.setFont(j, font)
				except Exception as e:
					print(f"ERROR: Failed to process node {i}: {e}")
					continue

		except Exception as e:
			print(f"ERROR: Failed during chunk processing: {e}")
			import traceback
			traceback.print_exc()
			return

		if remaining_nodes:
			print(f"DEBUG: Scheduling next chunk ({len(remaining_nodes)} nodes remaining)")
			QTimer.singleShot(0, lambda: self._populate_tree_progressively(remaining_nodes, parent_item, chunk_size, on_finished))
		else:
			# This is the last chunk, now we can sort and call the callback.
			print("DEBUG: Final chunk completed, running final actions...")
			def final_actions():
				if self._is_destroyed:
					print("DEBUG: final_actions aborted - widget destroyed")
					return
				try:
					print("DEBUG: Sorting tree...")
					self.sortByColumn(self.sortColumn(), self.header().sortIndicatorOrder())
					print("DEBUG: Tree sorted, calling on_finished callback...")
					if on_finished:
						try:
							on_finished()
							print("DEBUG: on_finished callback completed")
						except Exception as e:
							print(f"ERROR: on_finished callback failed: {e}")
							import traceback
							traceback.print_exc()
				except Exception as e:
					print(f"ERROR: final_actions failed: {e}")
					import traceback
					traceback.print_exc()
			
			QTimer.singleShot(0, final_actions)
	
	def mousePressEvent(self, event):
		"""Handle mouse press events, including checkbox clicks"""
		if self._is_destroyed or self._in_operation:
			return
		
		item = self.itemAt(event.pos())
		if item and event.button() == Qt.MouseButton.LeftButton:
			# Check if click is in the checkbox area (first 20 pixels of first column)
			column = self.columnAt(event.pos().x())
			if column == 0 and event.pos().x() < 20:
				# This is a checkbox click
				self._handle_checkbox_click(item)
				event.accept()
				return
		
		# Default handling for other clicks
		super().mousePressEvent(event)
	
	def _handle_checkbox_click(self, item):
		"""Handle checkbox click to toggle sorted state"""
		if self._is_destroyed or not item:
			return
		
		try:
			# Get current checkbox state
			current_state = item.checkState(0)
			
			# Toggle the state
			if current_state == Qt.CheckState.Checked:
				new_state = Qt.CheckState.Unchecked
				is_sorted = False
			else:
				new_state = Qt.CheckState.Checked
				is_sorted = True
			
			# Update the checkbox
			item.setCheckState(0, new_state)
			
			# Emit signal for parent to handle the sorted state change
			self.itemSortedToggled.emit(item, is_sorted)
			
		except Exception as e:
			print(f"Error handling checkbox click: {e}")
	
	def set_item_sorted_state(self, item, is_sorted):
		"""Set the sorted state of an item (updates checkbox)"""
		if not item:
			return
		
		try:
			if is_sorted:
				item.setCheckState(0, Qt.CheckState.Checked)
				# Make the item visually muted when sorted
				for col in range(self.columnCount()):
					item.setForeground(col, QColor(128, 128, 128))
			else:
				item.setCheckState(0, Qt.CheckState.Unchecked)
				# Restore normal appearance
				for col in range(self.columnCount()):
					item.setForeground(col, QColor(255, 255, 255))
		except Exception as e:
			print(f"Error setting item sorted state: {e}")

class StatusAwareWidget(QObject):
	"""A mixin class for widgets that provide status updates."""

	def __init__(self, parent=None):
		super().__init__(parent)
		self._status_message = ""
		self._status_timeout = 0
		self._is_destroyed = False
	
	def cleanup(self):
		"""Clean up status widget"""
		self._is_destroyed = True
		self._status_message = ""
		self._status_timeout = 0
	
	def set_status_message(self, message: str, timeout: int = 0):
		"""Set a status message that can be displayed in UI"""
		if self._is_destroyed:
			return
		
		try:
			self._status_message = str(message) if message is not None else ""
			self._status_timeout = max(0, int(timeout)) if timeout is not None else 0
		except Exception as e:
			print(f"Error setting status message: {e}")
			self._status_message = ""
			self._status_timeout = 0
	
	def get_status_message(self) -> str:
		"""Get the current status message"""
		if self._is_destroyed:
			return ""
		return getattr(self, '_status_message', "")
	
	def clear_status_message(self):
		"""Clear the current status message"""
		if not self._is_destroyed:
			self._status_message = ""
			self._status_timeout = 0
