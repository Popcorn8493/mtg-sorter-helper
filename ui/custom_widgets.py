from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget, QVBoxLayout, QLabel, QPushButton
from core.decorators import safe_signal_method

class SortableTreeWidgetItem(QTreeWidgetItem):

    def __lt__(self, other):
        if not isinstance(other, QTreeWidgetItem):
            return NotImplemented
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        try:
            if column == 1:
                self_text = self.text(column)
                other_text = other.text(column)
                if not self_text:
                    return True
                if not other_text:
                    return False
                self_value = int(self_text)
                other_value = int(other_text)
                return self_value < other_value
        except (ValueError, IndexError):
            pass
        self_text = self.text(column).lower()
        other_text = other.text(column).lower()
        if ': ' in self_text and ': ' in other_text:
            try:
                self_suffix = self_text.split(': ', 1)[1]
                other_suffix = other_text.split(': ', 1)[1]
                return self_suffix < other_suffix
            except IndexError:
                pass
        return self_text < other_text

class NavigableTreeWidget(QTreeWidget):
    drillDownRequested = pyqtSignal(QTreeWidgetItem)
    navigateUpRequested = pyqtSignal()
    markAsortedRequested = pyqtSignal(list)
    itemSortedToggled = pyqtSignal(QTreeWidgetItem, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_destroyed = False
        self._signals_connected = False
        self._signals_blocked_count = 0
        self._in_operation = False
        self.navigation_history = []
        self.max_history_size = 10
        self._operation_timer = QTimer()
        self._operation_timer.timeout.connect(self._process_pending_operations)
        self._operation_timer.setSingleShot(True)
        self._pending_operations = []
        self._populate_timer = QTimer()
        self._populate_timer.timeout.connect(self._process_next_chunk)
        self._populate_timer.setSingleShot(False)
        self._populate_state = {'nodes': [], 'parent_item': None, 'chunk_size': 100, 'on_finished': None, 'current_index': 0, 'active': False}
        self.setToolTip("Keyboard Navigation:\n• Enter/Return - Drill down into selected group\n• Backspace - Navigate back up one level\n• Space - Mark selected group(s) as sorted\n• Ctrl+A - Select all items\n• Arrow keys - Navigate between items\n• F2 - Show item details (if available)\n\nMouse:\n• Click checkbox - Mark group as sorted/unsorted\n• Click item name - Select item\n• Double-click - Drill down into group\n• Right-click - Context menu (if available)\n\nNote: Sorted items are hidden unless 'Show Sorted' is checked")
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._connect_signals()

    @safe_signal_method('Signal connection failed')
    def _connect_signals(self):
        if self._is_destroyed or self._signals_connected:
            return
        self.blockSignals(True)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.itemChanged.connect(self._on_item_changed)
        self.blockSignals(False)
        self._signals_connected = True

    @safe_signal_method('Signal blocking failed')
    def _block_signals(self):
        self._signals_blocked_count += 1
        if self._signals_blocked_count == 1:
            self.blockSignals(True)

    @safe_signal_method('Signal unblocking failed')
    def _unblock_signals(self):
        self._signals_blocked_count = max(0, self._signals_blocked_count - 1)
        if self._signals_blocked_count == 0:
            self.blockSignals(False)

    def _queue_operation(self, operation_func, delay_ms=10):
        if self._is_destroyed:
            return
        self._pending_operations.append(operation_func)
        if not self._operation_timer.isActive():
            self._operation_timer.start(delay_ms)

    def _process_pending_operations(self):
        if self._is_destroyed or not self._pending_operations:
            return
        operation = self._pending_operations.pop(0)
        try:
            operation()
        except Exception as e:
            print(f'Error processing pending operation: {e}')
        if self._pending_operations and (not self._is_destroyed):
            self._operation_timer.start(10)

    def cleanup(self):
        if self._is_destroyed:
            return
        self._is_destroyed = True
        if hasattr(self, '_operation_timer'):
            self._operation_timer.stop()
        if hasattr(self, '_pending_operations'):
            self._pending_operations.clear()
        if hasattr(self, '_populate_timer'):
            self._populate_timer.stop()
        if hasattr(self, '_populate_state'):
            self._populate_state['active'] = False
            self._populate_state['nodes'].clear()
        self.blockSignals(True)

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None):
        if self._is_destroyed or self._in_operation or (not event):
            return
        try:
            self._in_operation = True
            item = self.itemAt(event.pos())
            if item and event.button() == Qt.MouseButton.LeftButton:
                item_rect = self.visualItemRect(item)
                depth = 0
                parent = item.parent()
                while parent is not None:
                    depth += 1
                    parent = parent.parent()
                indent_offset = self.indentation() * depth
                checkbox_start = item_rect.left() + indent_offset
                checkbox_end = checkbox_start + 20
                if event.pos().x() >= checkbox_start and event.pos().x() <= checkbox_end:
                    event.accept()
                    return
            if event.button() == Qt.MouseButton.RightButton:
                self._emit_signal(lambda: self.navigateUpRequested.emit())
                event.accept()
            else:
                super().mouseDoubleClickEvent(event)
        except Exception as e:
            print(f'Error in mouseDoubleClickEvent: {e}')
        finally:
            self._in_operation = False

    def keyPressEvent(self, event: QKeyEvent | None):
        if self._is_destroyed or self._in_operation or (not event):
            return
        try:
            self._in_operation = True
            if self._handle_item_action_keys(event) or self._handle_navigation_keys(event) or self._handle_selection_keys(event):
                event.accept()
                return
            super().keyPressEvent(event)
        except Exception as e:
            print(f'Error in keyPressEvent: {e}')
            try:
                super().keyPressEvent(event)
            except Exception:
                pass
        finally:
            self._in_operation = False

    def _handle_item_action_keys(self, event: QKeyEvent | None) -> bool:
        if not event:
            return False
        key = event.key()
        current_item = self.currentItem()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if current_item:
                self._add_to_history()
                self._emit_signal(lambda: self.drillDownRequested.emit(current_item))
                return True
        elif key == Qt.Key.Key_Space:
            selected_items = self.selectedItems()
            if selected_items:
                self._emit_signal(lambda: self.markAsortedRequested.emit(selected_items))
                return True
        elif key == Qt.Key.Key_F2:
            if current_item:
                self._show_item_details(current_item)
                return True
        return False

    def _handle_navigation_keys(self, event: QKeyEvent | None) -> bool:
        if not event:
            return False
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Backspace:
            self._emit_signal(lambda: self.navigateUpRequested.emit())
            return True
        elif key == Qt.Key.Key_Home:
            if self.topLevelItemCount() > 0:
                item = self.topLevelItem(0)
                if item:
                    self._block_signals()
                    try:
                        self.setCurrentItem(item)
                    finally:
                        self._unblock_signals()
                return True
        elif key == Qt.Key.Key_End:
            if self.topLevelItemCount() > 0:
                item = self.topLevelItem(self.topLevelItemCount() - 1)
                if item:
                    self._block_signals()
                    try:
                        self.setCurrentItem(item)
                    finally:
                        self._unblock_signals()
                return True
        elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            if not modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
                letter = chr(key).upper()
                self._navigate_to_letter(letter)
                return True
        return False

    def _handle_selection_keys(self, event: QKeyEvent | None) -> bool:
        if not event:
            return False
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Escape:
            self._block_signals()
            try:
                self.clearSelection()
            finally:
                self._unblock_signals()
            return True
        elif key == Qt.Key.Key_A and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._block_signals()
            try:
                self.selectAll()
            finally:
                self._unblock_signals()
            return True
        return False

    @safe_signal_method('Signal emission failed')
    def _emit_signal(self, emit_func):
        if self._is_destroyed:
            return
        self._queue_operation(emit_func, 20)

    def _add_to_history(self):
        if self._is_destroyed:
            return
        try:
            current_item = self.currentItem()
            if current_item:
                item_text = current_item.text(0)
                self.navigation_history.append(item_text)
                if len(self.navigation_history) > self.max_history_size:
                    self.navigation_history.pop(0)
        except Exception as e:
            print(f'Error adding to history: {e}')

    def _show_item_details(self, item: QTreeWidgetItem):
        if self._is_destroyed or not item:
            return
        try:
            details = [f'Group: {item.text(0)}']
            if item.columnCount() > 1:
                details.append(f'Count: {item.text(1)}')
            item_data = item.data(0, Qt.ItemDataRole.UserRole)
            if item_data and isinstance(item_data, list) and (len(item_data) > 0):
                card_count = len(item_data)
                details.append(f'Contains {card_count} unique cards')
                if hasattr(item_data[0], 'type_line'):
                    type_counts: dict[str, int] = {}
                    for card in item_data:
                        try:
                            card_type = card.type_line.split('—')[0].strip()
                            type_counts[card_type] = type_counts.get(card_type, 0) + 1
                        except Exception:
                            pass
                    if type_counts:
                        details.append('Types: ' + ', '.join((f'{t}({c})' for t, c in sorted(type_counts.items()))))
            tooltip_text = '\n'.join(details)
            self.setToolTip(tooltip_text)
        except Exception as e:
            print(f'Error showing item details: {e}')

    def _navigate_to_letter(self, letter: str):
        if self._is_destroyed:
            return
        try:
            self._block_signals()
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                if item:
                    item_text = item.text(0).upper()
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
            print(f'Error navigating to letter: {e}')
        finally:
            self._unblock_signals()

    @safe_signal_method('Selection change handling failed')
    def _on_selection_changed(self):
        if self._is_destroyed or not self._signals_connected or self._in_operation:
            return
        self._queue_operation(self._do_selection_changed, 5)

    def _do_selection_changed(self):
        if self._is_destroyed:
            return
        try:
            selected_count = len(self.selectedItems())
            if selected_count == 0:
                tooltip = 'No items selected.\n\nUse arrow keys to navigate, Enter to drill down, Space to mark as sorted.'
            elif selected_count == 1:
                current = self.currentItem()
                if current:
                    tooltip = f'Selected: {current.text(0)}\n\nEnter - Drill down\nSpace - Mark as sorted\nBackspace - Go back'
                else:
                    tooltip = '1 item selected'
            else:
                tooltip = f'{selected_count} items selected\n\nSpace - Mark all selected as sorted\nEscape - Clear selection'
            self.setToolTip(tooltip)
        except Exception as e:
            print(f'Error in selection changed handler: {e}')

    def mousePressEvent(self, event: QMouseEvent | None):
        if self._is_destroyed or not event:
            return
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                item = self.itemAt(event.pos())
                if item:
                    item_rect = self.visualItemRect(item)
                    depth = 0
                    parent = item.parent()
                    while parent is not None:
                        depth += 1
                        parent = parent.parent()
                    indent_offset = self.indentation() * depth
                    checkbox_start = item_rect.left() + indent_offset
                    checkbox_end = checkbox_start + 20
                    if event.pos().x() >= checkbox_start and event.pos().x() <= checkbox_end:
                        self._handle_checkbox_click(item)
                        event.accept()
                        return
            super().mousePressEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                item = self.itemAt(event.pos())
                if item:
                    self._queue_operation(lambda: self._show_item_details(item), 50)
        except Exception as e:
            print(f'Error in mousePressEvent: {e}')

    def get_navigation_history(self):
        try:
            return self.navigation_history.copy() if not self._is_destroyed else []
        except Exception:
            return []

    def clear_navigation_history(self):
        try:
            if not self._is_destroyed:
                self.navigation_history.clear()
        except Exception:
            self.navigation_history = []

    def _populate_tree_progressively(self, nodes, parent_item=None, chunk_size=100, on_finished=None):
        if self._is_destroyed:
            print('DEBUG: _populate_tree_progressively aborted - widget destroyed')
            return
        if self._populate_state['active']:
            print('DEBUG: Stopping existing population to start new one')
            self._populate_timer.stop()
            self._populate_state['active'] = False
        if parent_item is None:
            parent_item = self.invisibleRootItem()
        self._populate_state = {'nodes': nodes, 'parent_item': parent_item, 'chunk_size': chunk_size, 'on_finished': on_finished, 'current_index': 0, 'active': True}
        print(f'DEBUG: Starting progressive population with {len(nodes)} nodes')
        self._populate_timer.start(1)

    def _process_next_chunk(self):
        if self._is_destroyed or not self._populate_state['active']:
            if self._populate_timer.isActive():
                self._populate_timer.stop()
            return
        state = self._populate_state
        nodes = state['nodes']
        parent_item = state['parent_item']
        chunk_size = state['chunk_size']
        current_index = state['current_index']
        chunk_start = current_index
        chunk_end = min(current_index + chunk_size, len(nodes))
        remaining = len(nodes) - chunk_end
        print(f'DEBUG: Processing chunk {chunk_start}-{chunk_end} of {len(nodes)} nodes, {remaining} remaining')
        try:
            for i in range(chunk_start, chunk_end):
                try:
                    node = nodes[i]
                    tree_item = SortableTreeWidgetItem(parent_item, [node.group_name, str(node.count)])
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, node.cards)
                    tree_item.setFlags(tree_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    if hasattr(node, 'cards') and node.cards:
                        all_sorted = all((c.is_fully_sorted for c in node.cards))
                        if all_sorted:
                            tree_item.setCheckState(0, Qt.CheckState.Checked)
                            for col in range(2):
                                tree_item.setForeground(col, QColor(128, 128, 128))
                            parent_widget = self.parent()
                            while parent_widget and (not hasattr(parent_widget, 'show_sorted_check')):
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
                    print(f'ERROR: Failed to process node {i}: {e}')
                    continue
        except Exception as e:
            print(f'ERROR: Failed during chunk processing: {e}')
            import traceback
            traceback.print_exc()
            self._populate_timer.stop()
            state['active'] = False
            return
        state['current_index'] = chunk_end
        if chunk_end >= len(nodes):
            print('DEBUG: Final chunk completed, running final actions...')
            self._populate_timer.stop()
            state['active'] = False
            self._finalize_population()

    def _finalize_population(self):
        if self._is_destroyed:
            print('DEBUG: _finalize_population aborted - widget destroyed')
            return
        try:
            print('DEBUG: Sorting tree...')
            self.sortByColumn(self.sortColumn(), self.header().sortIndicatorOrder())
            print('DEBUG: Tree sorted, calling on_finished callback...')
            on_finished = self._populate_state.get('on_finished')
            if on_finished:
                try:
                    on_finished()
                    print('DEBUG: on_finished callback completed')
                except Exception as e:
                    print(f'ERROR: on_finished callback failed: {e}')
                    import traceback
                    traceback.print_exc()
        except Exception as e:
            print(f'ERROR: _finalize_population failed: {e}')
            import traceback
            traceback.print_exc()

    def _on_item_changed(self, item, column):
        if self._is_destroyed or not item or column != 0:
            return
        try:
            if hasattr(item, 'checkState'):
                current_state = item.checkState(0)
                is_sorted = current_state == Qt.CheckState.Checked
                self.itemSortedToggled.emit(item, is_sorted)
        except Exception as e:
            print(f'Error handling item change: {e}')

    def _handle_checkbox_click(self, item):
        if self._is_destroyed or not item:
            return
        try:
            current_state = item.checkState(0)
            if current_state == Qt.CheckState.Checked:
                new_state = Qt.CheckState.Unchecked
                is_sorted = False
            else:
                new_state = Qt.CheckState.Checked
                is_sorted = True
            item.setCheckState(0, new_state)
            self.itemSortedToggled.emit(item, is_sorted)
        except Exception as e:
            print(f'Error handling checkbox click: {e}')

    def set_item_sorted_state(self, item, is_sorted):
        if not item:
            return
        try:
            self.blockSignals(True)
            if is_sorted:
                item.setCheckState(0, Qt.CheckState.Checked)
                for col in range(self.columnCount()):
                    item.setForeground(col, QColor(128, 128, 128))
            else:
                item.setCheckState(0, Qt.CheckState.Unchecked)
                for col in range(self.columnCount()):
                    item.setForeground(col, QColor(255, 255, 255))
            self.blockSignals(False)
        except Exception as e:
            print(f'Error setting item sorted state: {e}')
            self.blockSignals(False)

class StatusAwareWidget(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status_message = ''
        self._status_timeout = 0
        self._is_destroyed = False

    def cleanup(self):
        self._is_destroyed = True
        self._status_message = ''
        self._status_timeout = 0

    def set_status_message(self, message: str, timeout: int=0):
        if self._is_destroyed:
            return
        try:
            self._status_message = str(message) if message is not None else ''
            self._status_timeout = max(0, int(timeout)) if timeout is not None else 0
        except Exception as e:
            print(f'Error setting status message: {e}')
            self._status_message = ''
            self._status_timeout = 0

    def get_status_message(self) -> str:
        if self._is_destroyed:
            return ''
        return getattr(self, '_status_message', '')

    def clear_status_message(self):
        if not self._is_destroyed:
            self._status_message = ''
            self._status_timeout = 0

class EmptyState(QWidget):

    def __init__(self, title: str, message: str, action_text: str=None, action_callback=None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet('font-size: 16pt; font-weight: bold;')
        layout.addWidget(title_label)
        message_label = QLabel(message)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setMaximumWidth(400)
        message_label.setStyleSheet('font-size: 11pt; color: #888;')
        layout.addWidget(message_label)
        if action_text and action_callback:
            action_button = QPushButton(action_text)
            action_button.setObjectName('AccentButton')
            action_button.clicked.connect(action_callback)
            action_button.setMaximumWidth(200)
            layout.addWidget(action_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()