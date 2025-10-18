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

    def __init__(self, parent):
        self.parent = parent
        self.api: ScryfallAPI = parent.api
        self.cached_images: dict[str, str] = {}
        self.current_loading_id: str | None = None
        self.preview_card: Card | None = None
        self.image_thread: QThread | None = None
        self.image_worker: ImageFetchWorker | None = None
        self.background_cache_thread: QThread | None = None
        self.background_cache_worker: BackgroundImageCacheWorker | None = None

    def reset_preview_pane(self, *args):
        self.parent.worker_manager.cleanup_worker('image_worker')
        from workers.threads import cleanup_worker_thread
        cleanup_worker_thread(self.image_thread, self.image_worker)
        self.current_loading_id = None
        self.preview_card = None
        self.parent.card_image_label.setText('Select an individual card to see its image.')
        self.parent.card_image_label.setPixmap(QPixmap())
        self.parent.card_details_label.setText('Navigate to individual cards to see details.')
        self.parent.fetch_image_button.setVisible(False)

    def update_card_preview(self, item: QTreeWidgetItem):
        self.reset_preview_pane()
        cards = self.parent._get_cards_from_item(item)
        if not cards:
            return
        card = cards[0] if cards else None
        if not isinstance(card, Card):
            self.preview_card = None
            return
        self.preview_card = card
        if len(cards) == 1:
            self.parent.card_details_label.setText(f"<b>{card.name}</b><br>{card.mana_cost or ''}<br>{card.type_line}<br><i>{card.set_name} ({card.rarity.upper()})</i><br><br>Total Owned: {card.quantity}<br>Sorted: {card.sorted_count}")
        else:
            self.parent.card_details_label.setText(f'<b>Group: {item.text(0)}</b><br>Contains {len(cards)} different cards<br>Total cards: {sum((c.quantity for c in cards))}<br>Showing preview of: {card.name}')
        if card.image_uri:
            if self.load_cached_image(card.scryfall_id):
                pass
            else:
                self.parent.card_image_label.setText('Image available - click to load.')
                self.parent.fetch_image_button.setVisible(True)
        else:
            self.parent.card_image_label.setText('No image available for this card.')
            self.parent.fetch_image_button.setVisible(False)

    def on_fetch_image_clicked(self):
        try:
            try:
                if hasattr(self, 'image_thread') and self.image_thread and self.image_thread.isRunning():
                    return
            except RuntimeError as e:
                self.image_thread = None
                self.image_worker = None
            if not hasattr(self, 'preview_card') or not self.preview_card:
                self.parent.card_image_label.setText('No card selected.')
                return
            if not self.preview_card.image_uri:
                self.parent.card_image_label.setText('No image available for this card.')
                return
            card = self.preview_card
            self.current_loading_id = card.scryfall_id
            self.parent.card_image_label.setText('Loading image...')
            self.parent.fetch_image_button.setEnabled(False)
            try:
                self.parent.worker_manager.cleanup_worker('image_worker')
                if hasattr(self, 'image_thread') and self.image_thread:
                    from workers.threads import cleanup_worker_thread
                    cleanup_worker_thread(self.image_thread, getattr(self, 'image_worker', None))
            except Exception as cleanup_error:
                print(f'[UI] Error during thread cleanup: {cleanup_error}')
            self.image_thread = QThread()
            self.image_worker = ImageFetchWorker(card.image_uri, card.scryfall_id, self.api, parent=None)
            self.image_worker.moveToThread(self.image_thread)
            try:
                self.image_thread.started.connect(self.image_worker.process)
                self.image_worker.finished.connect(self.on_image_loaded)
                self.image_worker.error.connect(self.on_image_error)
                self.image_worker.finished.connect(self.image_thread.quit)
                self.image_worker.finished.connect(self.image_worker.deleteLater)
                self.image_thread.finished.connect(self.image_thread.deleteLater)
            except Exception as signal_error:
                print(f'[UI] Error connecting signals: {signal_error}')
                self.on_image_error(f'Failed to setup image fetch: {signal_error}')
                return
            self.image_thread.start()
        except Exception as e:
            self.parent.handle_ui_error('on_fetch_image_clicked', e, additional_context=f"preview_card: {(self.preview_card.name if self.preview_card else 'None')}, thread_running: {(self.image_thread.isRunning() if self.image_thread else 'None')}")
            try:
                self.parent.fetch_image_button.setEnabled(True)
                self.parent.card_image_label.setText(f'Error starting image fetch: {str(e)}')
            except:
                pass

    def on_image_loaded(self, image_data: bytes, scryfall_id: str):
        try:
            try:
                if hasattr(self.parent, 'fetch_image_button') and self.parent.fetch_image_button:
                    self.parent.fetch_image_button.setEnabled(True)
            except Exception as button_error:
                print(f'[UI] Button enable error: {button_error}')
            try:
                if hasattr(self, 'current_loading_id') and scryfall_id != self.current_loading_id:
                    return
            except Exception as id_check_error:
                print(f'[UI] ID check error: {id_check_error}')
            try:
                if not image_data:
                    self._set_label_text('No image data received.')
                    return
                if not isinstance(image_data, bytes):
                    self._set_label_text('Invalid image data format.')
                    return
                if len(image_data) < 100:
                    self._set_label_text('Image data too small.')
                    return
            except Exception as validation_error:
                print(f'[UI] Data validation error: {validation_error}')
                self._set_label_text('Data validation failed.')
                return
            try:
                pixmap = QPixmap()
                if not pixmap.loadFromData(image_data):
                    self._set_label_text('Failed to decode image.')
                    return
                if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
                    self._set_label_text('Invalid image format.')
                    return
            except Exception as pixmap_error:
                print(f'[UI] Pixmap creation error: {pixmap_error}')
                self._set_label_text('Image creation failed.')
                return
            try:
                if hasattr(self.parent, 'card_image_label') and self.parent.card_image_label:
                    label_size = self.parent.card_image_label.size()
                    if label_size.width() > 10 and label_size.height() > 10:
                        scaled_pixmap = pixmap.scaled(label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.parent.card_image_label.setPixmap(scaled_pixmap)
                    else:
                        self.parent.card_image_label.setPixmap(pixmap)
            except Exception as display_error:
                print(f'[UI] Image display error: {display_error}')
                self._set_label_text('Display failed.')
        except Exception as critical_error:
            print(f'[UI] CRITICAL ERROR in on_image_loaded: {critical_error}')
            try:
                import traceback
                traceback.print_exc()
            except:
                pass
            self._set_label_text('Critical error occurred.')
        finally:
            try:
                if hasattr(self, 'image_worker') and self.image_worker:
                    self.image_worker.deleteLater()
                if hasattr(self, 'image_thread') and self.image_thread:
                    self.image_thread.quit()
                    self.image_thread.wait(1000)
                    self.image_thread.deleteLater()
                self.image_thread = None
                self.image_worker = None
            except Exception as cleanup_error:
                print(f'[UI] Cleanup error: {cleanup_error}')

    def _set_label_text(self, text: str):
        if hasattr(self.parent, 'card_image_label') and self.parent.card_image_label:
            self.parent.card_image_label.setText(text)

    def on_image_error(self, error_message: str):
        try:
            try:
                if hasattr(self.parent, 'fetch_image_button') and self.parent.fetch_image_button:
                    self.parent.fetch_image_button.setEnabled(True)
            except Exception as button_error:
                print(f'[UI] Error re-enabling button: {button_error}')
            try:
                if isinstance(error_message, str):
                    display_message = error_message
                    if len(display_message) > 150:
                        display_message = display_message[:150] + '...'
                    self._set_label_text(f'Image unavailable:\n{display_message}')
                else:
                    self._set_label_text('Image fetch failed (invalid error)')
            except Exception as message_error:
                print(f'[UI] Error displaying message: {message_error}')
                self._set_label_text('Image fetch failed')
        except Exception as critical_error:
            print(f'[UI] CRITICAL ERROR in on_image_error: {critical_error}')
            try:
                import traceback
                traceback.print_exc()
            except:
                pass
            self._set_label_text('Error handler failed')
        finally:
            try:
                if hasattr(self, 'image_thread'):
                    self.image_thread = None
                if hasattr(self, 'image_worker'):
                    self.image_worker = None
            except Exception as cleanup_error:
                print(f'[UI] Error during error cleanup: {cleanup_error}')

    def start_background_image_cache(self, cards: List[Card]):
        try:
            if hasattr(self, 'background_cache_thread') and self.background_cache_thread and self.background_cache_thread.isRunning():
                return
            self.parent.worker_manager.cleanup_worker('background_cache_worker')
            from workers.threads import cleanup_worker_thread
            cleanup_worker_thread(self.background_cache_thread, self.background_cache_worker)
            self.background_cache_thread = QThread()
            self.background_cache_worker = BackgroundImageCacheWorker(cards, self.api, max_concurrent=2)
            self.background_cache_worker.moveToThread(self.background_cache_thread)
            self.background_cache_thread.started.connect(self.background_cache_worker.process)
            self.background_cache_worker.image_cached.connect(self.on_image_cached)
            self.background_cache_worker.progress.connect(self.on_cache_progress)
            self.background_cache_worker.finished.connect(self.on_cache_finished)
            self.background_cache_worker.error.connect(self.on_cache_error)
            self.background_cache_worker.finished.connect(self.background_cache_thread.quit)
            self.background_cache_thread.finished.connect(self._cleanup_background_cache)
            self.background_cache_thread.start()
        except Exception as e:
            self.parent.handle_background_error('starting background cache', e, additional_context=f"cards_count: {(len(cards) if cards else 0)}, thread_running: {(self.background_cache_thread.isRunning() if self.background_cache_thread else 'None')}")

    def on_image_cached(self, scryfall_id: str, cache_path: str):
        self.cached_images[scryfall_id] = cache_path
        if hasattr(self, 'preview_card') and self.preview_card and (self.preview_card.scryfall_id == scryfall_id):
            self.load_cached_image(scryfall_id)

    def on_cache_progress(self, current: int, total: int):
        pass

    def on_cache_finished(self, total_cached: int):
        pass

    def _cleanup_background_cache(self):
        if self.background_cache_worker:
            self.background_cache_worker.deleteLater()
        if self.background_cache_thread:
            self.background_cache_thread.deleteLater()
        self.background_cache_worker = None
        self.background_cache_thread = None

    def on_cache_error(self, scryfall_id: str, error_message: str):
        if scryfall_id != 'SYSTEM':
            pass
        else:
            print(f'[BackgroundCache] System error: {error_message}')

    def load_cached_image(self, scryfall_id: str):
        try:
            cache_path = self.cached_images.get(scryfall_id)
            if not cache_path:
                cache_file = Config.IMAGE_CACHE_DIR / f'{scryfall_id}.jpg'
                if cache_file.exists():
                    cache_path = str(cache_file)
                    self.cached_images[scryfall_id] = cache_path
            if cache_path and os.path.exists(cache_path):
                with open(cache_path, 'rb') as f:
                    image_data = f.read()
                pixmap = QPixmap()
                if pixmap.loadFromData(image_data):
                    scaled_pixmap = pixmap.scaled(self.parent.card_image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.parent.card_image_label.setPixmap(scaled_pixmap)
                    self.parent.fetch_image_button.setVisible(False)
                    return True
        except Exception as e:
            self.parent.handle_silent_error('loading cached image', e)
        return False