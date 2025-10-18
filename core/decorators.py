from functools import wraps
from typing import Callable, Any

def safe_method(error_message: str='Operation failed', log_prefix: str='[UI]', return_value: Any=None, reraise: bool=False) -> Callable:

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                print(f'{log_prefix} {error_message}: {e}')
                if reraise:
                    raise
                return return_value
        return wrapper
    return decorator

def safe_ui_method(error_message: str='UI operation failed') -> Callable:
    return safe_method(error_message, '[UI]', None, False)

def safe_signal_method(error_message: str='Signal operation failed') -> Callable:
    return safe_method(error_message, '[SIGNAL]', None, False)

def safe_cleanup_method(error_message: str='Cleanup operation failed') -> Callable:
    return safe_method(error_message, '[CLEANUP]', None, False)