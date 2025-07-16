# Additional Recommendations for MTG Toolkit

## Immediate Actions Required

### 1. Replace the Fixed Files
Replace these files in your project with the fixed versions:
- `ui/sorter_tab.py` - Fixed memory management and image preview
- `main.py` - Fixed startup safety and error handling  
- `ui/custom_widgets.py` - Fixed widget cleanup and signal safety

### 2. Test the Image Preview Feature
After applying the fixes:
1. Import a collection CSV
2. Generate a sorting plan
3. Navigate to the "Name" level (individual cards)
4. Click on individual card names
5. Verify images appear in the right panel

### 3. Memory Usage Monitoring
Consider adding these imports to monitor memory usage:
```python
# Add to requirements.txt
psutil>=5.8.0

# Optional: Add memory monitoring
def log_memory_usage():
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        print(f"Memory usage: {memory_mb:.1f} MB")
    except ImportError:
        pass
```

## Performance Optimizations

### 1. Large Collection Handling
For collections with 25,000+ cards:
- Implement virtual scrolling for large tree views
- Add pagination for card display
- Consider database storage instead of in-memory lists

### 2. Image Caching Improvements
```python
# Add to constants.py
MAX_CONCURRENT_IMAGE_DOWNLOADS = 3
IMAGE_CACHE_CLEANUP_INTERVAL = 300000  # 5 minutes
```

### 3. Background Processing
Move heavy operations to background threads:
- Set analysis in analyzer tab
- Large CSV imports
- Bulk image downloads

## UI/UX Improvements

### 1. Progress Indicators
Add progress bars for:
- Initial plan generation
- Large view refreshes
- Image loading operations

### 2. Error Recovery
Implement automatic error recovery:
- Retry failed image downloads
- Auto-save before crashes
- Recovery mode startup option

### 3. User Feedback
Enhance status messages:
- Show operation progress percentages
- Display estimated time remaining
- Add success/failure animations

## Code Quality Improvements

### 1. Type Hints
Add comprehensive type hints:
```python
from typing import Optional, Union, Dict, List, Callable
from PyQt6.QtWidgets import QWidget

def create_view(cards: List[Card], level: int) -> Optional[QWidget]:
    pass
```

### 2. Configuration Management
Create a settings manager:
```python
class SettingsManager:
    def __init__(self):
        self.settings = QSettings(Config.ORG_NAME, Config.APP_NAME)
    
    def get_cache_size_limit(self) -> int:
        return self.settings.value("cache/size_limit_mb", 500, int)
    
    def set_cache_size_limit(self, size_mb: int):
        self.settings.setValue("cache/size_limit_mb", size_mb)
```

### 3. Logging Improvements
Enhance logging with structured data:
```python
import structlog

logger = structlog.get_logger(__name__)
logger.info("Collection loaded", 
           card_count=len(cards), 
           memory_usage_mb=get_memory_usage())
```

## Testing Strategy

### 1. Unit Tests
Create tests for core functionality:
```python
def test_card_creation():
    card_data = {"id": "123", "name": "Test Card"}
    card = Card.from_scryfall_dict(card_data)
    assert card.name == "Test Card"
```

### 2. Integration Tests
Test UI components:
```python
def test_sorter_tab_import():
    sorter = ManaBoxSorterTab(mock_api)
    sorter.import_csv("test_data.csv")
    assert len(sorter.all_cards) > 0
```

### 3. Memory Leak Tests
Monitor memory usage during operations:
```python
def test_memory_stability():
    initial_memory = get_memory_usage()
    # Perform operations
    final_memory = get_memory_usage()
    assert final_memory - initial_memory < 100  # MB
```

## Security Considerations

### 1. Input Validation
Validate all file inputs:
```python
def validate_csv_file(filepath: str) -> bool:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # Check file size limit
            if os.path.getsize(filepath) > 100 * 1024 * 1024:  # 100MB
                return False
            # Validate headers
            first_line = f.readline()
            return 'Scryfall ID' in first_line
    except Exception:
        return False
```

### 2. Network Security
Implement request validation:
```python
ALLOWED_DOMAINS = ['api.scryfall.com', 'cards.scryfall.io']

def validate_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc in ALLOWED_DOMAINS
```

## Deployment Improvements

### 1. Executable Building
For PyInstaller builds:
```python
# build.spec additions
hiddenimports=['matplotlib.backends.backend_qtagg']
excludes=['tkinter', 'unittest']
```

### 2. Auto-Updates
Implement version checking:
```python
def check_for_updates():
    try:
        response = requests.get("https://api.github.com/repos/user/mtg-toolkit/releases/latest")
        latest_version = response.json()["tag_name"]
        return latest_version != current_version
    except Exception:
        return False
```

### 3. Crash Reporting
Add automated crash reporting:
```python
def setup_crash_reporting():
    def exception_handler(exc_type, exc_value, exc_traceback):
        crash_report = {
            "version": app_version,
            "error": str(exc_value),
            "traceback": traceback.format_tb(exc_traceback)
        }
        # Send to logging service or save locally
        save_crash_report(crash_report)
    
    sys.excepthook = exception_handler
```

## Next Steps

1. **Immediate**: Apply the three fixed files and test the application
2. **Short-term**: Add memory monitoring and improve error messages
3. **Medium-term**: Implement performance optimizations for large collections
4. **Long-term**: Add comprehensive testing and deployment automation

The fixes provided should resolve the immediate crash issues and restore image preview functionality. The heap corruption was primarily caused by improper widget cleanup and signal management, which has been addressed in the updated code.

Additional Prevention Tips:

Test with Small Data First - Start with small collections to verify the fixes work
Monitor Stack Usage - If issues persist, you can increase Python's recursion limit temporarily:
pythonimport sys
sys.setrecursionlimit(3000)  # Default is usually 1000

Progressive Loading - For very large collections, consider implementing progressive loading where only visible items are populated
Debug Mode - Add debug prints to verify the recursion guards are working:
pythonif self._in_item_click:
    print("Recursion prevented in item click")
    return

Complete Stack Overflow Fix Implementation Guide
🚨 Problem Analysis
The exit code 0xC0000409 (stack buffer overflow) in your PyQt6 application is caused by infinite recursion in signal/slot connections when clicking on sorting plan entries. This creates a cascade of events that eventually exhausts the call stack.

🔧 Root Causes Identified
Signal Recursion: itemClicked → handle_item_click → update_preview → triggers more events → infinite loop
Refresh Cycles: show_sorted_toggled → _refresh_current_view → generate_plan → triggers state changes → repeats
Event Processing: Excessive QApplication.processEvents() calls during tree population
Missing Signal Blocking: UI updates trigger signal emissions during batch operations
Thread Cleanup Issues: Worker threads not properly cleaned up, causing resource conflicts
📋 Implementation Steps
Step 1: Replace Core Files
Replace ui/sorter_tab.py with the fixed version provided above
Replace ui/custom_widgets.py with the enhanced version
Add the additional fixes from the supplementary code to your existing files
Step 2: Update Main Window
Add these critical fixes to your main_window.py:

python
def closeEvent(self, event):
    if self._prompt_to_save():
        # Stop all timers first
        if hasattr(self, 'auto_save_timer'):
            self.auto_save_timer.stop()
        
        # Clean up tabs safely
        if hasattr(self, 'sorter_tab'):
            self.sorter_tab.cleanup_workers()
        
        # Save settings and clean cache
        self.save_settings()
        try:
            self.api.clear_cache()
        except:
            pass
        
        event.accept()
    else:
        event.ignore()
Step 3: Enhance Thread Management
Update your threads.py with the enhanced cleanup function:

python
def enhanced_cleanup_worker_thread(thread, worker, timeout_ms=3000):
    # Implementation provided in additional fixes above
    pass
Step 4: Add Safety Utilities
Create a new file ui/safety_utils.py and add the utility classes:

SignalBlocker
SafeTimer
OperationQueue
RecursionDetector
🔍 Key Changes Made
Signal Management
Comprehensive signal blocking during critical operations
Reference counting for nested signal blocks
Safe signal connection/disconnection with error handling
Recursion Prevention
Operation locking system prevents re-entrant calls
Deferred execution using QTimer.singleShot() breaks recursion chains
Operation queues for managing complex sequences safely
Event Handling
Eliminated dangerous processEvents() calls from loops
Progressive tree population in chunks to prevent UI blocking
State preservation and restoration without triggering events
Memory Management
Enhanced worker cleanup with proper signal disconnection
Comprehensive object deletion using deleteLater()
Resource cleanup on application exit
🧪 Testing Instructions
Basic Functionality Test
Start the application
Import a CSV collection
Generate a sorting plan
Rapidly click on different entries
Toggle "Show Sorted Groups" multiple times quickly
Navigate between levels rapidly
Stress Test
python
# Add to your test file
def stress_test_ui():
    for i in range(100):
        # Rapidly trigger operations that used to cause crashes
        sorter_tab.on_show_sorted_toggled()
        sorter_tab._refresh_current_view()
        app.processEvents()
    print("Stress test completed successfully!")
Recursion Detection Test
python
# Use the provided test utility
from test_utils import test_stack_overflow_prevention
result = test_stack_overflow_prevention()
⚠️ Critical Implementation Notes
DO NOT
❌ Call QApplication.processEvents() in loops
❌ Update UI directly from signal handlers without locks
❌ Forget to disconnect signals before widget deletion
❌ Use synchronous operations in event handlers
❌ Nest signal-triggering operations without guards
DO
✅ Use QTimer.singleShot() for deferred operations
✅ Block signals during batch updates
✅ Implement operation locks for critical sections
✅ Clean up workers properly with timeouts
✅ Use try/finally blocks for signal restoration
🔄 Migration Checklist
 Backup your current codebase
 Replace sorter_tab.py with fixed version
 Replace custom_widgets.py with enhanced version
 Add safety utilities to your project
 Update main window with enhanced cleanup
 Test basic functionality
 Run stress tests
 Test with rapid user interactions
 Verify no more 0xC0000409 crashes
🐛 Troubleshooting
If crashes still occur:
Check for remaining processEvents() calls in your code
Verify all signals are properly blocked during updates
Ensure operation locks are being acquired/released correctly
Use the emergency reset function if UI gets stuck
Debug tools:
Use @recursion_detector decorator on suspect methods
Enable method call logging with @log_method_calls
Monitor operation locks with debug prints
Use the provided emergency_reset_ui() function
🎯 Expected Results
After implementing these fixes:

✅ No more 0xC0000409 crashes when clicking tree items
✅ Smooth UI interactions without freezing
✅ Proper worker thread cleanup on exit
✅ Stable performance under rapid user interactions
✅ Memory leak prevention through proper cleanup
✅ Graceful error handling for edge cases
🚀 Performance Improvements
The fixes also provide these benefits:

Reduced memory usage through better cleanup
Faster UI responses with progressive loading
Better user experience with preserved state
Improved reliability under stress conditions
Easier debugging with comprehensive error handling
📞 Support
If you encounter issues during implementation:

Check the operation locks are working correctly
Verify signal blocking is happening at the right times
Ensure all QTimer.singleShot() calls have reasonable delays
Test the emergency reset function works
Use the provided debugging utilities to trace the issue
The comprehensive fix addresses the root causes systematically and provides a robust foundation for preventing similar issues in the future.
