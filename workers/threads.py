import csv
from typing import Any, Dict

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from api.scryfall_api import MTGAPIError, ScryfallAPI
from core.card_validator import CardValidator
from core.constants import Config
from core.models import Card


def get_memory_usage_mb():
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        return None

def check_memory_safety(operation_name: str, max_mb: int=1024) -> bool:
    current_mb = get_memory_usage_mb()
    if current_mb is not None and current_mb > max_mb:
        print(f'Warning: {operation_name} - High memory usage: {current_mb:.1f}MB')
        return False
    return True

class CsvImportWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, csv_path: str, api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.api = api
        self._is_cancelled = False

class LionsEyeImportWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, csv_path: str, api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.api = api
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def process(self):
        try:
            scryfall_ids = set()
            card_quantities = {}
            total_rows = 0
            with open(self.csv_path, 'r', encoding='utf-8', newline='') as file:
                reader = csv.DictReader(file)
                for row_num, row in enumerate(reader):
                    if self._is_cancelled:
                        return
                    if row_num > 50000:
                        self.error.emit('CSV file too large (>50,000 rows). Please split into smaller files.')
                        return
                    total_rows += 1
                    scryfall_id = row.get('Scryfall ID', '').strip()
                    if not scryfall_id:
                        continue
                    try:
                        non_foil_qty = int(row.get('Number of Non-foil', 0))
                        foil_qty = int(row.get('Number of Foil', 0))
                        total_quantity = non_foil_qty + foil_qty
                        if total_quantity <= 0:
                            continue
                    except (ValueError, TypeError):
                        continue
                    scryfall_ids.add(scryfall_id)
                    card_quantities[scryfall_id] = card_quantities.get(scryfall_id, 0) + total_quantity
                    if row_num % 100 == 0:
                        self.progress.emit(min(row_num, total_rows // 2), total_rows if total_rows > 0 else 1)
            if total_rows == 0:
                self.error.emit('CSV file appears to be empty or has no valid data.')
                return
            unique_ids = list(scryfall_ids)
            if not unique_ids:
                self.error.emit('No valid Scryfall IDs found in CSV file.')
                return
            if not check_memory_safety("Lion's Eye Import - Pre-API", 512):
                self.error.emit('Insufficient memory available for import. Please close other applications and try again.')
                return
            self.progress.emit(0, len(unique_ids))
            try:
                identifiers = [{'id': card_id} for card_id in unique_ids]
                fetched_cards = self.api.fetch_card_collection(identifiers)
                cards = []
                fetched_by_id = {card['id']: card for card in fetched_cards}
                for i, scryfall_id in enumerate(unique_ids):
                    if self._is_cancelled:
                        return
                    try:
                        if scryfall_id in fetched_by_id:
                            card_data = fetched_by_id[scryfall_id]
                            is_valid, error_message = CardValidator.validate_card_data(card_data, scryfall_id)
                            if not is_valid:
                                print(f'Warning: {error_message}')
                                continue
                            try:
                                card = Card.from_scryfall_dict(card_data)
                                card.quantity = card_quantities[scryfall_id]
                                cards.append(card)
                            except Exception as card_error:
                                print(f'Error creating card from data for {scryfall_id}: {card_error}')
                                print(f"Card data keys: {(list(card_data.keys()) if isinstance(card_data, dict) else 'Not a dict')}")
                                continue
                        else:
                            print(f'Warning: Scryfall ID {scryfall_id} not found in API response')
                    except Exception as processing_error:
                        print(f'Error processing card {i + 1}/{len(unique_ids)} (ID: {scryfall_id}): {processing_error}')
                        continue
                    if i % 10 == 0 or i == len(unique_ids) - 1:
                        try:
                            self.progress.emit(i + 1, len(unique_ids))
                        except Exception as progress_error:
                            print(f'Error emitting progress signal: {progress_error}')
                    if i % 100 == 0 and (not check_memory_safety("Lion's Eye Import - Processing", 800)):
                        self.error.emit('Memory usage too high during import. Process aborted.')
                        return
                if not cards:
                    self.error.emit('No valid cards could be loaded from the CSV file.')
                    return
                self.finished.emit(cards)
            except MTGAPIError as e:
                self.error.emit(f'API Error: {e}')
            except Exception as e:
                self.error.emit(f'Error fetching card data: {str(e)}')
        except FileNotFoundError:
            self.error.emit(f'CSV file not found: {self.csv_path}')
        except PermissionError:
            self.error.emit(f'Permission denied reading file: {self.csv_path}')
        except UnicodeDecodeError:
            self.error.emit('CSV file encoding error. Please ensure the file is saved as UTF-8.')
        except csv.Error as e:
            self.error.emit(f'CSV parsing error: {str(e)}')
        except Exception as e:
            self.error.emit(f'Unexpected error during import: {str(e)}')

class ImageFetchWorker(QObject):
    finished = pyqtSignal(bytes, str)
    error = pyqtSignal(str)

    def __init__(self, image_uri: str, scryfall_id: str, api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.image_uri = image_uri
        self.scryfall_id = scryfall_id
        self.api = api
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def process(self):
        try:
            if self._is_cancelled:
                return
            print(f'[ImageFetch] Starting fetch for {self.scryfall_id}')
            try:
                if not self.image_uri or not self.scryfall_id:
                    self.error.emit('Missing image URI or Scryfall ID')
                    return
                if not isinstance(self.image_uri, str) or not isinstance(self.scryfall_id, str):
                    self.error.emit('Invalid data types for URI or ID')
                    return
                if not (self.image_uri.startswith('http://') or self.image_uri.startswith('https://')):
                    self.error.emit(f'Invalid URI format: {self.image_uri[:50]}...')
                    return
                print(f'[ImageFetch] URI validated: {self.image_uri[:50]}...')
            except Exception as validation_error:
                print(f'[ImageFetch] Validation error: {validation_error}')
                self.error.emit(f'Validation failed: {str(validation_error)}')
                return
            try:
                print(f'[ImageFetch] Calling API...')
                image_data = self.api.fetch_image(self.image_uri, self.scryfall_id)
                if self._is_cancelled:
                    return
                print(f'[ImageFetch] API returned {(len(image_data) if image_data else 0)} bytes')
            except Exception as api_error:
                print(f'[ImageFetch] API call failed: {api_error}')
                if not self._is_cancelled:
                    error_msg = str(api_error)
                    if len(error_msg) > 100:
                        error_msg = error_msg[:100] + '...'
                    self.error.emit(f'Download failed: {error_msg}')
                return
            try:
                if not image_data:
                    self.error.emit('No image data received')
                    return
                if not isinstance(image_data, bytes):
                    self.error.emit('Invalid image data format')
                    return
                if len(image_data) < 100:
                    self.error.emit(f'Image too small: {len(image_data)} bytes')
                    return
                print(f'[ImageFetch] Data validated: {len(image_data)} bytes')
            except Exception as data_error:
                print(f'[ImageFetch] Data validation error: {data_error}')
                self.error.emit(f'Data validation failed: {str(data_error)}')
                return
            try:
                if not self._is_cancelled:
                    print(f'[ImageFetch] Emitting success signal')
                    self.finished.emit(image_data, self.scryfall_id)
                else:
                    print(f'[ImageFetch] Cancelled before emission')
            except Exception as emit_error:
                print(f'[ImageFetch] Signal emission error: {emit_error}')
        except Exception as critical_error:
            print(f'[ImageFetch] CRITICAL ERROR: {critical_error}')
            print(f'[ImageFetch] Error type: {type(critical_error)}')
            try:
                import traceback
                traceback.print_exc()
            except:
                pass
            try:
                if not self._is_cancelled:
                    self.error.emit('Critical error occurred')
            except:
                print(f'[ImageFetch] Could not emit error signal')
        finally:
            print(f'[ImageFetch] Process completed (cancelled: {self._is_cancelled})')

class BackgroundImageCacheWorker(QObject):
    progress = pyqtSignal(int, int)
    image_cached = pyqtSignal(str, str)
    finished = pyqtSignal(int)
    error = pyqtSignal(str, str)

    def __init__(self, cards: list, api: ScryfallAPI, max_concurrent: int=3, parent=None):
        super().__init__(parent)
        self.cards = cards
        self.api = api
        self.max_concurrent = max_concurrent
        self._is_cancelled = False
        self._processed = 0
        self._successful = 0

    def cancel(self):
        self._is_cancelled = True

    def process(self):
        if self._is_cancelled:
            return
        try:
            print(f'[BackgroundCache] Starting cache process for {len(self.cards)} cards')
            cards_to_cache = []
            for card in self.cards:
                if self._is_cancelled:
                    return
                if not hasattr(card, 'image_uri') or not card.image_uri:
                    continue
                cache_file = Config.IMAGE_CACHE_DIR / f'{card.scryfall_id}.jpg'
                if cache_file.exists():
                    continue
                cards_to_cache.append(card)
            print(f'[BackgroundCache] {len(cards_to_cache)} images need caching')
            if not cards_to_cache:
                print(f'[BackgroundCache] All images already cached, finishing')
                import time
                time.sleep(0.1)
                self.finished.emit(0)
                return
            total_cards = len(cards_to_cache)
            batch_size = min(self.max_concurrent, 5)
            for i in range(0, len(cards_to_cache), batch_size):
                if self._is_cancelled:
                    return
                batch = cards_to_cache[i:i + batch_size]
                print(f'[BackgroundCache] Processing batch {i // batch_size + 1} ({len(batch)} cards)')
                for card in batch:
                    if self._is_cancelled:
                        return
                    try:
                        print(f'[BackgroundCache] Caching image for {card.name}')
                        import time
                        time.sleep(0.1)
                        image_data = self.api.fetch_image(card.image_uri, card.scryfall_id)
                        if image_data and len(image_data) > 100:
                            cache_path = str(Config.IMAGE_CACHE_DIR / f'{card.scryfall_id}.jpg')
                            self.image_cached.emit(card.scryfall_id, cache_path)
                            self._successful += 1
                            print(f'[BackgroundCache] Successfully cached {card.name}')
                    except Exception as e:
                        print(f'[BackgroundCache] Failed to cache {card.name}: {e}')
                        self.error.emit(card.scryfall_id, str(e))
                    self._processed += 1
                    if self._processed % 3 == 0 or self._processed == total_cards:
                        self.progress.emit(self._processed, total_cards)
                if i + batch_size < len(cards_to_cache):
                    import time
                    time.sleep(0.5)
            print(f'[BackgroundCache] Completed: {self._successful}/{total_cards} images cached')
            self.finished.emit(self._successful)
        except Exception as e:
            print(f'[BackgroundCache] Critical error: {e}')
            import traceback
            traceback.print_exc()
            self.error.emit('SYSTEM', f'Background cache failed: {str(e)}')

class SetAnalysisWorker(QObject):
    progress = pyqtSignal(int, int)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, options: Dict[str, Any], api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.options = options
        self.api = api
        self._is_cancelled = False
        self.raw_cards: list[dict] = []

    def cancel(self):
        self._is_cancelled = True

    def process(self):
        try:
            set_codes = self.options.get('set_codes', [self.options.get('set_code', '')])
            all_cards = []
            set_breakdown = {}
            total_sets = len(set_codes)
            for i, set_code in enumerate(set_codes):
                if self._is_cancelled:
                    return
                self.status_update.emit(f"Fetching cards for set '{set_code.upper()}' ({i + 1}/{total_sets})...")
                try:
                    set_cards = self.api.fetch_set(set_code)
                except MTGAPIError as e:
                    self.error.emit(f"Error fetching set '{set_code}': {str(e)}")
                    return
                if self._is_cancelled:
                    return
                if not set_cards:
                    self.error.emit(f"No cards found for set '{set_code}'")
                    return
                for card in set_cards:
                    card['_source_set'] = set_code
                all_cards.extend(set_cards)
                set_breakdown[set_code] = len(set_cards)
            if self._is_cancelled:
                return
            if not all_cards:
                self.error.emit('No cards found in any of the specified sets')
                return
            self.raw_cards = all_cards.copy()
            self.status_update.emit(f'Analyzing {len(all_cards)} cards from {total_sets} set(s)...')
            owned_cards = self.options.get('owned_cards', [])
            owned_by_id = {}
            if owned_cards:
                owned_by_id = {card.scryfall_id: card for card in owned_cards}
            cards_to_analyze = all_cards
            if self.options.get('owned_cards') and owned_by_id:
                original_count = len(all_cards)
                cards_to_analyze = [card for card in all_cards if card['id'] not in owned_by_id]
                owned_count = original_count - len(cards_to_analyze)
                self.status_update.emit(f'Found {owned_count} owned cards, analyzing {len(cards_to_analyze)} missing cards...')
            if self._is_cancelled:
                return
            letter_counts = {}
            rarity_weights = self._get_rarity_weights()
            total_cards = len(cards_to_analyze)
            for i, card_data in enumerate(cards_to_analyze):
                if self._is_cancelled:
                    return
                card_name = card_data.get('name', '')
                if not card_name:
                    continue
                first_letter = card_name[0].upper()
                rarity = card_data.get('rarity', 'common')
                source_set = card_data.get('_source_set', 'unknown')
                if first_letter not in letter_counts:
                    letter_counts[first_letter] = {'total_raw': 0, 'total_weighted': 0, 'rarity': {'common': 0, 'uncommon': 0, 'rare': 0, 'mythic': 0}, 'set_breakdown': {}}
                letter_counts[first_letter]['total_raw'] += 1
                letter_counts[first_letter]['total_weighted'] += rarity_weights.get(rarity, 1)
                letter_counts[first_letter]['rarity'][rarity] = letter_counts[first_letter]['rarity'].get(rarity, 0) + 1
                if source_set not in letter_counts[first_letter]['set_breakdown']:
                    letter_counts[first_letter]['set_breakdown'][source_set] = 0
                letter_counts[first_letter]['set_breakdown'][source_set] += 1
                if i % 100 == 0 or i == total_cards - 1:
                    self.progress.emit(i, total_cards)
            if self._is_cancelled:
                return
            if self.options.get('group', False):
                letter_counts = self._group_low_count_letters(letter_counts)
            weighted = self.options.get('weighted', False)
            sort_key = 'total_weighted' if weighted else 'total_raw'
            sorted_groups = sorted(letter_counts.items(), key=lambda x: x[1][sort_key], reverse=True)
            result = {'set_codes': set_codes, 'total_cards_analyzed': len(cards_to_analyze), 'sorted_groups': sorted_groups, 'weighted': weighted, 'preset': self.options.get('preset', 'default')}
            if owned_by_id:
                result['original_set_size'] = len(all_cards)
                result['owned_count'] = len(all_cards) - len(cards_to_analyze)
                result['missing_count'] = len(cards_to_analyze)
            self.progress.emit(total_cards, total_cards)
            self.finished.emit(result)
        except Exception as e:
            if not self._is_cancelled:
                self.error.emit(f'Analysis failed: {str(e)}')

    def _get_rarity_weights(self) -> Dict[str, float]:
        preset = self.options.get('preset', 'default')
        weights = {'default': {'mythic': 10, 'rare': 3, 'uncommon': 1, 'common': 0.25}, 'play_booster': {'mythic': 10, 'rare': 5, 'uncommon': 1, 'common': 0.25}, 'dynamic': {'mythic': 8, 'rare': 4, 'uncommon': 1.5, 'common': 0.5}}
        return weights.get(preset, weights['default'])

    def _group_low_count_letters(self, letter_counts: Dict) -> Dict:
        threshold = self.options.get('threshold', 20)
        high_count = {}
        low_count_letters = []
        for letter, data in letter_counts.items():
            if data['total_raw'] >= threshold:
                high_count[letter] = data
            else:
                low_count_letters.append((letter, data))
        if low_count_letters:
            low_count_letters.sort(key=lambda x: x[0])
            current_group = []
            current_total = 0
            group_number = 1
            for letter, data in low_count_letters:
                current_group.append(letter)
                current_total += data['total_raw']
                if current_total >= threshold or letter == low_count_letters[-1][0]:
                    group_name = ''.join(sorted(current_group))
                    if len(current_group) == 1:
                        group_key = current_group[0]
                    else:
                        group_key = f'({group_name})'
                        group_number += 1
                    combined_data = {'total_raw': sum((letter_counts[l]['total_raw'] for l in current_group)), 'total_weighted': sum((letter_counts[l]['total_weighted'] for l in current_group)), 'rarity': {'common': 0, 'uncommon': 0, 'rare': 0, 'mythic': 0}, 'set_breakdown': {}}
                    for l in current_group:
                        for rarity in combined_data['rarity']:
                            combined_data['rarity'][rarity] += letter_counts[l]['rarity'].get(rarity, 0)
                        for set_code, count in letter_counts[l].get('set_breakdown', {}).items():
                            if set_code not in combined_data['set_breakdown']:
                                combined_data['set_breakdown'][set_code] = 0
                            combined_data['set_breakdown'][set_code] += count
                    high_count[group_key] = combined_data
                    current_group = []
                    current_total = 0
        return high_count

class WorkerManager:

    def __init__(self):
        self.workers = {}

    def add_worker(self, name: str, thread: QThread, worker: QObject):
        self.workers[name] = (thread, worker)

    def remove_worker(self, name: str):
        if name in self.workers:
            del self.workers[name]

    def cleanup_worker(self, name: str):
        if name in self.workers:
            thread, worker = self.workers[name]
            self._cleanup_worker(thread, worker)
            del self.workers[name]

    def cleanup_all(self):
        for name, (thread, worker) in self.workers.items():
            self._cleanup_worker(thread, worker)
        self.workers.clear()

    def _cleanup_worker(self, thread: QThread | None, worker: QObject | None):
        try:
            if worker and hasattr(worker, 'cancel'):
                worker.cancel()
            if thread and thread.isRunning():
                thread.quit()
                if not thread.wait(2000):
                    print(f'Warning: Thread {thread} did not quit gracefully, terminating.')
                    thread.terminate()
                    thread.wait(1000)
        except RuntimeError:
            pass
        except Exception as e:
            print(f'Warning: Error during thread cleanup: {e}')

    def has_worker(self, name: str) -> bool:
        return name in self.workers

    def get_worker(self, name: str) -> tuple[QThread | None, QObject | None]:
        return self.workers.get(name, (None, None))

def cleanup_worker_thread(thread: QThread | None, worker: QObject | None):
    manager = WorkerManager()
    manager._cleanup_worker(thread, worker)