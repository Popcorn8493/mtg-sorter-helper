# ui/widget_factory.py - Widget Factory Pattern for UI Creation

from typing import Dict, Optional, List
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QProgressBar, QPushButton,
                             QSplitter, QStackedWidget, QWidget, QTreeWidget,
                             QVBoxLayout)


class WidgetConfig:
    """Configuration class for widget creation with all necessary properties."""

    def __init__(self, widget_class, name: str, **kwargs):
        self.widget_class = widget_class
        self.name = name
        self.properties = kwargs.get('properties', {})
        self.connections = kwargs.get('connections', {})
        self.tooltip = kwargs.get('tooltip', '')
        self.object_name = kwargs.get('object_name', '')
        self.visible = kwargs.get('visible', True)
        self.enabled = kwargs.get('enabled', True)
        self.stretch = kwargs.get('stretch', 0)
        self.alignment = kwargs.get('alignment', None)
        self.min_size = kwargs.get('min_size', None)
        self.max_size = kwargs.get('max_size', None)
        self.items = kwargs.get('items', [])
        self.placeholder = kwargs.get('placeholder', '')
        self.text = kwargs.get('text', '')
        self.checked = kwargs.get('checked', False)
        self.range = kwargs.get('range', None)
        self.orientation = kwargs.get('orientation', None)
        self.drag_drop_mode = kwargs.get('drag_drop_mode', None)
        self.selection_mode = kwargs.get('selection_mode', None)
        self.header_labels = kwargs.get('header_labels', [])
        self.sizes = kwargs.get('sizes', [])
        self.word_wrap = kwargs.get('word_wrap', False)
        self.scroll_policy = kwargs.get('scroll_policy', None)
        self.resize_mode = kwargs.get('resize_mode', None)
        self.decorated = kwargs.get('decorated', None)
        self.sorting_enabled = kwargs.get('sorting_enabled', None)
        self.auto_fill_background = kwargs.get('auto_fill_background', None)
        self.style_sheet = kwargs.get('style_sheet', '')


class WidgetFactory:
    """Factory class for creating and configuring PyQt6 widgets."""

    def __init__(self, parent_widget: QWidget):
        """
        Initialize the widget factory.

        Args:
            parent_widget: The parent widget that will own the created widgets.
        """
        self.parent_widget = parent_widget
        self.created_widgets: Dict[str, QWidget] = {}

    def create_widget(self, config: WidgetConfig) -> QWidget:
        """
        Create a widget based on the provided configuration.

        Args:
            config: WidgetConfig object containing widget creation parameters.

        Returns:
            The created and configured widget.
        """
        try:
            # Create the widget instance
            widget = config.widget_class(self.parent_widget)

            # Set basic properties
            if config.object_name:
                widget.setObjectName(config.object_name)

            if config.tooltip:
                widget.setToolTip(config.tooltip)

            widget.setVisible(config.visible)
            widget.setEnabled(config.enabled)

            # Set size constraints
            if config.min_size:
                widget.setMinimumSize(*config.min_size)

            if config.max_size:
                widget.setMaximumSize(*config.max_size)

            # Set alignment if specified
            if config.alignment:
                widget.setAlignment(config.alignment)

            # Widget-specific configurations
            self._configure_widget_specific(widget, config)

            # Set custom properties
            for prop_name, prop_value in config.properties.items():
                if hasattr(widget, prop_name):
                    setattr(widget, prop_name, prop_value)

            # Connect signals
            for signal_name, slot in config.connections.items():
                if hasattr(widget, signal_name):
                    signal = getattr(widget, signal_name)
                    signal.connect(slot)

            # Store the widget for later reference
            self.created_widgets[config.name] = widget

            return widget

        except Exception as e:
            print(f"Error creating widget '{config.name}': {e}")
            raise

    def _configure_widget_specific(self, widget: QWidget, config: WidgetConfig):
        """Configure widget-specific properties."""

        # QLabel specific
        if isinstance(widget, QLabel):
            if config.text:
                widget.setText(config.text)
            if config.word_wrap:
                widget.setWordWrap(config.word_wrap)

        # QLineEdit specific
        elif isinstance(widget, QLineEdit):
            if config.text:
                widget.setText(config.text)
            if config.placeholder:
                widget.setPlaceholderText(config.placeholder)

        # QPushButton specific
        elif isinstance(widget, QPushButton):
            if config.text:
                widget.setText(config.text)

        # QCheckBox specific
        elif isinstance(widget, QCheckBox):
            if config.text:
                widget.setText(config.text)
            widget.setChecked(config.checked)

        # QListWidget specific
        elif isinstance(widget, QListWidget):
            if config.items:
                widget.addItems(config.items)
            if config.drag_drop_mode:
                widget.setDragDropMode(config.drag_drop_mode)
            if config.selection_mode:
                widget.setSelectionMode(config.selection_mode)

        # QProgressBar specific
        elif isinstance(widget, QProgressBar):
            if config.range:
                widget.setRange(*config.range)

        # QSplitter specific
        elif isinstance(widget, QSplitter):
            if config.orientation:
                widget.setOrientation(config.orientation)
            if config.sizes:
                widget.setSizes(config.sizes)

        # QTreeWidget specific
        elif isinstance(widget, QTreeWidget):
            if config.header_labels:
                widget.setHeaderLabels(config.header_labels)
            if config.selection_mode:
                widget.setSelectionMode(config.selection_mode)
            if config.decorated is not None:
                widget.setRootIsDecorated(config.decorated)
            if config.sorting_enabled is not None:
                widget.setSortingEnabled(config.sorting_enabled)

        # QStackedWidget specific
        elif isinstance(widget, QStackedWidget):
            pass  # No specific configuration needed

        # Layout specific configurations
        elif isinstance(widget, (QHBoxLayout, QVBoxLayout)):
            if config.alignment:
                widget.setAlignment(config.alignment)

        # Apply style sheet if provided
        if config.style_sheet:
            widget.setStyleSheet(config.style_sheet)

    def get_widget(self, name: str) -> Optional[QWidget]:
        """Get a previously created widget by name."""
        return self.created_widgets.get(name)

    def get_all_widgets(self) -> Dict[str, QWidget]:
        """Get all created widgets."""
        return self.created_widgets.copy()

    def clear_widgets(self):
        """Clear all widget references."""
        self.created_widgets.clear()


class SorterTabWidgetConfigs:
    """Configuration definitions for all SorterTab widgets."""
    
    @staticmethod
    def get_import_section_configs() -> List[WidgetConfig]:
        """Get widget configurations for the import section."""
        return [
            WidgetConfig(
                widget_class=QPushButton,
                name="import_button",
                text="Import ManaBox CSV",
                object_name="AccentButton",
                tooltip="Import a ManaBox CSV export file containing your collection "
                        "(Shortcut: Ctrl+O)",
                connections={"clicked": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QPushButton,
                name="reset_progress_button",
                text="Reset Progress",
                tooltip="Resets the sorting progress for all cards in the current collection.",
                connections={"clicked": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QLabel,
                name="file_label",
                text="No file loaded.",
                alignment=Qt.AlignmentFlag.AlignCenter,
                tooltip="Shows the currently loaded collection file and status"
            ),
            WidgetConfig(
                widget_class=QProgressBar,
                name="progress_bar",
                visible=False,
                tooltip="Shows progress of card data fetching from Scryfall"
            )
        ]
    
    @staticmethod
    def get_options_section_configs() -> List[WidgetConfig]:
        """Get widget configurations for the options section."""
        return [
            WidgetConfig(
                widget_class=QListWidget,
                name="available_list",
                items=["Set", "Color Identity", "Rarity", "Type Line", "First Letter",
                       "Name", "Condition", "Commander Staple"],
                tooltip="Available sorting criteria. Double-click an item to add it to "
                        "the sort order.",
                connections={"itemDoubleClicked": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QListWidget,
                name="selected_list",
                drag_drop_mode=QAbstractItemView.DragDropMode.InternalMove,
                tooltip="Your sorting hierarchy. Double-click an item to remove it. "
                        "Drag and drop to reorder.",
                connections={"itemDoubleClicked": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QCheckBox,
                name="group_low_count_check",
                text="Group low-count letters into piles",
                checked=True,
                tooltip="Combine letters with few cards into larger piles for more "
                        "efficient sorting"
            ),
            WidgetConfig(
                widget_class=QCheckBox,
                name="optimal_grouping_check",
                text="Optimal grouping (max 3 letters per group)",
                checked=False,
                tooltip="Use optimal algorithm to group letters with maximum of 3 "
                        "letters per pile for efficient physical sorting"
            ),
            WidgetConfig(
                widget_class=QLineEdit,
                name="group_threshold_edit",
                text="20",
                tooltip="Minimum number of cards per pile when grouping letters "
                        "together"
            )
        ]
    
    @staticmethod
    def get_run_section_configs() -> List[WidgetConfig]:
        """Get widget configurations for the run section."""
        return [
            WidgetConfig(
                widget_class=QPushButton,
                name="run_button",
                text="Generate Sorting Plan",
                tooltip="Create a visual sorting plan based on your criteria "
                        "(Shortcut: Ctrl+G)",
                connections={"clicked": None}  # Will be set by the factory user
            )
        ]
    
    @staticmethod
    def get_results_section_configs() -> List[WidgetConfig]:
        """Get widget configurations for the results section."""
        return [
            WidgetConfig(
                widget_class=QHBoxLayout,
                name="breadcrumb_layout",
                alignment=Qt.AlignmentFlag.AlignLeft
            ),
            WidgetConfig(
                widget_class=QCheckBox,
                name="show_sorted_check",
                text="Show Sorted Groups",
                tooltip="Include already-sorted cards in the display",
                connections={"stateChanged": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QPushButton,
                name="mark_sorted_button",
                text="Mark Group as Sorted",
                visible=False,
                tooltip="Mark all cards in the selected group(s) as sorted "
                        "(Shortcut: Space)",
                connections={"clicked": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QPushButton,
                name="export_button",
                text="Export View",
                visible=False,
                tooltip="Export the current view to a CSV file (Shortcut: Ctrl+E)",
                connections={"clicked": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QSplitter,
                name="main_splitter",
                orientation=Qt.Orientation.Horizontal,
                sizes=[700, 350]
            ),
            WidgetConfig(
                widget_class=QLineEdit,
                name="filter_edit",
                placeholder="Filter current view...",
                visible=False,
                tooltip="Type to filter the current view by group name",
                connections={"textChanged": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QStackedWidget,
                name="results_stack"
            ),
            WidgetConfig(
                widget_class=QWidget,
                name="preview_panel"
            ),
            WidgetConfig(
                widget_class=QLabel,
                name="card_image_label",
                text="Select an individual card to see its image.",
                object_name="CardImageLabel",
                alignment=Qt.AlignmentFlag.AlignCenter,
                min_size=(220, 308),
                tooltip="Card images appear here when you select individual cards"
            ),
            WidgetConfig(
                widget_class=QPushButton,
                name="fetch_image_button",
                text="Fetch Image",
                visible=False,
                tooltip="Download and display the image for the selected card.",
                connections={"clicked": None}  # Will be set by the factory user
            ),
            WidgetConfig(
                widget_class=QLabel,
                name="card_details_label",
                alignment=Qt.AlignmentFlag.AlignTop,
                tooltip="Detailed card information appears here",
                properties={"wordWrap": True}
            ),
            WidgetConfig(
                widget_class=QLabel,
                name="status_label",
                alignment=Qt.AlignmentFlag.AlignRight
            )
        ]
    
    @staticmethod
    def get_all_configs() -> Dict[str, List[WidgetConfig]]:
        """Get all widget configurations organized by section."""
        return {
            "import": SorterTabWidgetConfigs.get_import_section_configs(),
            "options": SorterTabWidgetConfigs.get_options_section_configs(),
            "run": SorterTabWidgetConfigs.get_run_section_configs(),
            "results": SorterTabWidgetConfigs.get_results_section_configs()
        }
