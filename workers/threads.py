# workers/threads.py

import csv
from typing import Any, Dict

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from api.scryfall_api import MTGAPIError, ScryfallAPI
from core.constants import Config
from core.models import Card
from core.card_validator import CardValidator


def get_memory_usage_mb():
    """Get current memory usage in MB"""
    try:
        import psutil

        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        return None


def check_memory_safety(operation_name: str, max_mb: int = 1024) -> bool:
    """Check if memory usage is safe to continue operations"""
    current_mb = get_memory_usage_mb()
    if current_mb is not None and current_mb > max_mb:
        print(f"Warning: {operation_name} - High memory usage: {current_mb:.1f}MB")
        return False
    # If psutil is not available, assume memory is safe
    return True


class CsvImportWorker(QObject):
    """Worker object for CSV import operations"""

    # Signals
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list)  # cards
    error = pyqtSignal(str)  # error message

    def __init__(self, csv_path: str, api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.api = api
        self._is_cancelled = False


class LionsEyeImportWorker(QObject):
    """Worker object for Lion's Eye app CSV import operations"""

    # Signals
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list)  # cards
    error = pyqtSignal(str)  # error message

    def __init__(self, csv_path: str, api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.api = api
        self._is_cancelled = False

    def cancel(self):
        """Cancel the import operation"""
        self._is_cancelled = True

    def process(self):
        """Main processing function for Lion's Eye CSV format"""
        try:
            # Stream CSV processing to avoid loading entire file into memory
            scryfall_ids = set()
            card_quantities = {}
            total_rows = 0

            # First pass: count rows and collect IDs without loading everything into memory
            with open(self.csv_path, "r", encoding="utf-8", newline="") as file:
                reader = csv.DictReader(file)

                for row_num, row in enumerate(reader):
                    if self._is_cancelled:
                        return

                    # Memory safety: limit processing if file is too large
                    if row_num > 50000:  # Reasonable limit for most collections
                        self.error.emit(
                            "CSV file too large (>50,000 rows). Please split into smaller files."
                        )
                        return

                    total_rows += 1

                    # Lion's Eye format uses "Scryfall ID" column
                    scryfall_id = row.get("Scryfall ID", "").strip()
                    if not scryfall_id:
                        continue

                    # Lion's Eye format has separate foil and non-foil quantities
                    try:
                        non_foil_qty = int(row.get("Number of Non-foil", 0))
                        foil_qty = int(row.get("Number of Foil", 0))
                        total_quantity = non_foil_qty + foil_qty

                        if total_quantity <= 0:
                            continue
                    except (ValueError, TypeError):
                        continue

                    scryfall_ids.add(scryfall_id)
                    card_quantities[scryfall_id] = (
                        card_quantities.get(scryfall_id, 0) + total_quantity
                    )

                    # Throttled progress to prevent signal overload
                    if row_num % 100 == 0:
                        self.progress.emit(
                            min(row_num, total_rows // 2),
                            total_rows if total_rows > 0 else 1,
                        )

            if total_rows == 0:
                self.error.emit("CSV file appears to be empty or has no valid data.")
                return

            unique_ids = list(scryfall_ids)
            if not unique_ids:
                self.error.emit("No valid Scryfall IDs found in CSV file.")
                return

            # Memory safety check before API calls
            if not check_memory_safety("Lion's Eye Import - Pre-API", 512):
                self.error.emit(
                    "Insufficient memory available for import. Please close other applications and try again."
                )
                return

            # Fetch card data using collection endpoint for efficiency
            self.progress.emit(0, len(unique_ids))

            try:
                # Prepare identifiers for collection endpoint
                identifiers = [{"id": card_id} for card_id in unique_ids]

                # Use batch fetching for efficiency
                fetched_cards = self.api.fetch_card_collection(identifiers)

                # Process fetched cards
                cards = []
                fetched_by_id = {card["id"]: card for card in fetched_cards}

                for i, scryfall_id in enumerate(unique_ids):
                    if self._is_cancelled:
                        return

                    try:
                        if scryfall_id in fetched_by_id:
                            card_data = fetched_by_id[scryfall_id]

                            # Validate card data before processing using centralized validator
                            is_valid, error_message = CardValidator.validate_card_data(
                                card_data, scryfall_id
                            )
                            if not is_valid:
                                print(f"Warning: {error_message}")
                                continue

                            # Create card with additional error handling
                            try:
                                card = Card.from_scryfall_dict(card_data)
                                card.quantity = card_quantities[scryfall_id]
                                cards.append(card)
                            except Exception as card_error:
                                print(
                                    f"Error creating card from data for {scryfall_id}: {card_error}"
                                )
                                print(
                                    f"Card data keys: {list(card_data.keys()) if isinstance(card_data, dict) else 'Not a dict'}"
                                )
                                continue
                        else:
                            print(
                                f"Warning: Scryfall ID {scryfall_id} not found in API response"
                            )

                    except Exception as processing_error:
                        print(
                            f"Error processing card {i+1}/{len(unique_ids)} (ID: {scryfall_id}): {processing_error}"
                        )
                        # Continue processing other cards instead of failing completely
                        continue

                    # FIXED: Throttled progress updates to prevent signal overload
                    if i % 10 == 0 or i == len(unique_ids) - 1:
                        try:
                            self.progress.emit(i + 1, len(unique_ids))
                        except Exception as progress_error:
                            print(f"Error emitting progress signal: {progress_error}")

                    # Periodic memory check during processing
                    if i % 100 == 0 and not check_memory_safety(
                        "Lion's Eye Import - Processing", 800
                    ):
                        self.error.emit(
                            "Memory usage too high during import. Process aborted."
                        )
                        return

                if not cards:
                    self.error.emit("No valid cards could be loaded from the CSV file.")
                    return

                self.finished.emit(cards)

            except MTGAPIError as e:
                self.error.emit(f"API Error: {e}")
            except Exception as e:
                self.error.emit(f"Error fetching card data: {str(e)}")

        except FileNotFoundError:
            self.error.emit(f"CSV file not found: {self.csv_path}")
        except PermissionError:
            self.error.emit(f"Permission denied reading file: {self.csv_path}")
        except UnicodeDecodeError:
            self.error.emit(
                "CSV file encoding error. Please ensure the file is saved as UTF-8."
            )
        except csv.Error as e:
            self.error.emit(f"CSV parsing error: {str(e)}")
        except Exception as e:
            self.error.emit(f"Unexpected error during import: {str(e)}")


class ImageFetchWorker(QObject):
    """Worker object for image fetching operations"""

    # Signals
    finished = pyqtSignal(bytes, str)  # image_data, scryfall_id
    error = pyqtSignal(str)  # error message

    def __init__(self, image_uri: str, scryfall_id: str, api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.image_uri = image_uri
        self.scryfall_id = scryfall_id
        self.api = api
        self._is_cancelled = False

    def cancel(self):
        """Cancel the image fetch operation"""
        self._is_cancelled = True

    def process(self):
        """Main processing function - runs in worker thread"""
        try:
            if self._is_cancelled:
                return

            print(f"[ImageFetch] Starting fetch for {self.scryfall_id}")

            # Multiple layers of validation
            try:
                if not self.image_uri or not self.scryfall_id:
                    self.error.emit("Missing image URI or Scryfall ID")
                    return

                if not isinstance(self.image_uri, str) or not isinstance(
                    self.scryfall_id, str
                ):
                    self.error.emit("Invalid data types for URI or ID")
                    return

                if not (
                    self.image_uri.startswith("http://")
                    or self.image_uri.startswith("https://")
                ):
                    self.error.emit(f"Invalid URI format: {self.image_uri[:50]}...")
                    return

                print(f"[ImageFetch] URI validated: {self.image_uri[:50]}...")

            except Exception as validation_error:
                print(f"[ImageFetch] Validation error: {validation_error}")
                self.error.emit(f"Validation failed: {str(validation_error)}")
                return

            # API call with maximum protection
            try:
                print(f"[ImageFetch] Calling API...")
                image_data = self.api.fetch_image(self.image_uri, self.scryfall_id)

                if self._is_cancelled:
                    return

                print(
                    f"[ImageFetch] API returned {len(image_data) if image_data else 0} bytes"
                )

            except Exception as api_error:
                print(f"[ImageFetch] API call failed: {api_error}")
                if not self._is_cancelled:
                    error_msg = str(api_error)
                    if len(error_msg) > 100:
                        error_msg = error_msg[:100] + "..."
                    self.error.emit(f"Download failed: {error_msg}")
                return

            # Data validation with protection
            try:
                if not image_data:
                    self.error.emit("No image data received")
                    return

                if not isinstance(image_data, bytes):
                    self.error.emit("Invalid image data format")
                    return

                if len(image_data) < 100:
                    self.error.emit(f"Image too small: {len(image_data)} bytes")
                    return

                print(f"[ImageFetch] Data validated: {len(image_data)} bytes")

            except Exception as data_error:
                print(f"[ImageFetch] Data validation error: {data_error}")
                self.error.emit(f"Data validation failed: {str(data_error)}")
                return

            # Final emission with protection
            try:
                if not self._is_cancelled:
                    print(f"[ImageFetch] Emitting success signal")
                    self.finished.emit(image_data, self.scryfall_id)
                else:
                    print(f"[ImageFetch] Cancelled before emission")

            except Exception as emit_error:
                print(f"[ImageFetch] Signal emission error: {emit_error}")
                # Don't emit error here - just log it

        except Exception as critical_error:
            # Last resort catch-all
            print(f"[ImageFetch] CRITICAL ERROR: {critical_error}")
            print(f"[ImageFetch] Error type: {type(critical_error)}")
            try:
                import traceback

                traceback.print_exc()
            except:
                pass

            try:
                if not self._is_cancelled:
                    self.error.emit("Critical error occurred")
            except:
                print(f"[ImageFetch] Could not emit error signal")

        finally:
            print(f"[ImageFetch] Process completed (cancelled: {self._is_cancelled})")


class BackgroundImageCacheWorker(QObject):
    """Background worker for proactively caching card images"""

    # Signals
    progress = pyqtSignal(int, int)  # current, total
    image_cached = pyqtSignal(str, str)  # scryfall_id, cache_path
    finished = pyqtSignal(int)  # total_cached
    error = pyqtSignal(str, str)  # scryfall_id, error_message

    def __init__(
        self, cards: list, api: ScryfallAPI, max_concurrent: int = 3, parent=None
    ):
        super().__init__(parent)
        self.cards = cards
        self.api = api
        self.max_concurrent = max_concurrent
        self._is_cancelled = False
        self._processed = 0
        self._successful = 0

    def cancel(self):
        """Cancel the background caching operation"""
        self._is_cancelled = True

    def process(self):
        """Main processing function - downloads images in background"""
        if self._is_cancelled:
            return

        try:
            print(
                f"[BackgroundCache] Starting cache process for {len(self.cards)} cards"
            )

            # Filter cards that have image URIs and aren't already cached
            cards_to_cache = []
            for card in self.cards:
                if self._is_cancelled:
                    return

                if not hasattr(card, "image_uri") or not card.image_uri:
                    continue

                # Check if already cached
                cache_file = Config.IMAGE_CACHE_DIR / f"{card.scryfall_id}.jpg"
                if cache_file.exists():
                    continue

                cards_to_cache.append(card)

            print(f"[BackgroundCache] {len(cards_to_cache)} images need caching")

            if not cards_to_cache:
                print(f"[BackgroundCache] All images already cached, finishing")
                # Small delay to ensure UI has processed any pending signals
                import time

                time.sleep(0.1)
                self.finished.emit(0)
                return

            total_cards = len(cards_to_cache)

            # Process cards in small batches to avoid overwhelming the API
            batch_size = min(self.max_concurrent, 5)  # Max 5 concurrent downloads

            for i in range(0, len(cards_to_cache), batch_size):
                if self._is_cancelled:
                    return

                batch = cards_to_cache[i : i + batch_size]
                print(
                    f"[BackgroundCache] Processing batch {i//batch_size + 1} ({len(batch)} cards)"
                )

                # Process each card in the batch
                for card in batch:
                    if self._is_cancelled:
                        return

                    try:
                        print(f"[BackgroundCache] Caching image for {card.name}")

                        # Add small delay to be respectful to the API
                        import time

                        time.sleep(0.1)

                        # Attempt to fetch and cache the image
                        image_data = self.api.fetch_image(
                            card.image_uri, card.scryfall_id
                        )

                        if image_data and len(image_data) > 100:
                            cache_path = str(
                                Config.IMAGE_CACHE_DIR / f"{card.scryfall_id}.jpg"
                            )
                            self.image_cached.emit(card.scryfall_id, cache_path)
                            self._successful += 1
                            print(f"[BackgroundCache] Successfully cached {card.name}")

                    except Exception as e:
                        print(f"[BackgroundCache] Failed to cache {card.name}: {e}")
                        self.error.emit(card.scryfall_id, str(e))

                    self._processed += 1

                    # Emit progress every few cards
                    if self._processed % 3 == 0 or self._processed == total_cards:
                        self.progress.emit(self._processed, total_cards)

                # Small delay between batches
                if i + batch_size < len(cards_to_cache):
                    import time

                    time.sleep(0.5)

            print(
                f"[BackgroundCache] Completed: {self._successful}/{total_cards} images cached"
            )
            self.finished.emit(self._successful)

        except Exception as e:
            print(f"[BackgroundCache] Critical error: {e}")
            import traceback

            traceback.print_exc()
            self.error.emit("SYSTEM", f"Background cache failed: {str(e)}")


class SetAnalysisWorker(QObject):
    """Worker object for set analysis operations"""

    # Signals
    progress = pyqtSignal(int, int)  # current, total
    status_update = pyqtSignal(str)  # status message
    finished = pyqtSignal(dict)  # analysis result
    error = pyqtSignal(str)  # error message

    def __init__(self, options: Dict[str, Any], api: ScryfallAPI, parent=None):
        super().__init__(parent)
        self.options = options
        self.api = api
        self._is_cancelled = False
        self.raw_cards: list[dict] = []  # Store raw card data for WUBRG analysis

    def cancel(self):
        """Cancel the analysis operation"""
        self._is_cancelled = True

    def process(self):
        """Main processing function - runs in worker thread"""
        try:
            set_codes = self.options.get(
                "set_codes", [self.options.get("set_code", "")]
            )

            # Fetch cards from all sets
            all_cards = []
            set_breakdown = {}  # Track cards per set for color coding
            total_sets = len(set_codes)

            for i, set_code in enumerate(set_codes):
                if self._is_cancelled:
                    return

                self.status_update.emit(
                    f"Fetching cards for set '{set_code.upper()}' ({i+1}/{total_sets})..."
                )

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

                # Add set information to each card for color coding
                for card in set_cards:
                    card["_source_set"] = set_code

                all_cards.extend(set_cards)
                set_breakdown[set_code] = len(set_cards)

            if self._is_cancelled:
                return

            if not all_cards:
                self.error.emit("No cards found in any of the specified sets")
                return

            # Store raw card data for WUBRG analysis
            self.raw_cards = all_cards.copy()

            self.status_update.emit(
                f"Analyzing {len(all_cards)} cards from {total_sets} set(s)..."
            )

            # Process owned cards if requested
            owned_cards = self.options.get("owned_cards", [])
            owned_by_id = {}
            if owned_cards:
                owned_by_id = {card.scryfall_id: card for card in owned_cards}

            # Filter cards if subtracting owned
            cards_to_analyze = all_cards
            if self.options.get("owned_cards") and owned_by_id:
                original_count = len(all_cards)
                cards_to_analyze = [
                    card for card in all_cards if card["id"] not in owned_by_id
                ]
                owned_count = original_count - len(cards_to_analyze)
                self.status_update.emit(
                    f"Found {owned_count} owned cards, analyzing {len(cards_to_analyze)} missing cards..."
                )

            if self._is_cancelled:
                return

            # Perform letter analysis
            letter_counts = {}
            rarity_weights = self._get_rarity_weights()

            total_cards = len(cards_to_analyze)
            for i, card_data in enumerate(cards_to_analyze):
                if self._is_cancelled:
                    return

                card_name = card_data.get("name", "")
                if not card_name:
                    continue

                first_letter = card_name[0].upper()
                rarity = card_data.get("rarity", "common")
                source_set = card_data.get("_source_set", "unknown")

                if first_letter not in letter_counts:
                    letter_counts[first_letter] = {
                        "total_raw": 0,
                        "total_weighted": 0,
                        "rarity": {"common": 0, "uncommon": 0, "rare": 0, "mythic": 0},
                        "set_breakdown": {},  # Track cards per set for color coding
                    }

                letter_counts[first_letter]["total_raw"] += 1
                letter_counts[first_letter]["total_weighted"] += rarity_weights.get(
                    rarity, 1
                )
                letter_counts[first_letter]["rarity"][rarity] = (
                    letter_counts[first_letter]["rarity"].get(rarity, 0) + 1
                )

                # Track set breakdown for color coding
                if source_set not in letter_counts[first_letter]["set_breakdown"]:
                    letter_counts[first_letter]["set_breakdown"][source_set] = 0
                letter_counts[first_letter]["set_breakdown"][source_set] += 1

                # FIXED: Less frequent progress updates to prevent signal overload
                if i % 100 == 0 or i == total_cards - 1:
                    self.progress.emit(i, total_cards)

            if self._is_cancelled:
                return

            # Apply grouping if requested
            if self.options.get("group", False):
                letter_counts = self._group_low_count_letters(letter_counts)

            # Sort results
            weighted = self.options.get("weighted", False)
            sort_key = "total_weighted" if weighted else "total_raw"
            sorted_groups = sorted(
                letter_counts.items(), key=lambda x: x[1][sort_key], reverse=True
            )

            # Prepare result
            result = {
                "set_codes": set_codes,
                "total_cards_analyzed": len(cards_to_analyze),
                "sorted_groups": sorted_groups,
                "weighted": weighted,
                "preset": self.options.get("preset", "default"),
            }

            # Add owned card info if applicable
            if owned_by_id:
                result["original_set_size"] = len(all_cards)
                result["owned_count"] = len(all_cards) - len(cards_to_analyze)
                result["missing_count"] = len(cards_to_analyze)

            self.progress.emit(total_cards, total_cards)
            self.finished.emit(result)

        except Exception as e:
            if not self._is_cancelled:
                self.error.emit(f"Analysis failed: {str(e)}")

    def _get_rarity_weights(self) -> Dict[str, float]:
        """Get rarity weights based on preset"""
        preset = self.options.get("preset", "default")

        weights = {
            "default": {"mythic": 10, "rare": 3, "uncommon": 1, "common": 0.25},
            "play_booster": {"mythic": 10, "rare": 5, "uncommon": 1, "common": 0.25},
            "dynamic": {"mythic": 8, "rare": 4, "uncommon": 1.5, "common": 0.5},
        }

        return weights.get(preset, weights["default"])

    def _group_low_count_letters(self, letter_counts: Dict) -> Dict:
        """Group letters with low counts together"""
        threshold = self.options.get("threshold", 20)

        # Separate high and low count letters
        high_count = {}
        low_count_letters = []

        for letter, data in letter_counts.items():
            if data["total_raw"] >= threshold:
                high_count[letter] = data
            else:
                low_count_letters.append((letter, data))

        # Group low count letters
        if low_count_letters:
            # Sort by letter for consistent grouping
            low_count_letters.sort(key=lambda x: x[0])

            current_group = []
            current_total = 0
            group_number = 1

            for letter, data in low_count_letters:
                current_group.append(letter)
                current_total += data["total_raw"]

                if current_total >= threshold or letter == low_count_letters[-1][0]:
                    # Create group
                    group_name = "".join(sorted(current_group))
                    if len(current_group) == 1:
                        group_key = current_group[0]
                    else:
                        # Use parentheses to indicate grouped letters
                        group_key = f"({group_name})"
                        group_number += 1

                    # Combine data
                    combined_data = {
                        "total_raw": sum(
                            letter_counts[l]["total_raw"] for l in current_group
                        ),
                        "total_weighted": sum(
                            letter_counts[l]["total_weighted"] for l in current_group
                        ),
                        "rarity": {"common": 0, "uncommon": 0, "rare": 0, "mythic": 0},
                        "set_breakdown": {},
                    }

                    for l in current_group:
                        for rarity in combined_data["rarity"]:
                            combined_data["rarity"][rarity] += letter_counts[l][
                                "rarity"
                            ].get(rarity, 0)

                        # Combine set breakdowns
                        for set_code, count in (
                            letter_counts[l].get("set_breakdown", {}).items()
                        ):
                            if set_code not in combined_data["set_breakdown"]:
                                combined_data["set_breakdown"][set_code] = 0
                            combined_data["set_breakdown"][set_code] += count

                    high_count[group_key] = combined_data

                    # Reset for next group
                    current_group = []
                    current_total = 0

        return high_count


class WorkerManager:
    """
    Centralized worker thread management to eliminate duplication of thread cleanup patterns.
    """

    def __init__(self):
        self.workers = {}

    def add_worker(self, name: str, thread: QThread, worker: QObject):
        """Add a worker thread to be managed."""
        self.workers[name] = (thread, worker)

    def remove_worker(self, name: str):
        """Remove a worker from management without cleanup."""
        if name in self.workers:
            del self.workers[name]

    def cleanup_worker(self, name: str):
        """Clean up a specific worker by name."""
        if name in self.workers:
            thread, worker = self.workers[name]
            self._cleanup_worker(thread, worker)
            del self.workers[name]

    def cleanup_all(self):
        """Clean up all managed workers."""
        for name, (thread, worker) in self.workers.items():
            self._cleanup_worker(thread, worker)
        self.workers.clear()

    def _cleanup_worker(self, thread: QThread | None, worker: QObject | None):
        """
        Safely clean up a worker thread and its associated worker object.
        """
        try:
            # Signal the worker to stop its processing loop
            if worker and hasattr(worker, "cancel"):
                worker.cancel()

            # Quit the thread's event loop
            if thread and thread.isRunning():
                thread.quit()
                # Wait for the thread to finish. If it doesn't, terminate it.
                if not thread.wait(2000):  # Wait up to 2 seconds
                    print(
                        f"Warning: Thread {thread} did not quit gracefully, terminating."
                    )
                    thread.terminate()
                    thread.wait(1000)  # Wait 1 more second for termination
        except RuntimeError:
            # This can happen if the thread or worker is already deleted
            pass
        except Exception as e:  # Catch other potential errors during cleanup
            print(f"Warning: Error during thread cleanup: {e}")

    def has_worker(self, name: str) -> bool:
        """Check if a worker with the given name exists."""
        return name in self.workers

    def get_worker(self, name: str) -> tuple[QThread | None, QObject | None]:
        """Get a worker thread and worker object by name."""
        return self.workers.get(name, (None, None))


def cleanup_worker_thread(thread: QThread | None, worker: QObject | None):
    """
    Legacy function for backward compatibility.
    Use WorkerManager for new code.
    """
    manager = WorkerManager()
    manager._cleanup_worker(thread, worker)
