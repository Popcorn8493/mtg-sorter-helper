from typing import Optional
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel

class StatusManager:
    STYLES = {'success': 'color: #4CAF50; font-weight: bold;', 'error': 'color: #f44336; font-weight: bold;', 'warning': 'color: #FFC107; font-weight: bold;', 'info': 'color: #2196F3; font-weight: bold;', 'default': 'color: #FFC107; font-weight: normal;'}
    KEYWORD_MAPPINGS = {'success': ['drill', 'navigat', 'complete', 'finished', 'saved', 'loaded'], 'error': ['error', 'fail', 'failed', 'exception', 'critical'], 'warning': ['warning', 'caution', 'notice', 'attention'], 'info': ['sort', 'mark', 'process', 'analyze', 'fetch', 'update']}

    def __init__(self, status_label: QLabel):
        self.status_label = status_label
        self._current_timer: Optional[QTimer] = None

    def show(self, message: str, style: str='auto', timeout: int=2500) -> None:
        if not self.status_label:
            return
        if self._current_timer:
            self._current_timer.stop()
            self._current_timer = None
        self.status_label.setText(message)
        if style == 'auto':
            style = self._detect_style_from_message(message)
        if style in self.STYLES:
            self.status_label.setStyleSheet(self.STYLES[style])
        else:
            self.status_label.setStyleSheet(style)
        if timeout > 0:
            self._current_timer = QTimer()
            self._current_timer.timeout.connect(self._clear_message)
            self._current_timer.setSingleShot(True)
            self._current_timer.start(timeout)

    def _detect_style_from_message(self, message: str) -> str:
        message_lower = message.lower()
        for style_type, keywords in self.KEYWORD_MAPPINGS.items():
            if any((keyword in message_lower for keyword in keywords)):
                return style_type
        return 'default'

    def _clear_message(self) -> None:
        if self.status_label:
            self.status_label.setText('')
            self.status_label.setStyleSheet('')
        if self._current_timer:
            self._current_timer.stop()
            self._current_timer = None

    def clear(self) -> None:
        self._clear_message()

    def show_success(self, message: str, timeout: int=2500) -> None:
        self.show(message, 'success', timeout)

    def show_error(self, message: str, timeout: int=3000) -> None:
        self.show(message, 'error', timeout)

    def show_warning(self, message: str, timeout: int=2500) -> None:
        self.show(message, 'warning', timeout)

    def show_info(self, message: str, timeout: int=2500) -> None:
        self.show(message, 'info', timeout)

    def show_custom(self, message: str, css_style: str, timeout: int=2500) -> None:
        self.show(message, css_style, timeout)

    def is_displaying(self) -> bool:
        return bool(self.status_label and self.status_label.text().strip())

    def get_current_message(self) -> str:
        return self.status_label.text() if self.status_label else ''

class StatusAwareMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._status_manager: Optional[StatusManager] = None

    def _init_status_manager(self) -> None:
        if hasattr(self, 'status_label') and self.status_label:
            self._status_manager = StatusManager(self.status_label)

    def show_status_message(self, message: str, timeout: int=2500, style: str='auto') -> None:
        if not self._status_manager:
            self._init_status_manager()
        if self._status_manager:
            self._status_manager.show(message, style, timeout)
        elif hasattr(self, 'status_label') and self.status_label:
            self.status_label.setText(message)
            if timeout > 0:
                QTimer.singleShot(timeout, lambda: self.status_label.setText(''))

    def get_status_manager(self) -> Optional[StatusManager]:
        if not self._status_manager:
            self._init_status_manager()
        return self._status_manager