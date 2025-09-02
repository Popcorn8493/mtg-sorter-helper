# ui/settings_dialog.py

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
                             QCheckBox, QSpinBox, QLabel, QPushButton, 
                             QGroupBox, QTabWidget, QWidget, QSlider)
from PyQt6.QtGui import QFont

from core.constants import Config


class SettingsDialog(QDialog):
    """Settings dialog for configuring application behavior"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings(Config.ORG_NAME, Config.APP_NAME)
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        """Setup the UI layout"""
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(500, 400)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        
        # Create tab widget
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)
        
        # Performance tab
        performance_tab = self._create_performance_tab()
        tab_widget.addTab(performance_tab, "Performance")
        
        # Cache tab
        cache_tab = self._create_cache_tab()
        tab_widget.addTab(cache_tab, "Cache")
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        reset_button = QPushButton("Reset to Defaults")
        reset_button.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_button)
        
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        button_layout.addWidget(ok_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        main_layout.addLayout(button_layout)
    
    def _create_performance_tab(self):
        """Create the performance settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Lazy Loading Group
        lazy_group = QGroupBox("Lazy Loading")
        lazy_layout = QFormLayout(lazy_group)
        
        self.enable_lazy_loading = QCheckBox("Enable lazy loading for better performance")
        self.enable_lazy_loading.setToolTip(
            "When enabled, card data and images are loaded only when needed, "
            "reducing memory usage and improving startup time."
        )
        lazy_layout.addRow(self.enable_lazy_loading)
        
        self.preload_visible_cards = QCheckBox("Preload data for visible cards")
        self.preload_visible_cards.setToolTip(
            "Automatically load card data for cards currently visible in the interface."
        )
        lazy_layout.addRow(self.preload_visible_cards)
        
        self.preload_images_on_demand = QCheckBox("Load images only when requested")
        self.preload_images_on_demand.setToolTip(
            "Only download card images when the user explicitly requests them."
        )
        lazy_layout.addRow(self.preload_images_on_demand)
        
        # Concurrent Loading Group
        concurrent_group = QGroupBox("Concurrent Loading")
        concurrent_layout = QFormLayout(concurrent_group)
        
        self.max_concurrent_loads = QSpinBox()
        self.max_concurrent_loads.setRange(1, 20)
        self.max_concurrent_loads.setToolTip(
            "Maximum number of card data requests that can run simultaneously."
        )
        concurrent_layout.addRow("Max concurrent card loads:", self.max_concurrent_loads)
        
        self.max_concurrent_images = QSpinBox()
        self.max_concurrent_images.setRange(1, 10)
        self.max_concurrent_images.setToolTip(
            "Maximum number of image downloads that can run simultaneously."
        )
        concurrent_layout.addRow("Max concurrent image loads:", self.max_concurrent_images)
        
        # Add groups to layout
        layout.addWidget(lazy_group)
        layout.addWidget(concurrent_group)
        layout.addStretch()
        
        return tab
    
    def _create_cache_tab(self):
        """Create the cache settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Cache Sizes Group
        cache_group = QGroupBox("Cache Size Limits")
        cache_layout = QFormLayout(cache_group)
        
        self.max_cache_size = QSpinBox()
        self.max_cache_size.setRange(100, 2000)
        self.max_cache_size.setSuffix(" MB")
        self.max_cache_size.setToolTip(
            "Maximum size for all cached data combined."
        )
        cache_layout.addRow("Total cache size limit:", self.max_cache_size)
        
        self.max_image_cache_size = QSpinBox()
        self.max_image_cache_size.setRange(50, 1000)
        self.max_image_cache_size.setSuffix(" MB")
        self.max_image_cache_size.setToolTip(
            "Maximum size for image cache specifically."
        )
        cache_layout.addRow("Image cache size limit:", self.max_image_cache_size)
        
        # Cache Behavior Group
        behavior_group = QGroupBox("Cache Behavior")
        behavior_layout = QFormLayout(behavior_group)
        
        self.auto_cleanup_cache = QCheckBox("Automatically clean up old cache files")
        self.auto_cleanup_cache.setToolTip(
            "Remove old cache files when size limits are exceeded."
        )
        behavior_layout.addRow(self.auto_cleanup_cache)
        
        self.persist_cache = QCheckBox("Persist cache between sessions")
        self.persist_cache.setToolTip(
            "Keep cached data when the application is closed and reopened."
        )
        behavior_layout.addRow(self.persist_cache)
        
        # Add groups to layout
        layout.addWidget(cache_group)
        layout.addWidget(behavior_group)
        layout.addStretch()
        
        return tab
    
    def load_settings(self):
        """Load current settings from QSettings"""
        # Lazy loading settings
        enable_lazy = self.settings.value("lazy_loading/enabled", Config.ENABLE_LAZY_LOADING, type=bool)
        self.enable_lazy_loading.setChecked(enable_lazy)
        
        preload_visible = self.settings.value("lazy_loading/preload_visible", Config.PRELOAD_VISIBLE_CARDS, type=bool)
        self.preload_visible_cards.setChecked(preload_visible)
        
        preload_images = self.settings.value("lazy_loading/preload_images", Config.PRELOAD_IMAGES_ON_DEMAND, type=bool)
        self.preload_images_on_demand.setChecked(preload_images)
        
        # Concurrent loading settings
        max_loads = self.settings.value("lazy_loading/max_concurrent_loads", Config.MAX_CONCURRENT_LOADS, type=int)
        self.max_concurrent_loads.setValue(max_loads)
        
        max_images = self.settings.value("lazy_loading/max_concurrent_images", Config.MAX_CONCURRENT_IMAGES, type=int)
        self.max_concurrent_images.setValue(max_images)
        
        # Cache settings
        max_cache = self.settings.value("cache/max_size_mb", Config.MAX_CACHE_SIZE_MB, type=int)
        self.max_cache_size.setValue(max_cache)
        
        max_image_cache = self.settings.value("cache/max_image_size_mb", Config.MAX_IMAGE_CACHE_SIZE_MB, type=int)
        self.max_image_cache_size.setValue(max_image_cache)
        
        auto_cleanup = self.settings.value("cache/auto_cleanup", True, type=bool)
        self.auto_cleanup_cache.setChecked(auto_cleanup)
        
        persist = self.settings.value("cache/persist", True, type=bool)
        self.persist_cache.setChecked(persist)
    
    def save_settings(self):
        """Save current settings to QSettings"""
        # Lazy loading settings
        self.settings.setValue("lazy_loading/enabled", self.enable_lazy_loading.isChecked())
        self.settings.setValue("lazy_loading/preload_visible", self.preload_visible_cards.isChecked())
        self.settings.setValue("lazy_loading/preload_images", self.preload_images_on_demand.isChecked())
        self.settings.setValue("lazy_loading/max_concurrent_loads", self.max_concurrent_loads.value())
        self.settings.setValue("lazy_loading/max_concurrent_images", self.max_concurrent_images.value())
        
        # Cache settings
        self.settings.setValue("cache/max_size_mb", self.max_cache_size.value())
        self.settings.setValue("cache/max_image_size_mb", self.max_image_cache_size.value())
        self.settings.setValue("cache/auto_cleanup", self.auto_cleanup_cache.isChecked())
        self.settings.setValue("cache/persist", self.persist_cache.isChecked())
        
        # Sync settings
        self.settings.sync()
    
    def reset_to_defaults(self):
        """Reset all settings to their default values"""
        # Lazy loading defaults
        self.enable_lazy_loading.setChecked(Config.ENABLE_LAZY_LOADING)
        self.preload_visible_cards.setChecked(Config.PRELOAD_VISIBLE_CARDS)
        self.preload_images_on_demand.setChecked(Config.PRELOAD_IMAGES_ON_DEMAND)
        self.max_concurrent_loads.setValue(Config.MAX_CONCURRENT_LOADS)
        self.max_concurrent_images.setValue(Config.MAX_CONCURRENT_IMAGES)
        
        # Cache defaults
        self.max_cache_size.setValue(Config.MAX_CACHE_SIZE_MB)
        self.max_image_cache_size.setValue(Config.MAX_IMAGE_CACHE_SIZE_MB)
        self.auto_cleanup_cache.setChecked(True)
        self.persist_cache.setChecked(True)
    
    def accept(self):
        """Save settings and close dialog"""
        self.save_settings()
        super().accept()
    
    def get_lazy_loading_config(self):
        """Get current lazy loading configuration"""
        return {
            'enabled': self.enable_lazy_loading.isChecked(),
            'preload_visible': self.preload_visible_cards.isChecked(),
            'preload_images': self.preload_images_on_demand.isChecked(),
            'max_concurrent_loads': self.max_concurrent_loads.value(),
            'max_concurrent_images': self.max_concurrent_images.value()
        }
    
    def get_cache_config(self):
        """Get current cache configuration"""
        return {
            'max_size_mb': self.max_cache_size.value(),
            'max_image_size_mb': self.max_image_cache_size.value(),
            'auto_cleanup': self.auto_cleanup_cache.isChecked(),
            'persist': self.persist_cache.isChecked()
        }
