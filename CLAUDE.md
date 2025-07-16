# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MTG Toolkit is a PyQt6-based desktop application for analyzing Magic: The Gathering card collections and optimizing sorting strategies. The application provides two main features:

1. **Collection Sorter**: Imports ManaBox CSV exports and generates optimal sorting plans based on configurable criteria
2. **Set Analyzer**: Analyzes MTG sets by letter frequency with optional rarity weighting to optimize physical card sorting

## Development Commands

```bash
# Install dependencies (includes psutil for memory monitoring)
pip install -r requirements.txt

# Run the application
python main.py

# Run with command line options
python main.py --debug                    # Enable debug logging
python main.py --theme light              # Start with light theme
python main.py --clear-cache              # Clear cache on startup
python main.py --import file.csv          # Import collection on startup
python main.py --no-splash               # Skip splash screen
python main.py --safe-mode               # Start in safe mode for troubleshooting
```

## Architecture

### Core Components

- **main.py**: Application entry point with comprehensive startup sequence, error handling, command-line argument parsing, and memory monitoring
- **ui/main_window.py**: Main application window with tabbed interface, project management, and auto-save functionality
- **ui/custom_widgets.py**: Enhanced tree widgets with stack overflow prevention and safe signal handling
- **workers/threads.py**: Worker classes for background processing with memory safety and proper signal handling
- **core/models.py**: Data models for `Card` and `SortGroup` with sorting state tracking
- **core/constants.py**: Configuration constants and theme management
- **api/scryfall_api.py**: Scryfall API client with intelligent caching, rate limiting, and memory safety checks

### UI Architecture

The application uses a tabbed interface:
- **ManaBoxSorterTab** (`ui/sorter_tab.py`): Collection management with hierarchical sorting plans and crash-resistant tree operations
- **SetAnalyzerTab** (`ui/analyzer_tab.py`): Set analysis with matplotlib charts

### Data Flow

1. **CSV Import**: ManaBox exports → Streaming CSV processing → Scryfall API batch lookups → Card objects with cached data
2. **Sorting Plans**: User-defined criteria → Hierarchical grouping → Interactive tree navigation with deferred execution
3. **Progress Tracking**: Sorted count tracking per card → Group-level progress calculation with throttled updates

### Caching Strategy

- **Card Data**: `.mtgtoolkit_cache/card_data/` - Scryfall API responses (50MB limit)
- **Images**: `.mtgtoolkit_cache/image_data/` - Card images for UI display (configurable limit)
- **Sets**: `.mtgtoolkit_cache/set_data/` - Set-level analysis results (100MB limit)
- **Projects**: `.mtgproj` files - Complete sorting state with progress
- **Logs**: `.mtgtoolkit_cache/logs/` - Application and error logs

### Threading Model

- **CsvImportWorker**: Background CSV processing with streaming, memory monitoring, and throttled progress updates
- **ImageFetchWorker**: Async card image loading for UI
- **SetAnalysisWorker**: Background set analysis with progress tracking
- **Main Thread**: UI updates and user interactions with deferred signal handling

## Key Implementation Details

### Crash Prevention & Memory Safety

**FIXED: Heap Corruption Issues (Exit code 0xC0000409)**
- **Tree Widget Recursion**: Fixed recursive signal connections in `NavigableTreeWidget` using deferred execution with `QTimer.singleShot()`
- **CSV Import Memory Exhaustion**: Implemented streaming CSV processing instead of loading entire files into memory
- **Memory Monitoring**: Added `psutil`-based memory usage monitoring with configurable limits
- **Signal Throttling**: Reduced progress signal frequency from every row to every 100 rows to prevent Qt event system overload
- **Collection Size Limits**: Enforced limits of 50,000 CSV rows and 10,000 cards per import operation
- **API Rate Limiting**: Increased Scryfall API delays from 0.05s to 0.1s to prevent server overload

### Error Handling
- Comprehensive error handling throughout startup sequence and runtime operations
- Critical operations wrapped in try-catch blocks with fallback behavior
- Stack overflow prevention in tree widget operations
- Safe signal emission with deferred execution queues

### Memory Management
- Cache size limits enforced (50MB card data, configurable image cache, 100MB set data)
- Automatic cleanup of oldest cached files when limits exceeded
- Real-time memory usage monitoring during CSV import and processing operations
- Progressive tree population to prevent UI freezing and memory spikes

### Project State
- Auto-save every 5 minutes to prevent progress loss
- Project files contain complete sorting state and progress
- Recent projects menu for quick access

### API Integration
- Respectful Scryfall API usage with increased rate limiting (0.1s delays)
- Bulk collection endpoint for efficient lookups with memory safety checks
- Graceful handling of API failures and network issues
- Collection size validation (max 10,000 cards per batch, 15,000 total responses)

### Threading Safety
- Proper QObject-based worker pattern instead of QThread inheritance
- Safe signal blocking/unblocking with reference counting
- Operation queuing system for deferred execution
- Comprehensive cleanup procedures for worker threads

## Development Notes

- PyQt6 is used throughout - ensure Qt API environment variable is set correctly
- Dark/light theme support via ThemeManager stylesheets
- High DPI display support configured during startup
- Comprehensive logging to `.mtgtoolkit_cache/logs/mtg_toolkit.log`
- Memory monitoring functions available for debugging performance issues
- Progressive tree population prevents UI freezing with large datasets

## Recent Fixes

### Crash Resolution (Exit Code 0xC0000409)
1. **Tree Widget Stack Overflow**: Fixed recursive signal connections causing stack overflow during tree item interactions
2. **CSV Import Memory Exhaustion**: Replaced memory-intensive file loading with streaming processing and memory monitoring
3. **Signal System Overload**: Implemented throttled progress updates to prevent Qt event system crashes
4. **API Memory Safety**: Added collection size limits and memory checks for Scryfall API operations

### Code Structure Improvements
- Split complex event handling in `NavigableTreeWidget` into specialized handler methods
- Enhanced documentation and type hints throughout worker classes
- Improved error messages with specific guidance for memory and collection size issues
- Added progressive tree population to handle large sorting hierarchies without crashes

## Known Limitations

- CSV imports limited to 50,000 rows per file
- Collection processing limited to 10,000 unique cards per operation
- Memory usage monitored but requires `psutil` package for full functionality
- Some file splitting may be needed for very large collections to prevent memory issues
