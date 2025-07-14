import csv
import json
import string
import collections
from typing import Dict, List

from PyQt6.QtCore import QThread, pyqtSignal

from api.scryfall_api import ScryfallAPI, MTGAPIError
from core.models import Card


class CsvImportWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)  # New signal for status updates

    def __init__(self, filepath: str, api: ScryfallAPI):
        super().__init__()
        self.filepath = filepath
        self.api = api
        self._is_cancelled = False

    def cancel(self):
        """Allow cancellation of import process"""
        self._is_cancelled = True

    def run(self):
        try:
            self.status_update.emit("Reading CSV file...")
            cards = []

            with open(self.filepath, 'r', encoding='utf-8') as f:
                # Find header line within first 20 lines
                header = None
                original_position = f.tell()

                for line_num in range(20):
                    line = f.readline()
                    if not line:  # End of file
                        break
                    if 'Scryfall ID' in line and 'Quantity' in line:
                        header = [h.strip().strip('"') for h in line.split(',')]
                        break

                if not header:
                    self.error.emit(
                        "Could not find required columns in CSV file.\n\n"
                        "Expected columns:\n"
                        "• 'Scryfall ID' - unique identifier for each card\n"
                        "• 'Quantity' - number of copies owned\n\n"
                        "Please ensure you're using a ManaBox CSV export."
                    )
                    return

                # Find required column indices
                try:
                    scryfall_id_index = header.index('Scryfall ID')
                    quantity_index = header.index('Quantity')
                except ValueError:
                    missing_cols = []
                    if 'Scryfall ID' not in header:
                        missing_cols.append('Scryfall ID')
                    if 'Quantity' not in header:
                        missing_cols.append('Quantity')

                    self.error.emit(
                        f"Missing required columns: {', '.join(missing_cols)}\n\n"
                        f"Found columns: {', '.join(header)}\n\n"
                        "Please check your CSV file format."
                    )
                    return

                # Optional columns
                condition_index = header.index('Condition') if 'Condition' in header else None

                # Read from beginning and skip to data
                f.seek(0)
                content = f.read()
                csv_start = content.find(','.join(header))
                if csv_start == -1:
                    self.error.emit("Could not locate data section in CSV file.")
                    return

                csv_content = content[csv_start:]
                reader = csv.DictReader(csv_content.splitlines(), fieldnames=header)
                next(reader)  # Skip header row

                # Convert to list to get count
                card_list = []
                for row in reader:
                    if self._is_cancelled:
                        return

                    # Skip empty rows
                    scryfall_id = row.get('Scryfall ID', '').strip()
                    if not scryfall_id:
                        continue

                    try:
                        quantity = int(row.get('Quantity', 0))
                        if quantity <= 0:
                            continue  # Skip cards with 0 quantity
                    except ValueError:
                        continue  # Skip rows with invalid quantity

                    card_list.append(row)

                total = len(card_list)
                if total == 0:
                    self.error.emit(
                        "No valid card data found in CSV file.\n\n"
                        "Please check that:\n"
                        "• Cards have valid Scryfall IDs\n"
                        "• Quantities are greater than 0\n"
                        "• The file is properly formatted"
                    )
                    return

                self.status_update.emit(f"Processing {total} cards...")

                # Process cards and fetch data
                failed_cards = []
                for i, row in enumerate(card_list):
                    if self._is_cancelled:
                        return

                    self.progress.emit(i + 1, total)

                    scryfall_id = row.get('Scryfall ID', '').strip()

                    try:
                        card_data = self.api.fetch_card_by_id(scryfall_id)
                        card = Card.from_scryfall_dict(card_data)

                        # Set additional properties from CSV
                        card.quantity = int(row.get('Quantity', 1))
                        card.condition = row.get('Condition', 'N/A') if condition_index else 'N/A'

                        cards.append(card)

                    except MTGAPIError as e:
                        failed_cards.append({
                            'id': scryfall_id,
                            'error': str(e),
                            'type': e.error_type
                        })

                        # Continue processing other cards unless it's a critical error
                        if e.error_type in ['rate_limit', 'connection_error']:
                            # For rate limits or connection issues, fail the entire import
                            error_msg = f"Import failed due to {e.error_type}:\n\n{str(e)}"
                            if e.error_type == 'rate_limit':
                                retry_after = e.details.get('retry_after', '60')
                                error_msg += f"\n\nPlease wait {retry_after} seconds and try again."
                            self.error.emit(error_msg)
                            return
                        # For individual card errors, continue but track them
                        continue

                    except Exception as e:
                        failed_cards.append({
                            'id': scryfall_id,
                            'error': str(e),
                            'type': 'unknown'
                        })
                        continue

                # Report results
                if not cards and failed_cards:
                    # All cards failed
                    error_summary = self._create_error_summary(failed_cards)
                    self.error.emit(f"All cards failed to import:\n\n{error_summary}")
                    return
                elif failed_cards:
                    # Some cards failed - emit warning but continue
                    self.status_update.emit(f"Import completed with {len(failed_cards)} warnings")
                else:
                    self.status_update.emit("Import completed successfully!")

                self.finished.emit(cards)

        except FileNotFoundError:
            self.error.emit(
                f"File not found: {self.filepath}\n\n"
                "Please check that the file exists and try again."
            )
        except PermissionError:
            self.error.emit(
                f"Permission denied accessing: {self.filepath}\n\n"
                "Please check file permissions and ensure the file is not open in another program."
            )
        except UnicodeDecodeError:
            self.error.emit(
                "Unable to read the CSV file - invalid character encoding.\n\n"
                "Please ensure the file is saved as UTF-8 or try opening it in a text editor and re-saving."
            )
        except Exception as e:
            self.error.emit(
                f"An unexpected error occurred during import:\n\n{str(e)}\n\n"
                "Please check the file format and try again."
            )

    def _create_error_summary(self, failed_cards: List[Dict]) -> str:
        """Create a user-friendly summary of failed cards"""
        if not failed_cards:
            return ""

        # Group errors by type
        error_groups = collections.defaultdict(list)
        for card in failed_cards:
            error_groups[card['type']].append(card)

        summary_parts = []

        for error_type, cards in error_groups.items():
            count = len(cards)
            if error_type == 'not_found':
                summary_parts.append(f"• {count} card(s) not found on Scryfall (invalid IDs)")
            elif error_type == 'network_error':
                summary_parts.append(f"• {count} card(s) failed due to network issues")
            elif error_type == 'validation_error':
                summary_parts.append(f"• {count} card(s) had invalid data format")
            else:
                summary_parts.append(f"• {count} card(s) failed with unknown errors")

        summary = '\n'.join(summary_parts)

        if len(failed_cards) <= 5:
            # Show individual card details for small numbers
            summary += "\n\nFailed cards:"
            for card in failed_cards[:5]:
                summary += f"\n- {card['id']}: {card['error']}"

        return summary


class SetAnalysisWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # New progress signal
    status_update = pyqtSignal(str)  # New status signal

    def __init__(self, options: Dict, api: ScryfallAPI):
        super().__init__()
        self.options = options
        self.api = api
        self._is_cancelled = False

    def cancel(self):
        """Allow cancellation of analysis"""
        self._is_cancelled = True

    def _get_group_map(self, raw_totals):
        if not self.options['group']:
            return {letter: letter for letter in string.ascii_uppercase}

        thr = self.options['threshold']
        mapping = {}
        buf, tot = "", 0

        def flush():
            nonlocal buf, tot
            if buf:
                for ch in buf:
                    mapping[ch] = buf
                buf, tot = "", 0

        letters = string.ascii_uppercase
        for i, l in enumerate(letters):
            if raw_totals.get(l, 0) < thr:
                buf += l
                tot += raw_totals.get(l, 0)
                if tot >= thr or not (i < 25 and raw_totals.get(letters[i + 1], 0) < thr):
                    flush()
            else:
                flush()
                mapping[l] = l
        flush()
        return mapping

    def run(self):
        try:
            set_code = self.options['set_code']
            self.status_update.emit(f"Fetching set data for '{set_code.upper()}'...")

            # Fetch set data with progress tracking
            try:
                cards_data = self.api.fetch_set(set_code)
            except MTGAPIError as e:
                if e.error_type == 'not_found':
                    self.error.emit(
                        f"Set '{set_code.upper()}' not found on Scryfall.\n\n"
                        "Please check the set code and try again.\n\n"
                        "Examples of valid set codes:\n"
                        "• mh3 (Modern Horizons 3)\n"
                        "• ltr (Lord of the Rings)\n"
                        "• dmu (Dominaria United)"
                    )
                elif e.error_type == 'rate_limit':
                    retry_after = e.details.get('retry_after', '60')
                    self.error.emit(
                        f"Rate limit exceeded.\n\n"
                        f"Please wait {retry_after} seconds and try again."
                    )
                elif e.error_type == 'connection_error':
                    self.error.emit(
                        "Unable to connect to Scryfall.\n\n"
                        "Please check your internet connection and try again."
                    )
                else:
                    self.error.emit(f"Failed to fetch set data:\n\n{str(e)}")
                return

            if self._is_cancelled:
                return

            original_count = len(cards_data)
            self.status_update.emit(f"Found {original_count} cards in set")

            # Filter out owned cards if provided
            owned_cards_list = self.options.get('owned_cards')
            if owned_cards_list:
                self.status_update.emit("Filtering out owned cards...")
                owned_ids = {card.scryfall_id for card in owned_cards_list}
                cards_data = [card_dict for card_dict in cards_data if card_dict.get('id') not in owned_ids]

                filtered_count = len(cards_data)
                owned_count = original_count - filtered_count

                if not cards_data:
                    self.status_update.emit("Analysis complete - you own the entire set!")
                    self.finished.emit({
                        "sorted_groups": [],
                        "set_code": set_code,
                        "weighted": self.options['weighted'],
                        "owned_count": owned_count,
                        "total_count": original_count
                    })
                    return
                else:
                    self.status_update.emit(f"Analyzing {filtered_count} missing cards ({owned_count} owned)")

            if self._is_cancelled:
                return

            # Process cards
            self.status_update.emit("Processing card data...")
            total_cards = len(cards_data)

            cards = []
            for i, card_dict in enumerate(cards_data):
                if self._is_cancelled:
                    return

                if i % 100 == 0:  # Update progress every 100 cards
                    self.progress.emit(i, total_cards)

                try:
                    card = Card.from_scryfall_dict(card_dict)
                    cards.append(card)
                except Exception:
                    # Skip malformed cards
                    continue

            self.progress.emit(total_cards, total_cards)

            if self._is_cancelled:
                return

            # Perform analysis
            self.status_update.emit("Analyzing card distribution...")

            detailed_breakdown = collections.defaultdict(
                lambda: {
                    'total_raw': 0,
                    'total_weighted': 0,
                    'rarity': collections.defaultdict(float)
                }
            )

            # Get weights
            wts = self._get_weights(cards)

            # Calculate raw letter totals for grouping
            raw_letter_totals = collections.defaultdict(float)
            for c in cards:
                if c.name != 'N/A':
                    raw_letter_totals[c.name[0].upper()] += 1

            # Get grouping map
            group_map = self._get_group_map(raw_letter_totals)

            # Process each card
            for c in cards:
                if self._is_cancelled:
                    return

                if c.name == 'N/A':
                    continue

                group_key = group_map.get(c.name[0].upper(), c.name[0].upper())
                weight = wts.get(c.rarity, 1)
                value_to_add = weight if self.options['weighted'] else 1

                detailed_breakdown[group_key]['total_raw'] += 1
                detailed_breakdown[group_key]['total_weighted'] += value_to_add
                detailed_breakdown[group_key]['rarity'][c.rarity] += value_to_add

            # Sort results
            sort_key = 'total_weighted' if self.options['weighted'] else 'total_raw'
            sorted_groups = sorted(
                detailed_breakdown.items(),
                key=lambda item: item[1][sort_key],
                reverse=True
            )

            self.status_update.emit("Analysis complete!")

            result = {
                "sorted_groups": sorted_groups,
                "set_code": set_code,
                "weighted": self.options['weighted'],
                "total_cards_analyzed": len(cards),
                "original_set_size": original_count
            }

            if owned_cards_list:
                result["owned_count"] = original_count - len(cards_data)
                result["missing_count"] = len(cards_data)

            self.finished.emit(result)

        except Exception as e:
            self.error.emit(
                f"An unexpected error occurred during analysis:\n\n{str(e)}\n\n"
                "Please try again or check your input parameters."
            )

    def _get_weights(self, cards):
        preset = self.options['preset']

        if preset == "play_booster":
            return {"common": 10, "uncommon": 5, "rare": 1, "mythic": 0.25}

        if preset == "dynamic":
            rarities = ["common", "uncommon", "rare", "mythic"]
            rarity_counts = {r: 0 for r in rarities}
            total = sum(1 for c in cards if c.rarity in rarities)

            if total > 0:
                for c in cards:
                    if c.rarity in rarities:
                        rarity_counts[c.rarity] += 1
                return {r: (count / total) * 100 for r, count in rarity_counts.items()}

        # Default weights
        return {"common": 10, "uncommon": 3, "rare": 1, "mythic": 0.25}


class ImageFetchWorker(QThread):
    finished = pyqtSignal(bytes, str)
    error = pyqtSignal(str)

    def __init__(self, image_uri: str, scryfall_id: str, api: ScryfallAPI):
        super().__init__()
        self.image_uri = image_uri
        self.scryfall_id = scryfall_id
        self.api = api

    def run(self):
        try:
            image_data = self.api.fetch_image(self.image_uri, self.scryfall_id)
            self.finished.emit(image_data, self.scryfall_id)
        except MTGAPIError as e:
            if e.error_type == 'not_found':
                self.error.emit("Image not available")
            elif e.error_type == 'timeout':
                self.error.emit("Download timeout")
            elif e.error_type == 'connection_error':
                self.error.emit("Connection failed")
            else:
                self.error.emit(f"Download failed: {str(e)}")
        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")