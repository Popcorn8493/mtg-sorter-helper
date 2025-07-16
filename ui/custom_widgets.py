# ui/custom_widgets.py - FIXED VERSION with stack overflow prevention

from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal as Signal, QObject, QTimer
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent


class SortableTreeWidgetItem(QTreeWidgetItem):
	"""Enhanced tree widget item with improved sorting capabilities"""
	
	def __lt__(self, other):
		"""Custom sorting logic for tree items"""
		if not isinstance(other, QTreeWidgetItem):
			return False
		
		tree = self.treeWidget()
		column = tree.sortColumn() if tree else 0
		
		try:
			# For the count column (usually column 1), sort numerically
			if column == 1:
				self_text = self.text(column)
				other_text = other.text(column)
				
				# Handle empty strings
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
		
		# Handle special prefixes (like "Set: ", "Rarity: ", etc.)
		if ': ' in self_text and ': ' in other_text:
			# Extract the part after the colon for comparison
			try:
				self_suffix = self_text.split(': ', 1)[1]
				other_suffix = other_text.split(': ', 1)[1]
				return self_suffix < other_suffix
			except IndexError:
				pass
		
		return self_text < other_text


class NavigableTreeWidget(QTreeWidget):
	"""FIXED: Stack overflow prevention with recursion guards and better signal handling"""
	
	# Signals for different navigation actions
	drillDownRequested = Signal(QTreeWidgetItem)
	navigateUpRequested = Signal()
	markAsortedRequested = Signal(list)  # List of selected items
	
	def __init__(self, parent=None):
		super().__init__(parent)
		
		# FIXED: Add recursion guards
		self._in_key_event = False
		self._in_mouse_event = False
		self._in_selection_change = False
		self._signal_emission_blocked = False
		
		# Initialize all attributes and safety flags
		self.navigation_history = []
		self.max_history_size = 10
		self._is_connected = True
		self._is_destroyed = False
		self._signals_connected = False
		
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
		
		# Enable extended selection by default for multiple item operations
		self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
		
		# FIXED: Connect signals with delay and guards
		QTimer.singleShot(100, self._safe_connect_signals)
	
	def _safe_connect_signals(self):
		"""FIXED: Safely connect signals with error handling and recursion guards"""
		try:
			if not self._is_destroyed and not self._signals_connected:
				self.itemSelectionChanged.connect(self._on_selection_changed)
				self._signals_connected = True
		except Exception as e:
			print(f"Warning: Failed to connect selection signal: {e}")
	
	def cleanup(self):
		"""FIXED: Clean up resources and disconnect signals safely"""
		if self._is_destroyed:
			return
		
		self._is_destroyed = True
		# Block signals to prevent any last-minute events on a widget that is being destroyed.
		# Qt's object ownership model will handle the actual disconnection of signals
		# when this widget is deleted by its parent or by deleteLater().
		self.blockSignals(True)
	
	def closeEvent(self, event):
		"""Handle widget close event"""
		self.cleanup()
		super().closeEvent(event)
	
	def mouseDoubleClickEvent(self, event: QMouseEvent):
		"""FIXED: Stack overflow prevention in mouse events"""
		if self._is_destroyed or self._in_mouse_event:
			return
		
		try:
			self._in_mouse_event = True
			
			if event.button() == Qt.MouseButton.RightButton:
				self._emit_safe_signal(lambda: self.navigateUpRequested.emit())
				event.accept()
			else:
				# Let the base class handle left double-clicks
				super().mouseDoubleClickEvent(event)
		except Exception as e:
			print(f"Error in mouseDoubleClickEvent: {e}")
		finally:
			self._in_mouse_event = False
	
	def keyPressEvent(self, event: QKeyEvent):
		"""FIXED: Stack overflow prevention in keyboard events"""
		if self._is_destroyed or self._in_key_event:
			return
		
		try:
			self._in_key_event = True
			
			key = event.key()
			modifiers = event.modifiers()
			
			# Get currently selected items
			selected_items = self.selectedItems()
			current_item = self.currentItem()
			
			if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
				# Drill down into selected item
				if current_item:
					self._add_to_history()
					self._emit_safe_signal(lambda: self.drillDownRequested.emit(current_item))
					event.accept()
					return
			
			elif key == Qt.Key.Key_Backspace:
				# Navigate up one level
				self._emit_safe_signal(lambda: self.navigateUpRequested.emit())
				event.accept()
				return
			
			elif key == Qt.Key.Key_Space:
				# Mark selected items as sorted
				if selected_items:
					self._emit_safe_signal(lambda: self.markAsortedRequested.emit(selected_items))
					event.accept()
					return
			
			elif key == Qt.Key.Key_F2:
				# Show item details
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
					if first_item:
						self.setCurrentItem(first_item)
					event.accept()
					return
			
			elif key == Qt.Key.Key_End:
				# Go to last item
				if self.topLevelItemCount() > 0:
					last_item = self.topLevelItem(self.topLevelItemCount() - 1)
					if last_item:
						self.setCurrentItem(last_item)
					event.accept()
					return
			
			elif key == Qt.Key.Key_A and modifiers & Qt.KeyboardModifier.ControlModifier:
				# Select all items (Ctrl+A)
				self.selectAll()
				event.accept()
				return
			
			elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
				# Quick navigation by first letter
				if not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
					letter = chr(key).upper()
					self._navigate_to_letter(letter)
					event.accept()
					return
			
			# If no custom handling, pass to parent
			super().keyPressEvent(event)
		
		except Exception as e:
			print(f"Error in keyPressEvent: {e}")
			# Always call parent to prevent event system issues
			try:
				super().keyPressEvent(event)
			except:
				pass
		finally:
			self._in_key_event = False
	
	def _emit_safe_signal(self, emit_func):
		"""FIXED: Safely emit signals with recursion prevention"""
		if self._is_destroyed or self._signal_emission_blocked:
			return
		
		try:
			self._signal_emission_blocked = True
			# Emit after a short delay to break recursion chains
			QTimer.singleShot(10, lambda: self._do_emit(emit_func))
		except Exception as e:
			print(f"Error in _emit_safe_signal: {e}")
	
	def _do_emit(self, emit_func):
		"""Actually emit the signal"""
		try:
			if not self._is_destroyed:
				emit_func()
		except Exception as e:
			print(f"Error emitting signal: {e}")
		finally:
			self._signal_emission_blocked = False
	
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
	
	def _on_selection_changed(self):
		"""FIXED: Stack overflow prevention in selection change handling"""
		if (self._is_destroyed or not hasattr(self, '_is_connected') or
				not self._is_connected or self._in_selection_change):
			return
		
		try:
			self._in_selection_change = True
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
		finally:
			self._in_selection_change = False
	
	def mousePressEvent(self, event):
		"""FIXED: Stack overflow prevention in mouse press events"""
		if self._is_destroyed or self._in_mouse_event:
			return
		
		try:
			self._in_mouse_event = True
			super().mousePressEvent(event)
			
			# Update tooltip based on what was clicked
			if event.button() == Qt.MouseButton.LeftButton:
				item = self.itemAt(event.pos())
				if item:
					self._show_item_details(item)
		except Exception as e:
			print(f"Error in mousePressEvent: {e}")
		finally:
			self._in_mouse_event = False
	
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

	def _populate_tree_progressively(self, nodes, parent_item=None, chunk_size=100):
		"""FIXED: Populates the tree in chunks to prevent stack overflow"""
		if self._is_destroyed:
			return

		if parent_item is None:
			parent_item = self.invisibleRootItem()

		chunk = nodes[:chunk_size]
		remaining_nodes = nodes[chunk_size:]

		for node in chunk:
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

		if remaining_nodes:
			QTimer.singleShot(0, lambda: self._populate_tree_progressively(remaining_nodes, parent_item, chunk_size))
		else:
			# This is the last chunk, now we can sort.
			self.sortByColumn(self.sortColumn(), self.header().sortIndicatorOrder())

class StatusAwareWidget(QObject):
	"""FIXED: Mixin class for widgets that provide status updates"""
	
	def __init__(self, parent=None):
		super().__init__(parent)
		self._status_message = ""
		self._status_timeout = 0
	
	def set_status_message(self, message: str, timeout: int = 0):
		"""Set a status message that can be displayed in UI"""
		try:
			self._status_message = str(message)
			self._status_timeout = max(0, int(timeout))
		except:
			self._status_message = ""
			self._status_timeout = 0
	
	def get_status_message(self) -> str:
		"""Get the current status message"""
		return getattr(self, '_status_message', "")
	
	def clear_status_message(self):
		"""Clear the current status message"""
		self._status_message = ""
		self._status_timeout = 0
