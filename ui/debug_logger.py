"""
Enhanced debugging and logging system for MTG Sorter Helper.

Provides structured logging, operation context tracking, and tab-specific
debugging responses for better observability.
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
import json


class DebugLevel(Enum):
    """Debug verbosity levels."""
    OFF = 0
    ERRORS_ONLY = 1
    NORMAL = 2
    VERBOSE = 3
    TRACE = 4


@dataclass
class DebugContext:
    """Context information for debug operations."""
    operation: str
    module: str
    start_time: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    depth: int = 0
    parent: Optional['DebugContext'] = None

    def add_metadata(self, key: str, value: Any):
        """Add metadata to the context."""
        self.metadata[key] = value

    def get_formatted_header(self) -> str:
        """Get formatted context header."""
        indent = "  " * self.depth
        return f"{indent}▶ {self.module}::{self.operation}"


@dataclass
class DebugResponse:
    """Structured debug response for operations."""
    operation: str
    success: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    context: Optional[DebugContext] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'operation': self.operation,
            'success': self.success,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp.isoformat(),
            'duration_ms': self.duration_ms,
        }

    def to_formatted_string(self) -> str:
        """Get formatted string representation."""
        status = "✓" if self.success else "✗"
        indent = "  " * (self.context.depth if self.context else 0)
        result = f"{indent}{status} {self.operation}"
        if self.duration_ms > 0:
            result += f" ({self.duration_ms:.1f}ms)"
        if self.message:
            result += f" - {self.message}"
        return result


class StructuredLogger:
    """Enhanced logger with context tracking and structured output."""

    def __init__(self, name: str, debug_level: DebugLevel = DebugLevel.NORMAL):
        self.logger = logging.getLogger(name)
        self.debug_level = debug_level
        self.context_stack: List[DebugContext] = []
        self._log_buffer: List[str] = []

    def set_debug_level(self, level: DebugLevel):
        """Set debug verbosity level."""
        self.debug_level = level

    @contextmanager
    def context(self, operation: str, module: str = None, **metadata):
        """Context manager for tracking operations."""
        if module is None:
            module = self.logger.name

        depth = len(self.context_stack)
        ctx = DebugContext(
            operation=operation,
            module=module,
            depth=depth,
            parent=self.context_stack[-1] if self.context_stack else None
        )

        # Add metadata
        for key, value in metadata.items():
            ctx.add_metadata(key, value)

        # Push context
        self.context_stack.append(ctx)

        try:
            if self.debug_level.value >= DebugLevel.VERBOSE.value:
                self.logger.debug(ctx.get_formatted_header())
            yield ctx
        finally:
            self.context_stack.pop()

    def debug_response(
        self,
        operation: str,
        success: bool,
        message: str = "",
        **details
    ) -> DebugResponse:
        """Create and log a debug response."""
        ctx = self.context_stack[-1] if self.context_stack else None

        response = DebugResponse(
            operation=operation,
            success=success,
            message=message,
            details=details,
            context=ctx,
        )

        if self.debug_level.value >= DebugLevel.NORMAL.value:
            if success:
                self.logger.info(response.to_formatted_string())
            else:
                self.logger.error(response.to_formatted_string())

        if self.debug_level.value >= DebugLevel.VERBOSE.value and details:
            self.logger.debug(f"  Details: {json.dumps(details, default=str, indent=2)}")

        return response

    def trace(self, message: str, **kwargs):
        """Log trace-level information."""
        if self.debug_level.value >= DebugLevel.TRACE.value:
            ctx_prefix = f"[{self.context_stack[-1].operation}] " if self.context_stack else ""
            self.logger.debug(f"{ctx_prefix}{message}")
            if kwargs:
                self.logger.debug(f"  Data: {json.dumps(kwargs, default=str, indent=2)}")

    def debug(self, message: str, **kwargs):
        """Log debug information."""
        if self.debug_level.value >= DebugLevel.VERBOSE.value:
            ctx_prefix = f"[{self.context_stack[-1].operation}] " if self.context_stack else ""
            self.logger.debug(f"{ctx_prefix}{message}")

    def info(self, message: str, **kwargs):
        """Log info level."""
        self.logger.info(message)
        if kwargs and self.debug_level.value >= DebugLevel.VERBOSE.value:
            self.logger.debug(f"  Data: {json.dumps(kwargs, default=str)}")

    def warning(self, message: str, **kwargs):
        """Log warning level."""
        self.logger.warning(message)

    def error(self, message: str, **kwargs):
        """Log error level."""
        self.logger.error(message)
        if kwargs:
            self.logger.error(f"  Error Details: {json.dumps(kwargs, default=str)}")

    def get_buffer(self) -> str:
        """Get buffered log output."""
        return "\n".join(self._log_buffer)

    def clear_buffer(self):
        """Clear log buffer."""
        self._log_buffer.clear()


class SorterTabDebugger:
    """Dedicated debugger for Collection Sorter Tab."""

    def __init__(self, debug_level: DebugLevel = DebugLevel.NORMAL):
        self.logger = StructuredLogger("sorter_tab.debug", debug_level)
        self.import_stats = {}
        self.sort_stats = {}
        self.export_stats = {}

    def log_import_start(self, file_path: str, num_lines: int = None):
        """Log CSV import start."""
        with self.logger.context("CSV Import", "SorterTab", file_path=file_path, lines=num_lines):
            self.logger.debug(f"Starting import from: {file_path}")
            if num_lines:
                self.logger.debug(f"Expected lines: {num_lines}")

    def log_import_row(self, row_num: int, card_name: str, count: int = 1):
        """Log individual card import."""
        if self.logger.debug_level.value >= DebugLevel.TRACE.value:
            self.logger.trace(f"Row {row_num}: {card_name} x{count}")

    def log_import_complete(
        self,
        total_cards: int,
        total_rows: int,
        skipped: int = 0,
        errors: int = 0
    ) -> DebugResponse:
        """Log CSV import completion."""
        self.import_stats = {
            'total_cards': total_cards,
            'total_rows': total_rows,
            'skipped': skipped,
            'errors': errors,
        }

        success = errors == 0
        message = f"Imported {total_cards} cards from {total_rows} rows"
        if skipped > 0:
            message += f" ({skipped} skipped)"
        if errors > 0:
            message += f" - {errors} ERRORS"

        return self.logger.debug_response(
            "CSV Import Complete",
            success,
            message,
            **self.import_stats
        )

    def log_sort_start(self, sort_criteria: List[str]):
        """Log sort operation start."""
        with self.logger.context("Sort Generation", "SorterTab", criteria=sort_criteria):
            self.logger.debug(f"Generating sort tree with criteria: {sort_criteria}")

    def log_sort_group_created(self, level: int, group_name: str, card_count: int):
        """Log sort group creation."""
        if self.logger.debug_level.value >= DebugLevel.VERBOSE.value:
            self.logger.trace(f"Level {level}: Created group '{group_name}' with {card_count} cards")

    def log_sort_complete(self, total_groups: int, tree_depth: int) -> DebugResponse:
        """Log sort completion."""
        self.sort_stats = {
            'total_groups': total_groups,
            'tree_depth': tree_depth,
        }

        return self.logger.debug_response(
            "Sort Generation Complete",
            True,
            f"Created {total_groups} groups with depth {tree_depth}",
            **self.sort_stats
        )

    def log_export_start(self, export_format: str, file_path: str):
        """Log export start."""
        with self.logger.context("Export", "SorterTab", format=export_format, path=file_path):
            self.logger.debug(f"Exporting to {export_format} format: {file_path}")

    def log_export_complete(self, exported_count: int, file_size_kb: float) -> DebugResponse:
        """Log export completion."""
        self.export_stats = {
            'exported_count': exported_count,
            'file_size_kb': file_size_kb,
        }

        return self.logger.debug_response(
            "Export Complete",
            True,
            f"Exported {exported_count} cards ({file_size_kb:.1f} KB)",
            **self.export_stats
        )

    def log_error(self, operation: str, error: Exception, context: str = None) -> DebugResponse:
        """Log sorter tab error."""
        details = {
            'error_type': type(error).__name__,
            'error_message': str(error),
        }
        if context:
            details['context'] = context

        return self.logger.debug_response(
            operation,
            False,
            f"Error: {type(error).__name__}",
            **details
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregated statistics."""
        return {
            'import': self.import_stats,
            'sort': self.sort_stats,
            'export': self.export_stats,
        }


class AnalyzerTabDebugger:
    """Dedicated debugger for Set Analyzer Tab."""

    def __init__(self, debug_level: DebugLevel = DebugLevel.NORMAL):
        self.logger = StructuredLogger("analyzer_tab.debug", debug_level)
        self.analysis_stats = {}
        self.fetch_stats = {}
        self.chart_stats = {}

    def log_fetch_start(self, set_codes: List[str]):
        """Log set data fetch start."""
        with self.logger.context("Fetch Sets", "AnalyzerTab", sets=set_codes):
            self.logger.debug(f"Fetching data for sets: {set_codes}")

    def log_fetch_progress(self, current_set: str, total_sets: int, cards_fetched: int):
        """Log fetch progress."""
        if self.logger.debug_level.value >= DebugLevel.VERBOSE.value:
            self.logger.trace(f"Fetching {current_set} ({cards_fetched} cards) - {cards_fetched}/{total_sets} sets")

    def log_fetch_complete(self, total_cards: int, unique_sets: int) -> DebugResponse:
        """Log fetch completion."""
        self.fetch_stats = {
            'total_cards': total_cards,
            'unique_sets': unique_sets,
        }

        return self.logger.debug_response(
            "Set Data Fetch Complete",
            True,
            f"Fetched {total_cards} cards from {unique_sets} sets",
            **self.fetch_stats
        )

    def log_analysis_start(self, analysis_type: str, weights: str, options: Dict[str, Any]):
        """Log analysis start."""
        with self.logger.context("Analysis", "AnalyzerTab", type=analysis_type, weights=weights):
            self.logger.debug(f"Starting {analysis_type} analysis with {weights} weights")
            if self.logger.debug_level.value >= DebugLevel.VERBOSE.value:
                self.logger.trace(f"Options: {options}")

    def log_analysis_step(self, step: str, processed_items: int = None):
        """Log analysis progress step."""
        if self.logger.debug_level.value >= DebugLevel.VERBOSE.value:
            msg = f"Analysis step: {step}"
            if processed_items is not None:
                msg += f" ({processed_items} items)"
            self.logger.trace(msg)

    def log_analysis_complete(
        self,
        total_entries: int,
        rarity_distribution: Dict[str, int] = None,
        duration_ms: float = 0.0
    ) -> DebugResponse:
        """Log analysis completion."""
        self.analysis_stats = {
            'total_entries': total_entries,
            'duration_ms': duration_ms,
        }
        if rarity_distribution:
            self.analysis_stats['rarity_distribution'] = rarity_distribution

        return self.logger.debug_response(
            "Analysis Complete",
            True,
            f"Analyzed {total_entries} entries in {duration_ms:.1f}ms",
            **self.analysis_stats
        )

    def log_chart_start(self, chart_type: str):
        """Log chart generation start."""
        with self.logger.context("Chart Generation", "AnalyzerTab", chart_type=chart_type):
            self.logger.debug(f"Generating {chart_type} chart")

    def log_chart_complete(self, chart_type: str, elements: int = None) -> DebugResponse:
        """Log chart completion."""
        details = {'chart_type': chart_type}
        if elements is not None:
            details['elements'] = elements

        return self.logger.debug_response(
            f"Chart: {chart_type}",
            True,
            f"Generated {chart_type} chart" + (f" with {elements} elements" if elements else ""),
            **details
        )

    def log_export_start(self, export_format: str, file_path: str):
        """Log analysis export start."""
        with self.logger.context("Export Analysis", "AnalyzerTab", format=export_format):
            self.logger.debug(f"Exporting analysis to {export_format}: {file_path}")

    def log_export_complete(self, rows_exported: int, file_size_kb: float) -> DebugResponse:
        """Log export completion."""
        return self.logger.debug_response(
            "Analysis Export Complete",
            True,
            f"Exported {rows_exported} rows ({file_size_kb:.1f} KB)",
            rows=rows_exported,
            file_size_kb=file_size_kb,
        )

    def log_error(self, operation: str, error: Exception, context: str = None) -> DebugResponse:
        """Log analyzer tab error."""
        details = {
            'error_type': type(error).__name__,
            'error_message': str(error),
        }
        if context:
            details['context'] = context

        return self.logger.debug_response(
            operation,
            False,
            f"Error: {type(error).__name__}",
            **details
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregated statistics."""
        return {
            'fetch': self.fetch_stats,
            'analysis': self.analysis_stats,
            'chart': self.chart_stats,
        }


# Global debug manager
class DebugManager:
    """Centralized debug manager for the application."""

    _instance = None
    _debug_level = DebugLevel.NORMAL

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def set_debug_level(cls, level: DebugLevel):
        """Set global debug level."""
        cls._debug_level = level

    @classmethod
    def get_sorter_debugger(cls) -> SorterTabDebugger:
        """Get sorter tab debugger."""
        debugger = SorterTabDebugger(cls._debug_level)
        return debugger

    @classmethod
    def get_analyzer_debugger(cls) -> AnalyzerTabDebugger:
        """Get analyzer tab debugger."""
        debugger = AnalyzerTabDebugger(cls._debug_level)
        return debugger

    @classmethod
    def create_logger(cls, name: str) -> StructuredLogger:
        """Create a new structured logger."""
        return StructuredLogger(name, cls._debug_level)