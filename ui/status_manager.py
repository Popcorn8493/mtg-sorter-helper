"""
Status Manager for centralized status message handling.

This module provides a StatusManager class that centralizes status message
display logic with consistent styling patterns across the application.
"""

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import QTimer
from typing import Optional


class StatusManager:
    """
    Centralized status message manager with consistent styling.

    Provides a unified interface for displaying status messages with
    appropriate visual feedback based on message content and type.
    """

    # Predefined style constants for different message types
    STYLES = {
        'success': "color: #4CAF50; font-weight: bold;",
        'error': "color: #f44336; font-weight: bold;",
        'warning': "color: #FFC107; font-weight: bold;",
        'info': "color: #2196F3; font-weight: bold;",
        'default': "color: #FFC107; font-weight: normal;"
    }

    # Keyword mappings for automatic style detection
    KEYWORD_MAPPINGS = {
        'success': ['drill', 'navigat', 'complete', 'finished', 'saved',
                    'loaded'],
        'error': ['error', 'fail', 'failed', 'exception', 'critical'],
        'warning': ['warning', 'caution', 'notice', 'attention'],
        'info': ['sort', 'mark', 'process', 'analyze', 'fetch', 'update']
    }

    def __init__(self, status_label: QLabel):
        """
        Initialize the StatusManager with a QLabel for display.

        Args:
            status_label: The QLabel widget to display status messages
        """
        self.status_label = status_label
        self._current_timer: Optional[QTimer] = None

    def show(self, message: str, style: str = 'auto',
             timeout: int = 2500) -> None:
        """
        Display a status message with optional styling and timeout.

        Args:
            message: The message to display
            style: Style type ('auto', 'success', 'error', 'warning',
                   'info', 'default') or custom CSS string. 'auto' detects
                   style from message content.
            timeout: Time in milliseconds before clearing the message
                     (0 = no timeout)
        """
        if not self.status_label:
            return

        # Clear any existing timer
        if self._current_timer:
            self._current_timer.stop()
            self._current_timer = None

        # Set the message text
        self.status_label.setText(message)

        # Determine the style to use
        if style == 'auto':
            style = self._detect_style_from_message(message)

        # Apply the style
        if style in self.STYLES:
            self.status_label.setStyleSheet(self.STYLES[style])
        else:
            # Custom CSS string
            self.status_label.setStyleSheet(style)

        # Set up timeout if specified
        if timeout > 0:
            self._current_timer = QTimer()
            self._current_timer.timeout.connect(self._clear_message)
            self._current_timer.setSingleShot(True)
            self._current_timer.start(timeout)

    def _detect_style_from_message(self, message: str) -> str:
        """
        Automatically detect the appropriate style based on message content.

        Args:
            message: The message to analyze

        Returns:
            The detected style type
        """
        message_lower = message.lower()

        for style_type, keywords in self.KEYWORD_MAPPINGS.items():
            if any(keyword in message_lower for keyword in keywords):
                return style_type

        return 'default'

    def _clear_message(self) -> None:
        """Clear the current status message and reset styling."""
        if self.status_label:
            self.status_label.setText("")
            self.status_label.setStyleSheet("")

        if self._current_timer:
            self._current_timer.stop()
            self._current_timer = None

    def clear(self) -> None:
        """Manually clear the current status message."""
        self._clear_message()

    def show_success(self, message: str, timeout: int = 2500) -> None:
        """Show a success message with green styling."""
        self.show(message, 'success', timeout)

    def show_error(self, message: str, timeout: int = 3000) -> None:
        """Show an error message with red styling."""
        self.show(message, 'error', timeout)

    def show_warning(self, message: str, timeout: int = 2500) -> None:
        """Show a warning message with yellow styling."""
        self.show(message, 'warning', timeout)

    def show_info(self, message: str, timeout: int = 2500) -> None:
        """Show an info message with blue styling."""
        self.show(message, 'info', timeout)

    def show_custom(self, message: str, css_style: str,
                    timeout: int = 2500) -> None:
        """Show a message with custom CSS styling."""
        self.show(message, css_style, timeout)

    def is_displaying(self) -> bool:
        """Check if a status message is currently being displayed."""
        return bool(self.status_label and self.status_label.text().strip())

    def get_current_message(self) -> str:
        """Get the currently displayed message."""
        return self.status_label.text() if self.status_label else ""


class StatusAwareMixin:
    """
    Mixin class that provides status management capabilities to any widget.

    This mixin can be used to add status message functionality to any widget
    that has a status_label attribute.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._status_manager: Optional[StatusManager] = None

    def _init_status_manager(self) -> None:
        """Initialize the status manager if a status_label exists."""
        if hasattr(self, 'status_label') and self.status_label:
            self._status_manager = StatusManager(self.status_label)

    def show_status_message(self, message: str,
                            timeout: int = 2500, style: str = 'auto') -> None:
        """
        Show a status message using the status manager.

        This method provides backward compatibility with existing code.

        Args:
            message: The message to display
            timeout: Time in milliseconds before clearing the message
            style: Style type ('auto', 'success', 'error', 'warning',
                   'info', 'default')
        """
        if not self._status_manager:
            self._init_status_manager()

        if self._status_manager:
            self._status_manager.show(message, style, timeout)
        elif hasattr(self, 'status_label') and self.status_label:
            # Fallback to direct label manipulation
            self.status_label.setText(message)
            if timeout > 0:
                QTimer.singleShot(timeout, lambda: self.status_label.setText(""))

    def get_status_manager(self) -> Optional[StatusManager]:
        """Get the status manager instance."""
        if not self._status_manager:
            self._init_status_manager()
        return self._status_manager