import csv
import logging
import time
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from api.scryfall_api import MTGAPIError
from api.mtgjson_api import MTGJsonAPI
from core.booster_probability import BoosterProbabilityCalculator
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

    def __init__(self, csv_path: str, api: MTGJsonAPI, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.api = api
        self._is_cancelled = False
        self._last_progress_time = 0
        self._min_update_interval = 0.1  # 100ms between updates (10 updates/sec max)

    def cancel(self):
        self._is_cancelled = True

    def _should_emit_progress(self, current: int, total: int) -> bool:
        """Emit only if enough time passed OR operation complete"""
        if current == total:
            return True  # Always emit final update

        now = time.time()
        if now - self._last_progress_time >= self._min_update_interval:
            self._last_progress_time = now
            return True
        return False

    def process(self):
        """Process ManaBox CSV format - reads Quantity column and looks up cards by Scryfall ID in MTGJSON."""
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
                        total_quantity = int(row.get('Quantity', 0))
                        if total_quantity <= 0:
                            continue
                    except (ValueError, TypeError):
                        continue
                    scryfall_ids.add(scryfall_id)
                    card_quantities[scryfall_id] = card_quantities.get(scryfall_id, 0) + total_quantity
                    # Time-throttled progress updates during CSV parsing
                    if self._should_emit_progress(row_num, total_rows if total_rows > 0 else 1):
                        self.progress.emit(min(row_num, total_rows // 2), total_rows if total_rows > 0 else 1)
            if total_rows == 0:
                self.error.emit('CSV file appears to be empty or has no valid data.')
                return
            unique_ids = list(scryfall_ids)
            if not unique_ids:
                self.error.emit('No valid Scryfall IDs found in CSV file.')
                return
            if not check_memory_safety("ManaBox Import - Pre-API", 512):
                self.error.emit('Insufficient memory available for import. Please close other applications and try again.')
                return
            self.progress.emit(0, len(unique_ids))
            try:
                # Check if MTGJSON AllPrintings index is available
                if not self.api.ensure_allprintings_loaded():
                    self.error.emit('MTGJSON database not available. Please complete first-time setup.')
                    return

                cards = []
                for i, scryfall_id in enumerate(unique_ids):
                    if self._is_cancelled:
                        return
                    try:
                        # Fetch card from MTGJSON by Scryfall ID
                        card_data = self.api.fetch_card_by_scryfall_id(scryfall_id)

                        # Use set name from MTGJSON data
                        set_name = card_data.get('_set_name', card_data.get('setCode', 'N/A'))

                        # Create Card from MTGJSON data
                        card = Card.from_mtgjson_dict(card_data, set_name)
                        card.quantity = card_quantities[scryfall_id]
                        cards.append(card)

                    except MTGAPIError as api_error:
                        print(f'Card lookup failed for {scryfall_id}: {api_error}')
                        continue
                    except Exception as processing_error:
                        print(f'Error processing card {i + 1}/{len(unique_ids)} (ID: {scryfall_id}): {processing_error}')
                        continue

                    # Time-throttled progress updates during card processing
                    if self._should_emit_progress(i + 1, len(unique_ids)):
                        try:
                            self.progress.emit(i + 1, len(unique_ids))
                        except Exception as progress_error:
                            print(f'Error emitting progress signal: {progress_error}')

                    if i % 100 == 0 and (not check_memory_safety("ManaBox Import - Processing", 800)):
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

class LionsEyeImportWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, csv_path: str, api: MTGJsonAPI, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.api = api
        self._is_cancelled = False
        self._last_progress_time = 0
        self._min_update_interval = 0.1  # 100ms between updates (10 updates/sec max)

    def cancel(self):
        self._is_cancelled = True

    def _should_emit_progress(self, current: int, total: int) -> bool:
        """Emit only if enough time passed OR operation complete"""
        if current == total:
            return True  # Always emit final update

        now = time.time()
        if now - self._last_progress_time >= self._min_update_interval:
            self._last_progress_time = now
            return True
        return False

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
                    # Time-throttled progress updates during CSV parsing
                    if self._should_emit_progress(row_num, total_rows if total_rows > 0 else 1):
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
                # Check if MTGJSON AllPrintings index is available
                if not self.api.ensure_allprintings_loaded():
                    self.error.emit('MTGJSON database not available. Please complete first-time setup.')
                    return

                cards = []
                for i, scryfall_id in enumerate(unique_ids):
                    if self._is_cancelled:
                        return
                    try:
                        # Fetch card from MTGJSON by Scryfall ID
                        card_data = self.api.fetch_card_by_scryfall_id(scryfall_id)

                        # Use set name from MTGJSON data
                        set_name = card_data.get('_set_name', card_data.get('setCode', 'N/A'))

                        # Create Card from MTGJSON data
                        card = Card.from_mtgjson_dict(card_data, set_name)
                        card.quantity = card_quantities[scryfall_id]
                        cards.append(card)

                    except MTGAPIError as api_error:
                        print(f'Card lookup failed for {scryfall_id}: {api_error}')
                        continue
                    except Exception as processing_error:
                        print(f'Error processing card {i + 1}/{len(unique_ids)} (ID: {scryfall_id}): {processing_error}')
                        continue

                    # Time-throttled progress updates during card processing
                    if self._should_emit_progress(i + 1, len(unique_ids)):
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

# ImageFetchWorker and BackgroundImageCacheWorker removed in MTGJSON migration
# Images are no longer displayed or cached in this version

class SetAnalysisWorker(QObject):
    progress = pyqtSignal(int, int)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, options: Dict[str, Any], api: MTGJsonAPI, parent=None):
        super().__init__(parent)
        self.options = options
        self.api = api
        self.mtgjson_api = api  # Now the same API
        self._is_cancelled = False
        self.raw_cards: list[dict] = []
        self._last_progress_time = 0
        self._min_update_interval = 0.1  # 100ms between updates (10 updates/sec max)
        self.logger = logging.getLogger(__name__)

    def cancel(self):
        self._is_cancelled = True

    def _should_emit_progress(self, current: int, total: int) -> bool:
        """Emit only if enough time passed OR operation complete"""
        if current == total:
            return True  # Always emit final update

        now = time.time()
        if now - self._last_progress_time >= self._min_update_interval:
            self._last_progress_time = now
            return True
        return False

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
                    set_cards = self.mtgjson_api.fetch_set_cards(set_code)
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

            # Determine weighting method: booster probabilities or rarity weights
            preset = self.options.get('preset', 'default')
            use_booster_probabilities = (preset == 'play_booster')

            booster_probabilities = None
            rarity_weights = None

            if use_booster_probabilities:
                try:
                    booster_probabilities = self._get_booster_probabilities(set_codes)
                    # Also get rarity weights as fallback for cards without booster data
                    rarity_weights = self._get_rarity_weights()
                except MTGAPIError as e:
                    # Booster data unavailable - show error and halt
                    self.error.emit(str(e))
                    return
            else:
                rarity_weights = self._get_rarity_weights()

            letter_counts = {}
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
                card_uuid = card_data.get('uuid')  # MTGJSON UUID (NOT Scryfall ID!)

                if first_letter not in letter_counts:
                    letter_counts[first_letter] = {'total_raw': 0, 'total_weighted': 0, 'rarity': {'common': 0, 'uncommon': 0, 'rare': 0, 'mythic': 0}, 'set_breakdown': {}}

                letter_counts[first_letter]['total_raw'] += 1

                # Calculate weighted value based on method
                if use_booster_probabilities and booster_probabilities:
                    # Use booster probability if available, fallback to rarity weight
                    card_weight = booster_probabilities.get(card_uuid, rarity_weights.get(rarity, 1))
                else:
                    # Use rarity-based weight
                    card_weight = rarity_weights.get(rarity, 1)

                letter_counts[first_letter]['total_weighted'] += card_weight
                letter_counts[first_letter]['rarity'][rarity] = letter_counts[first_letter]['rarity'].get(rarity, 0) + 1
                if source_set not in letter_counts[first_letter]['set_breakdown']:
                    letter_counts[first_letter]['set_breakdown'][source_set] = 0
                letter_counts[first_letter]['set_breakdown'][source_set] += 1
                # Time-throttled progress updates during card analysis
                if self._should_emit_progress(i + 1, total_cards):
                    self.progress.emit(i + 1, total_cards)
            if self._is_cancelled:
                return
            if self.options.get('group', False):
                letter_counts = self._group_low_count_letters(letter_counts)
            weighted = self.options.get('weighted', False)
            sort_key = 'total_weighted' if weighted else 'total_raw'
            sorted_groups = sorted(letter_counts.items(), key=lambda x: x[1][sort_key], reverse=True)
            result = {'set_codes': set_codes, 'total_cards_analyzed': len(cards_to_analyze), 'sorted_groups': sorted_groups, 'weighted': weighted, 'preset': self.options.get('preset', 'default'), 'raw_cards': self.raw_cards}
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
        weights = {'default': {'mythic': 10, 'rare': 3, 'uncommon': 1, 'common': 0.25}, 'dynamic': {'mythic': 8, 'rare': 4, 'uncommon': 1.5, 'common': 0.5}}
        return weights.get(preset, weights['default'])

    def _get_booster_probabilities(self, set_codes: list[str]) -> Optional[Dict[str, float]]:
        """
        Fetch and calculate booster probabilities from MTGJSON data.
        Supports both single-set and multi-set analysis.

        Args:
            set_codes: List of set codes to fetch booster data for

        Returns:
            Dictionary mapping card UUID to expected pulls per pack,
            or None if data unavailable

        Raises:
            MTGAPIError: If booster data is unavailable (caller should handle)
        """
        all_probabilities = {}
        failed_sets = []
        successful_sets = []

        for set_code in set_codes:
            # Fetch booster config from MTGJSON
            self.status_update.emit(f'Fetching booster configuration from MTGJSON for {set_code.upper()}...')

            try:
                booster_data = self.mtgjson_api.fetch_booster_config(set_code)

                # Check if we're using parent set's booster data
                if 'source_set' in booster_data:
                    source_set = booster_data['source_set']
                    self.logger.info(f"Using booster data from parent set '{source_set.upper()}' for child set '{set_code.upper()}'")
                    self.status_update.emit(f"Set '{set_code.upper()}' using parent '{source_set.upper()}' booster configuration...")

            except MTGAPIError as e:
                # Track failed sets but continue with others
                if e.error_type == 'no_booster_data':
                    failed_sets.append(set_code)
                    self.logger.warning(f"No booster data available for set '{set_code.upper()}'")
                    continue
                raise

            # Calculate probabilities
            self.status_update.emit(f'Calculating card probabilities for {set_code.upper()}...')

            try:
                calculator = BoosterProbabilityCalculator(booster_data)
                set_probabilities = calculator.calculate_card_probabilities()

                # Merge into combined probabilities
                all_probabilities.update(set_probabilities)
                successful_sets.append(set_code)

                # Log summary stats for debugging
                stats = calculator.get_summary_statistics()
                self.logger.info(
                    f'Booster probability stats for {set_code}: '
                    f'{stats["total_unique_cards"]} cards, '
                    f'avg={stats["avg_probability"]:.3f}, '
                    f'max={stats["max_probability"]:.3f}'
                )

            except ValueError as e:
                failed_sets.append(set_code)
                self.logger.error(f'Failed to calculate probabilities for {set_code}: {str(e)}')
                continue

        # If all sets failed, raise an error with helpful context
        if not successful_sets:
            if len(set_codes) == 1:
                # Try to get set metadata for better error message
                set_code = set_codes[0]
                try:
                    set_metadata = self.mtgjson_api.fetch_set_metadata(set_code)
                    set_type = set_metadata.get('type', 'unknown')
                    set_name = set_metadata.get('name', set_code.upper())

                    # Provide context-specific guidance based on set type
                    if set_type in ['masterpiece', 'promo', 'token', 'memorabilia']:
                        guidance = (
                            f"{set_name} ({set_code.upper()}) is a special insert set without booster data.\n\n"
                            f"💡 These cards often appear in other sets' boosters. Try:\n"
                            f"• Analyzing with the main set (e.g., 'spm,{set_code.lower()}' for complete product coverage)\n"
                            f"• Using 'default' or 'dynamic' preset for rarity-based analysis\n\n"
                            f"This gives you complete coverage of all cards in the product."
                        )
                    elif set_type == 'commander':
                        guidance = (
                            f"{set_name} ({set_code.upper()}) is a Commander product without booster data.\n\n"
                            f"💡 Commander products are pre-constructed decks, not randomized boosters.\n\n"
                            f"Use 'default' or 'dynamic' preset for rarity-based analysis instead."
                        )
                    elif set_type == 'draft_innovation':
                        guidance = (
                            f"{set_name} ({set_code.upper()}) is a special draft product.\n\n"
                            f"💡 These have unique distribution. Try:\n"
                            f"• Using 'default' or 'dynamic' preset for rarity-based analysis\n"
                            f"• Checking the set's specific product documentation"
                        )
                    else:
                        guidance = (
                            f"{set_name} ({set_code.upper()}) does not have booster data available.\n\n"
                            f"This usually means:\n"
                            f"• The set was not sold in booster packs\n"
                            f"• The set is too old/new for MTGJSON coverage\n"
                            f"• The set only had special product releases\n\n"
                            f"Use 'default' or 'dynamic' preset for rarity-based analysis instead."
                        )
                except:
                    # Fallback if metadata fetch fails
                    guidance = (
                        f"Set '{set_code.upper()}' does not have booster pack data available.\n\n"
                        f"This usually means:\n"
                        f"• The set was not sold in booster packs\n"
                        f"• The set is too old or too new for MTGJSON coverage\n"
                        f"• The set only had special product releases\n\n"
                        f"Please use the 'default' or 'dynamic' weight preset instead."
                    )

                raise MTGAPIError(guidance, 'no_booster_data', {'set_code': set_code})
            else:
                raise MTGAPIError(
                    f"None of the specified sets have booster pack data available.\n\n"
                    f"Failed sets: {', '.join(s.upper() for s in failed_sets)}\n\n"
                    f"💡 Tip: Some sets (like masterpieces) don't have direct booster data.\n"
                    f"Try analyzing them with their main set for complete product coverage.\n\n"
                    f"Or use 'default' or 'dynamic' preset for rarity-based analysis instead.",
                    'no_booster_data',
                    {'failed_sets': failed_sets}
                )

        # If some sets failed, log a warning
        if failed_sets:
            warning_msg = f"Warning: Booster data unavailable for {len(failed_sets)} set(s): {', '.join(s.upper() for s in failed_sets)}. Using default weights for cards from these sets."
            self.status_update.emit(warning_msg)
            self.logger.warning(warning_msg)

        return all_probabilities

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