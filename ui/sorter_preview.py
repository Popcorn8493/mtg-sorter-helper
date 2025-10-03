# ui/sorter_preview.py - Card preview and image handling for sorter tab

import os
from typing import List
from PyQt6.QtCore import QThread, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QTreeWidgetItem

from api.scryfall_api import ScryfallAPI
from core.constants import Config
from core.models import Card
from workers.threads import ImageFetchWorker, BackgroundImageCacheWorker


class SorterPreview:
    """Handles card preview and image functionality for the sorter tab"""

    def __init__(self, parent):
        self.parent = parent
        self.api: ScryfallAPI = parent.api
        self.cached_images: dict[str, str] = {}  # scryfall_id -> cache_path
        self.current_loading_id: str | None = None
        self.preview_card: Card | None = None

        # Thread/worker attributes
        self.image_thread: QThread | None = None
        self.image_worker: ImageFetchWorker | None = None
        self.background_cache_thread: QThread | None = None
        self.background_cache_worker: BackgroundImageCacheWorker | None = None

    def reset_preview_pane(self, *args):
        """Reset preview pane safely"""
        # Use centralized worker management
        self.parent.worker_manager.cleanup_worker("image_worker")

        # Legacy cleanup for backward compatibility
        from workers.threads import cleanup_worker_thread

        cleanup_worker_thread(self.image_thread, self.image_worker)

        self.current_loading_id = None
        self.preview_card = None
        self.parent.card_image_label.setText(
            "Select an individual card to see its image."
        )
        self.parent.card_image_label.setPixmap(QPixmap())
        self.parent.card_details_label.setText(
            "Navigate to individual cards to see details."
        )
        self.parent.fetch_image_button.setVisible(False)

    def update_card_preview(self, item: QTreeWidgetItem):
        """Update card preview to be on-demand."""
        self.reset_preview_pane()

        cards = self.parent._get_cards_from_item(item)
        if not cards:
            return

        # Determine which card to preview (first in group)
        card = cards[0] if cards else None

        if not isinstance(card, Card):
            self.preview_card = None
            return

        self.preview_card = card  # Store the card for the fetch button

        # Display text details
        if len(cards) == 1:
            self.parent.card_details_label.setText(
                f"<b>{card.name}</b><br>{card.mana_cost or ''}<br>{card.type_line}<br>"
                f"<i>{card.set_name} ({card.rarity.upper()})</i><br><br>"
                f"Total Owned: {card.quantity}<br>Sorted: {card.sorted_count}"
            )
        else:  # Group selected
            self.parent.card_details_label.setText(
                f"<b>Group: {item.text(0)}</b><br>"
                f"Contains {len(cards)} different cards<br>"
                f"Total cards: {sum(c.quantity for c in cards)}<br>"
                f"Showing preview of: {card.name}"
            )

        # Set up the image pane - check cache first, then on-demand fetching
        if card.image_uri:
            # Try to load cached image first
            if self.load_cached_image(card.scryfall_id):
                # Image loaded from cache, fetch button already hidden
                pass
            else:
                # Image not cached, show fetch button
                self.parent.card_image_label.setText("Image available - click to load.")
                self.parent.fetch_image_button.setVisible(True)
        else:
            self.parent.card_image_label.setText("No image available for this card.")
            self.parent.fetch_image_button.setVisible(False)

    def on_fetch_image_clicked(self):
        """Starts the download for the currently previewed card's image."""
        try:
            # Check if another fetch is already running - safely handle deleted Qt objects
            try:
                if (
                    hasattr(self, "image_thread")
                    and self.image_thread
                    and self.image_thread.isRunning()
                ):
                    return
            except RuntimeError as e:
                # Qt object was deleted, clear the reference and continue
                self.image_thread = None
                self.image_worker = None

            # Validate preview card
            if not hasattr(self, "preview_card") or not self.preview_card:
                self.parent.card_image_label.setText("No card selected.")
                return

            if not self.preview_card.image_uri:
                self.parent.card_image_label.setText(
                    "No image available for this card."
                )
                return

            card = self.preview_card

            # Store current loading ID for validation
            self.current_loading_id = card.scryfall_id

            # Update UI state
            self.parent.card_image_label.setText("Loading image...")
            self.parent.fetch_image_button.setEnabled(False)

            # Clean up any existing thread/worker
            try:
                # Use centralized worker management
                self.parent.worker_manager.cleanup_worker("image_worker")

                # Legacy cleanup for backward compatibility
                if hasattr(self, "image_thread") and self.image_thread:
                    from workers.threads import cleanup_worker_thread

                    cleanup_worker_thread(
                        self.image_thread, getattr(self, "image_worker", None)
                    )
            except Exception as cleanup_error:
                print(f"[UI] Error during thread cleanup: {cleanup_error}")

            # Create new thread and worker
            self.image_thread = QThread()
            self.image_worker = ImageFetchWorker(
                card.image_uri, card.scryfall_id, self.api, parent=None
            )

            # Move worker to thread
            self.image_worker.moveToThread(self.image_thread)

            # Connect signals with error handling
            try:
                self.image_thread.started.connect(self.image_worker.process)
                self.image_worker.finished.connect(self.on_image_loaded)
                self.image_worker.error.connect(self.on_image_error)
                self.image_worker.finished.connect(self.image_thread.quit)
                self.image_worker.finished.connect(self.image_worker.deleteLater)
                self.image_thread.finished.connect(self.image_thread.deleteLater)
            except Exception as signal_error:
                print(f"[UI] Error connecting signals: {signal_error}")
                self.on_image_error(f"Failed to setup image fetch: {signal_error}")
                return

            # Start the thread
            self.image_thread.start()

        except Exception as e:
            self.parent.handle_ui_error(
                "on_fetch_image_clicked",
                e,
                additional_context=f"preview_card: {self.preview_card.name if self.preview_card else 'None'}, thread_running: {self.image_thread.isRunning() if self.image_thread else 'None'}",
            )

            # Reset UI state on error
            try:
                self.parent.fetch_image_button.setEnabled(True)
                self.parent.card_image_label.setText(
                    f"Error starting image fetch: {str(e)}"
                )
            except:
                pass  # Don't crash the UI

    def on_image_loaded(self, image_data: bytes, scryfall_id: str):
        """Handle successful image loading"""
        try:
            # Safe button re-enable
            try:
                if (
                    hasattr(self.parent, "fetch_image_button")
                    and self.parent.fetch_image_button
                ):
                    self.parent.fetch_image_button.setEnabled(True)
            except Exception as button_error:
                print(f"[UI] Button enable error: {button_error}")

            # Check if this is still the current request
            try:
                if (
                    hasattr(self, "current_loading_id")
                    and scryfall_id != self.current_loading_id
                ):
                    return
            except Exception as id_check_error:
                print(f"[UI] ID check error: {id_check_error}")

            # Validate image data with multiple checks
            try:
                if not image_data:
                    self._set_label_text("No image data received.")
                    return

                if not isinstance(image_data, bytes):
                    self._set_label_text("Invalid image data format.")
                    return

                if len(image_data) < 100:
                    self._set_label_text("Image data too small.")
                    return

            except Exception as validation_error:
                print(f"[UI] Data validation error: {validation_error}")
                self._set_label_text("Data validation failed.")
                return

            # Create and load pixmap with maximum protection
            try:
                pixmap = QPixmap()
                if not pixmap.loadFromData(image_data):
                    self._set_label_text("Failed to decode image.")
                    return

                if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
                    self._set_label_text("Invalid image format.")
                    return

            except Exception as pixmap_error:
                print(f"[UI] Pixmap creation error: {pixmap_error}")
                self._set_label_text("Image creation failed.")
                return

            # Scale and display with protection
            try:
                if (
                    hasattr(self.parent, "card_image_label")
                    and self.parent.card_image_label
                ):
                    label_size = self.parent.card_image_label.size()

                    if label_size.width() > 10 and label_size.height() > 10:
                        scaled_pixmap = pixmap.scaled(
                            label_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self.parent.card_image_label.setPixmap(scaled_pixmap)
                    else:
                        self.parent.card_image_label.setPixmap(pixmap)

            except Exception as display_error:
                print(f"[UI] Image display error: {display_error}")
                self._set_label_text("Display failed.")

        except Exception as critical_error:
            print(f"[UI] CRITICAL ERROR in on_image_loaded: {critical_error}")
            try:
                import traceback

                traceback.print_exc()
            except:
                pass
            self._set_label_text("Critical error occurred.")

        finally:
            # Safe cleanup with proper Qt object handling
            try:
                # Use the same safe cleanup pattern as background cache
                if hasattr(self, "image_worker") and self.image_worker:
                    self.image_worker.deleteLater()
                if hasattr(self, "image_thread") and self.image_thread:
                    self.image_thread.quit()
                    self.image_thread.wait(1000)  # Wait up to 1 second
                    self.image_thread.deleteLater()
                # Only set to None after Qt cleanup is scheduled
                self.image_thread = None
                self.image_worker = None
            except Exception as cleanup_error:
                print(f"[UI] Cleanup error: {cleanup_error}")

    def _set_label_text(self, text: str):
        """Set label text with error protection"""
        if hasattr(self.parent, "card_image_label") and self.parent.card_image_label:
            self.parent.card_image_label.setText(text)

    def on_image_error(self, error_message: str):
        """Handle image loading errors"""
        try:
            # Safe button re-enable
            try:
                if (
                    hasattr(self.parent, "fetch_image_button")
                    and self.parent.fetch_image_button
                ):
                    self.parent.fetch_image_button.setEnabled(True)
            except Exception as button_error:
                print(f"[UI] Error re-enabling button: {button_error}")

            # Safe error message display
            try:
                if isinstance(error_message, str):
                    display_message = error_message
                    if len(display_message) > 150:
                        display_message = display_message[:150] + "..."
                    self._set_label_text(f"Image unavailable:\n{display_message}")
                else:
                    self._set_label_text("Image fetch failed (invalid error)")

            except Exception as message_error:
                print(f"[UI] Error displaying message: {message_error}")
                self._set_label_text("Image fetch failed")

        except Exception as critical_error:
            print(f"[UI] CRITICAL ERROR in on_image_error: {critical_error}")
            try:
                import traceback

                traceback.print_exc()
            except:
                pass
            self._set_label_text("Error handler failed")

        finally:
            # Safe cleanup
            try:
                if hasattr(self, "image_thread"):
                    self.image_thread = None
                if hasattr(self, "image_worker"):
                    self.image_worker = None
            except Exception as cleanup_error:
                print(f"[UI] Error during error cleanup: {cleanup_error}")

    def start_background_image_cache(self, cards: List[Card]):
        """Start background caching of card images"""
        try:
            # Don't start if already running
            if (
                hasattr(self, "background_cache_thread")
                and self.background_cache_thread
                and self.background_cache_thread.isRunning()
            ):
                return

            # Clean up any existing thread
            # Use centralized worker management
            self.parent.worker_manager.cleanup_worker("background_cache_worker")

            # Legacy cleanup for backward compatibility
            from workers.threads import cleanup_worker_thread

            cleanup_worker_thread(
                self.background_cache_thread, self.background_cache_worker
            )

            # Create new thread and worker
            self.background_cache_thread = QThread()
            self.background_cache_worker = BackgroundImageCacheWorker(
                cards, self.api, max_concurrent=2
            )

            # Move worker to thread
            self.background_cache_worker.moveToThread(self.background_cache_thread)

            # Connect signals
            self.background_cache_thread.started.connect(
                self.background_cache_worker.process
            )
            self.background_cache_worker.image_cached.connect(self.on_image_cached)
            self.background_cache_worker.progress.connect(self.on_cache_progress)
            self.background_cache_worker.finished.connect(self.on_cache_finished)
            self.background_cache_worker.error.connect(self.on_cache_error)

            # Safe cleanup: let Qt handle the deletion after thread finishes
            self.background_cache_worker.finished.connect(
                self.background_cache_thread.quit
            )
            self.background_cache_thread.finished.connect(
                self._cleanup_background_cache
            )

            # Start the thread
            self.background_cache_thread.start()

        except Exception as e:
            self.parent.handle_background_error(
                "starting background cache",
                e,
                additional_context=f"cards_count: {len(cards) if cards else 0}, thread_running: {self.background_cache_thread.isRunning() if self.background_cache_thread else 'None'}",
            )

    def on_image_cached(self, scryfall_id: str, cache_path: str):
        """Handle successful background image caching"""
        self.cached_images[scryfall_id] = cache_path

        # If this is the currently previewed card, update the display
        if (
            hasattr(self, "preview_card")
            and self.preview_card
            and self.preview_card.scryfall_id == scryfall_id
        ):
            self.load_cached_image(scryfall_id)

    def on_cache_progress(self, current: int, total: int):
        """Handle background cache progress updates"""
        pass  # Progress is handled silently

    def on_cache_finished(self, total_cached: int):
        """Handle background cache completion"""
        # Don't set references to None here - let Qt cleanup handle it
        pass

    def _cleanup_background_cache(self):
        """Safely cleanup background cache thread and worker after Qt finishes"""
        if self.background_cache_worker:
            self.background_cache_worker.deleteLater()
        if self.background_cache_thread:
            self.background_cache_thread.deleteLater()
        # Only set to None after Qt cleanup is scheduled
        self.background_cache_worker = None
        self.background_cache_thread = None

    def on_cache_error(self, scryfall_id: str, error_message: str):
        """Handle background cache errors"""
        if scryfall_id != "SYSTEM":  # Don't log individual card failures
            pass  # Silently handle individual failures
        else:
            print(f"[BackgroundCache] System error: {error_message}")

    def load_cached_image(self, scryfall_id: str):
        """Load a cached image directly from disk"""
        try:
            cache_path = self.cached_images.get(scryfall_id)
            if not cache_path:
                # Check if file exists in standard cache location
                cache_file = Config.IMAGE_CACHE_DIR / f"{scryfall_id}.jpg"
                if cache_file.exists():
                    cache_path = str(cache_file)
                    self.cached_images[scryfall_id] = cache_path

            if cache_path and os.path.exists(cache_path):
                # Load image data
                with open(cache_path, "rb") as f:
                    image_data = f.read()

                # Create and display pixmap
                pixmap = QPixmap()
                if pixmap.loadFromData(image_data):
                    scaled_pixmap = pixmap.scaled(
                        self.parent.card_image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.parent.card_image_label.setPixmap(scaled_pixmap)

                    # Hide the fetch button since image is already displayed
                    self.parent.fetch_image_button.setVisible(False)
                    return True

        except Exception as e:
            self.parent.handle_silent_error("loading cached image", e)

        return False
