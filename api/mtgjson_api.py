"""
MTGJSON API integration for fetching booster configuration data and card data.

This module provides access to MTGJSON's data including:
- Card data from individual sets and AllPrintings database
- Booster configuration data with sheet/weight information
- Scryfall ID indexing for fast card lookups
"""

import json
import time
import gzip
import sqlite3
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path
import requests
from core.constants import Config
from api.scryfall_api import CacheManager, MTGAPIError


class MTGJsonAPI:
    """
    Interface to MTGJSON API for fetching booster configuration data.

    Uses a hybrid caching approach: fetches per-set booster configs on demand
    and caches them locally for offline use and performance.
    """

    def __init__(self):
        """Initialize the MTGJSON API client with caching support."""
        self.booster_cache_manager = CacheManager(
            Config.BOOSTER_CACHE_DIR,
            Config.MAX_BOOSTER_CACHE_SIZE_MB
        )
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'{Config.APP_NAME}/1.0 (Educational Project)',
            'Accept': 'application/json'
        })
        self._allprintings_data: Optional[Dict] = None
        self._scryfall_index: Optional[Dict[str, Dict]] = None

    def download_allprintings(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Download AllPrintings.json.gz from MTGJSON (~180MB compressed).

        Args:
            progress_callback: Optional function(bytes_downloaded, total_bytes)
                             called periodically during download

        Returns:
            True if successful, False otherwise

        Raises:
            MTGAPIError: If download fails
        """
        try:
            print(f'Downloading AllPrintings database from {Config.ALLPRINTINGS_URL}...')

            response = self.session.get(Config.ALLPRINTINGS_URL, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB chunks

            # Download to temporary file first
            temp_path = Config.ALLPRINTINGS_CACHE_PATH.with_suffix('.tmp.gz')

            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size:
                            progress_callback(downloaded, total_size)

            print(f'Download complete ({downloaded / (1024*1024):.1f} MB). Decompressing...')

            # Decompress the file
            with gzip.open(temp_path, 'rb') as f_in:
                with open(Config.ALLPRINTINGS_CACHE_PATH, 'wb') as f_out:
                    f_out.write(f_in.read())

            # Remove temporary compressed file
            temp_path.unlink()

            print(f'AllPrintings database saved to {Config.ALLPRINTINGS_CACHE_PATH}')
            return True

        except requests.RequestException as e:
            raise MTGAPIError(
                f'Failed to download AllPrintings database: {str(e)}',
                'download_error',
                {'url': Config.ALLPRINTINGS_URL}
            )
        except Exception as e:
            raise MTGAPIError(
                f'Error processing AllPrintings download: {str(e)}',
                'processing_error',
                {}
            )

    def build_scryfall_index(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> int:
        """
        Build Scryfall ID → Card data index from AllPrintings.json.
        Stores index in SQLite database for fast lookups.

        Args:
            progress_callback: Optional function(cards_processed, total_cards)

        Returns:
            Number of cards indexed

        Raises:
            MTGAPIError: If AllPrintings not found or indexing fails
        """
        if not Config.ALLPRINTINGS_CACHE_PATH.exists():
            raise MTGAPIError(
                'AllPrintings database not found. Download it first.',
                'not_found',
                {}
            )

        try:
            print('Building Scryfall ID index from AllPrintings...')

            # Load AllPrintings JSON
            with open(Config.ALLPRINTINGS_CACHE_PATH, 'r', encoding='utf-8') as f:
                allprintings = json.load(f)

            # Create SQLite index
            conn = sqlite3.connect(str(Config.SCRYFALL_INDEX_PATH))
            cursor = conn.cursor()

            # Create table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cards (
                    scryfall_id TEXT PRIMARY KEY,
                    set_code TEXT,
                    card_data TEXT
                )
            ''')

            # Create index on scryfall_id for fast lookups
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_scryfall_id ON cards(scryfall_id)
            ''')

            cards_indexed = 0
            total_sets = len(allprintings.get('data', {}))
            processed_sets = 0

            # Index all cards
            for set_code, set_data in allprintings.get('data', {}).items():
                cards = set_data.get('cards', [])

                for card in cards:
                    scryfall_id = card.get('identifiers', {}).get('scryfallId')

                    if scryfall_id:
                        # Store card data as JSON
                        # Include set name for convenience
                        card['_set_name'] = set_data.get('name', set_code)

                        cursor.execute('''
                            INSERT OR REPLACE INTO cards (scryfall_id, set_code, card_data)
                            VALUES (?, ?, ?)
                        ''', (scryfall_id, set_code, json.dumps(card)))

                        cards_indexed += 1

                processed_sets += 1
                if progress_callback:
                    progress_callback(processed_sets, total_sets)

            conn.commit()
            conn.close()

            print(f'Index built: {cards_indexed} cards indexed from {total_sets} sets')
            return cards_indexed

        except json.JSONDecodeError as e:
            raise MTGAPIError(
                f'Failed to parse AllPrintings JSON: {str(e)}',
                'parse_error',
                {}
            )
        except Exception as e:
            raise MTGAPIError(
                f'Error building Scryfall index: {str(e)}',
                'indexing_error',
                {}
            )

    def ensure_allprintings_loaded(self) -> bool:
        """
        Ensure AllPrintings database is downloaded and indexed.

        Returns:
            True if loaded/downloaded successfully, False otherwise
        """
        # Check if index exists
        if not Config.SCRYFALL_INDEX_PATH.exists():
            # Check if AllPrintings file exists
            if not Config.ALLPRINTINGS_CACHE_PATH.exists():
                return False  # Needs first-run download

            # AllPrintings exists but not indexed
            try:
                self.build_scryfall_index()
                return True
            except MTGAPIError:
                return False

        return True

    def fetch_set_cards_from_allprintings(self, set_code: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch cards from a set using the local AllPrintings.json file.

        Args:
            set_code: Magic set code (e.g., 'MH3', 'VOW')

        Returns:
            List of card dictionaries, or None if set not found or AllPrintings not available

        Raises:
            MTGAPIError: If AllPrintings file cannot be read
        """
        if not Config.ALLPRINTINGS_CACHE_PATH.exists():
            return None

        try:
            # Load AllPrintings JSON
            with open(Config.ALLPRINTINGS_CACHE_PATH, 'r', encoding='utf-8') as f:
                allprintings = json.load(f)

            # Get set data
            set_code_upper = set_code.upper().strip()
            sets_data = allprintings.get('data', {})

            # Try exact match first
            if set_code_upper in sets_data:
                set_data = sets_data[set_code_upper]
                cards = set_data.get('cards', [])

                # Add set name to each card for consistency
                set_name = set_data.get('name', set_code_upper)
                for card in cards:
                    card['_set_name'] = set_name

                return cards

            # If exact match not found, return None (will fall back to network)
            return None

        except json.JSONDecodeError as e:
            raise MTGAPIError(
                f'Failed to parse AllPrintings JSON: {str(e)}',
                'parse_error',
                {}
            )
        except Exception as e:
            raise MTGAPIError(
                f'Error reading AllPrintings from disk: {str(e)}',
                'read_error',
                {}
            )

    def fetch_card_by_scryfall_id(self, scryfall_id: str) -> Dict[str, Any]:
        """
        Fetch a card by its Scryfall ID from the local index.

        Args:
            scryfall_id: The Scryfall ID to look up

        Returns:
            Card data dictionary from MTGJSON

        Raises:
            MTGAPIError: If card not found or index not available
        """
        if not Config.SCRYFALL_INDEX_PATH.exists():
            raise MTGAPIError(
                'Scryfall index not available. Run first-time setup.',
                'index_not_found',
                {}
            )

        try:
            conn = sqlite3.connect(str(Config.SCRYFALL_INDEX_PATH))
            cursor = conn.cursor()

            cursor.execute(
                'SELECT card_data FROM cards WHERE scryfall_id = ?',
                (scryfall_id,)
            )

            result = cursor.fetchone()
            conn.close()

            if not result:
                raise MTGAPIError(
                    f'Card not found for Scryfall ID: {scryfall_id}',
                    'not_found',
                    {'scryfall_id': scryfall_id}
                )

            return json.loads(result[0])

        except sqlite3.Error as e:
            raise MTGAPIError(
                f'Database error looking up card: {str(e)}',
                'database_error',
                {}
            )

    def fetch_set_cards(self, set_code: str) -> List[Dict[str, Any]]:
        """
        Fetch all cards from a specific set using MTGJSON.

        First attempts to read from local AllPrintings.json if available,
        then falls back to network request.

        Args:
            set_code: Magic set code (e.g., 'MH3', 'VOW')

        Returns:
            List of card dictionaries from MTGJSON

        Raises:
            MTGAPIError: If set not found or network error
        """
        set_code = set_code.upper().strip()

        # Try reading from local AllPrintings first
        try:
            cards = self.fetch_set_cards_from_allprintings(set_code)
            if cards is not None:
                print(f'Fetching set \'{set_code}\' from local AllPrintings database')
                return cards
        except MTGAPIError as e:
            # Log but don't fail - will try network
            print(f'Warning: Failed to read from AllPrintings: {str(e)}. Falling back to network.')

        # Fall back to network request
        url = f'{Config.MTGJSON_API_BASE}{set_code}.json'

        try:
            print(f'Fetching set \'{set_code}\' from MTGJSON API')
            time.sleep(0.05)  # Be respectful to MTGJSON

            response = self.session.get(url, timeout=30)

            if response.status_code == 404:
                raise MTGAPIError(
                    f"Set '{set_code}' not found in MTGJSON",
                    'not_found',
                    {'set_code': set_code}
                )

            response.raise_for_status()
            data = response.json()

            if 'data' not in data:
                raise MTGAPIError(
                    f"Invalid response structure from MTGJSON for set '{set_code}'",
                    'invalid_data',
                    {}
                )

            set_data = data['data']

            if 'cards' not in set_data:
                raise MTGAPIError(
                    f"No cards found in set '{set_code}'",
                    'no_cards',
                    {}
                )

            # Add set name to each card for convenience
            set_name = set_data.get('name', set_code)
            cards = set_data['cards']

            for card in cards:
                card['_set_name'] = set_name

            return cards

        except requests.RequestException as e:
            raise MTGAPIError(
                f"Network error while fetching set '{set_code}': {str(e)}",
                'network_error',
                {'original_error': str(e)}
            )

    def fetch_set_metadata(self, set_code: str) -> Dict[str, Any]:
        """
        Fetch full set metadata from MTGJSON.

        Args:
            set_code: Magic set code

        Returns:
            Dictionary containing full set data including name, type, parentCode, etc.

        Raises:
            MTGAPIError: If set not found or network error
        """
        set_code = set_code.upper().strip()
        url = f'{Config.MTGJSON_API_BASE}{set_code}.json'

        try:
            time.sleep(0.05)
            response = self.session.get(url, timeout=30)

            if response.status_code == 404:
                raise MTGAPIError(
                    f"Set '{set_code}' not found in MTGJSON",
                    'not_found',
                    {'set_code': set_code}
                )

            response.raise_for_status()
            data = response.json()

            if 'data' not in data:
                raise MTGAPIError(
                    f"Invalid response structure from MTGJSON for set '{set_code}'",
                    'invalid_data',
                    {}
                )

            return data['data']

        except requests.RequestException as e:
            raise MTGAPIError(
                f"Network error while fetching set metadata for '{set_code}': {str(e)}",
                'network_error',
                {'original_error': str(e)}
            )

    def fetch_booster_config(self, set_code: str) -> Dict[str, Any]:
        """
        Fetch booster configuration for a specific set from MTGJSON.
        Automatically checks parent sets if the child set has no booster data.

        Args:
            set_code: Magic set code (e.g., 'MH3', 'BLB', 'LTR')

        Returns:
            Dictionary containing booster configuration data with structure:
            {
                'booster': {
                    'default': {  # or 'draft', 'play', etc.
                        'sheets': {...},
                        'boosters': [...]
                    }
                },
                'set_code': str,
                'source_set': str (if using parent's booster data)
            }

        Raises:
            MTGAPIError: If set not found, network error, or data unavailable
        """
        if not set_code or not isinstance(set_code, str):
            raise MTGAPIError(
                'Set code must be a non-empty string',
                'validation_error',
                {'provided_code': set_code}
            )

        set_code = set_code.upper().strip()
        cache_file = Config.BOOSTER_CACHE_DIR / f'{set_code}_booster.json'

        # Try cache first
        if cache_file.exists():
            try:
                cached_data = json.loads(cache_file.read_text(encoding='utf-8'))
                return cached_data
            except (json.JSONDecodeError, IOError):
                # Cache corrupted, remove and re-fetch
                cache_file.unlink(missing_ok=True)

        # Fetch from MTGJSON API
        # MTGJSON v5 structure: /api/v5/{SET_CODE}.json contains full set data
        url = f'{Config.MTGJSON_API_BASE}{set_code}.json'

        try:
            # MTGJSON doesn't have rate limits like Scryfall, but be respectful
            time.sleep(0.05)

            response = self.session.get(url, timeout=30)

            if response.status_code == 404:
                raise MTGAPIError(
                    f"Booster data not found for set '{set_code}'",
                    'not_found',
                    {
                        'set_code': set_code,
                        'suggestion': 'This set may not have booster configuration data available. Try using rarity-based weights instead.'
                    }
                )
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', '60'))
                raise MTGAPIError(
                    f'Rate limit exceeded. Please wait {retry_after} seconds.',
                    'rate_limit',
                    {'retry_after': retry_after}
                )
            elif response.status_code >= 500:
                raise MTGAPIError(
                    'MTGJSON server error. Please try again later.',
                    'server_error',
                    {'status_code': response.status_code}
                )

            response.raise_for_status()
            data = response.json()

            # MTGJSON v5 structure: data.data contains the actual set data
            if 'data' not in data:
                raise MTGAPIError(
                    f"Invalid response structure from MTGJSON for set '{set_code}'",
                    'invalid_data',
                    {'suggestion': 'MTGJSON API format may have changed'}
                )

            set_data = data['data']

            # Check if booster data exists
            if 'booster' not in set_data or not set_data['booster']:
                # Check for parent set
                parent_code = set_data.get('parentCode')

                if parent_code:
                    # This is a child/supplemental set - try parent's booster data
                    try:
                        parent_booster = self.fetch_booster_config(parent_code)
                        # Mark that we're using parent's data
                        parent_booster['source_set'] = parent_code
                        parent_booster['child_set'] = set_code
                        parent_booster['set_name'] = set_data.get('name', set_code)

                        # Cache this relationship for future use
                        try:
                            cache_file.write_text(
                                json.dumps(parent_booster, indent=2),
                                encoding='utf-8'
                            )
                        except IOError:
                            pass

                        return parent_booster
                    except MTGAPIError:
                        # Parent also doesn't have booster data, fall through to error
                        pass

                raise MTGAPIError(
                    f"Set '{set_code}' does not have booster configuration data",
                    'no_booster_data',
                    {
                        'set_code': set_code,
                        'parent_code': parent_code if parent_code else None,
                        'suggestion': 'This set was not sold in booster packs or data is unavailable. Use rarity-based weight presets instead.'
                    }
                )

            # Extract just the booster data we need
            booster_data = {
                'booster': set_data['booster'],
                'set_code': set_code
            }

            # Build UUID-to-Scryfall ID mapping
            # This is CRITICAL for matching booster probabilities to Scryfall cards
            if 'cards' in set_data:
                booster_data['uuid_to_scryfall'] = {}
                booster_data['card_mappings'] = {}

                for card in set_data['cards']:
                    mtgjson_uuid = card.get('uuid')
                    card_name = card.get('name')
                    scryfall_id = card.get('identifiers', {}).get('scryfallId')

                    if mtgjson_uuid and scryfall_id:
                        # Map MTGJSON UUID to Scryfall ID
                        booster_data['uuid_to_scryfall'][mtgjson_uuid] = scryfall_id

                    if mtgjson_uuid and card_name:
                        # Keep name mapping for debugging
                        booster_data['card_mappings'][mtgjson_uuid] = card_name

            # Cache the booster data
            self.booster_cache_manager.cleanup_old_files()
            try:
                cache_file.write_text(
                    json.dumps(booster_data, indent=2),
                    encoding='utf-8'
                )
            except IOError:
                # Cache write failure is not critical
                pass

            return booster_data

        except requests.Timeout:
            raise MTGAPIError(
                f"Request timeout while fetching booster data for '{set_code}'",
                'timeout',
                {'suggestion': 'Check your internet connection and try again'}
            )
        except requests.ConnectionError:
            raise MTGAPIError(
                'Unable to connect to MTGJSON. Please check your internet connection.',
                'connection_error',
                {
                    'suggestion': 'Verify your internet connection. If cache exists, it will be used automatically.'
                }
            )
        except requests.RequestException as e:
            raise MTGAPIError(
                f"Network error while fetching booster data for '{set_code}': {str(e)}",
                'network_error',
                {'original_error': str(e)}
            )

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the booster data cache.

        Returns:
            Dictionary with cache size and file count information
        """
        try:
            cache_size = self.booster_cache_manager.get_cache_size()

            def format_size(size_bytes):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if size_bytes < 1024:
                        return f'{size_bytes:.1f} {unit}'
                    size_bytes /= 1024
                return f'{size_bytes:.1f} TB'

            return {
                'booster_cache_size': format_size(cache_size),
                'booster_cache_files': len(list(Config.BOOSTER_CACHE_DIR.glob('*.json')))
            }
        except Exception:
            return {
                'booster_cache_size': 'Unknown',
                'booster_cache_files': 0
            }

    def clear_cache(self) -> bool:
        """
        Clear the booster data cache.

        Returns:
            True if successful, False otherwise
        """
        import shutil
        try:
            shutil.rmtree(Config.BOOSTER_CACHE_DIR, ignore_errors=True)
            Config.BOOSTER_CACHE_DIR.mkdir(exist_ok=True)
            return True
        except Exception:
            return False
