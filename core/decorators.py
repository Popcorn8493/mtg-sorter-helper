"""
Utility decorators for the MTG Toolkit application.
"""
from functools import wraps
from typing import Callable, Any, Optional


def safe_method(error_message: str = "Operation failed", 
                log_prefix: str = "[UI]", 
                return_value: Any = None,
                reraise: bool = False) -> Callable:
    """
    Decorator for safely executing methods with error handling.
    
    Args:
        error_message: Custom error message to display
        log_prefix: Prefix for log messages (default: "[UI]")
        return_value: Value to return on error (default: None)
        reraise: Whether to reraise the exception after logging (default: False)
    
    Returns:
        Decorated function with error handling
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                print(f"{log_prefix} {error_message}: {e}")
                if reraise:
                    raise
                return return_value
        return wrapper
    return decorator


def safe_ui_method(error_message: str = "UI operation failed") -> Callable:
    """
    Specialized decorator for UI methods with standard error handling.
    Uses "[UI]" prefix and returns None on error.
    """
    return safe_method(error_message, "[UI]", None, False)


def safe_signal_method(error_message: str = "Signal operation failed") -> Callable:
    """
    Specialized decorator for signal-related methods.
    Uses "[SIGNAL]" prefix and returns None on error.
    """
    return safe_method(error_message, "[SIGNAL]", None, False)


def safe_cleanup_method(error_message: str = "Cleanup operation failed") -> Callable:
    """
    Specialized decorator for cleanup methods.
    Uses "[CLEANUP]" prefix and returns None on error.
    """
    return safe_method(error_message, "[CLEANUP]", None, False)
