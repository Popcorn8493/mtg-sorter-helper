from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent

class SortableTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other):
        tree = self.treeWidget(); column = tree.sortColumn() if tree else 0
        try:
            if column == 1: return int(self.text(column)) < int(other.text(column))
        except (ValueError, IndexError): pass
        return self.text(column).lower() < other.text(column).lower()

class NavigableTreeWidget(QTreeWidget):
    """A QTreeWidget with keyboard navigation for drilling down and up."""
    drillDownRequested = pyqtSignal(QTreeWidgetItem)
    navigateUpRequested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if item := self.currentItem():
                self.drillDownRequested.emit(item)
        elif key == Qt.Key.Key_Backspace:
            self.navigateUpRequested.emit()
        else:
            super().keyPressEvent(event)
