import json
import os
import pathlib
import shutil
import time
from typing import Dict, List, Any
import requests
from core.constants import Config
from core.card_validator import CardValidator
SCRYFALL_API_COLLECTION_ENDPOINT = 'https://api.scryfall.com/cards/collection'

class CacheManager:

    def __init__(self, cache_dir: pathlib.Path, max_size_mb: int):
        self.cache_dir = cache_dir
        self.max_size_bytes = max_size_mb * 1024 * 1024

    def get_cache_size(self) -> int:
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(self.cache_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
        except (OSError, IOError):
            pass
        return total

    def cleanup_old_files(self) -> int:
        current_size = self.get_cache_size()
        if current_size <= self.max_size_bytes:
            return 0
        files_with_times = []
        try:
            for dirpath, dirnames, filenames in os.walk(self.cache_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        mtime = os.path.getmtime(fp)
                        size = os.path.getsize(fp)
                        files_with_times.append((fp, mtime, size))
        except (OSError, IOError):
            return 0
        files_with_times.sort(key=lambda x: x[1])
        removed_count = 0
        target_size = self.max_size_bytes * 0.8
        for filepath, mtime, file_size in files_with_times:
            if current_size <= target_size:
                break
            try:
                os.remove(filepath)
                current_size -= file_size
                removed_count += 1
            except (OSError, IOError):
                continue
        return removed_count

class MTGAPIError(Exception):

    def __init__(self, message: str, error_type: str='unknown', details: Dict=None):
        self.error_type = error_type
        self.details = details or {}
        super().__init__(message)

class ScryfallAPI:

    def __init__(self):
        self.card_cache_manager = CacheManager(Config.CARD_CACHE_DIR, 50)
        self.image_cache_manager = CacheManager(Config.IMAGE_CACHE_DIR, Config.MAX_IMAGE_CACHE_SIZE_MB)
        self.set_cache_manager = CacheManager(Config.SET_CACHE_DIR, 100)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': f'{Config.APP_NAME}/1.0 (Educational Project)', 'Accept': 'application/json'})

    def fetch_card_by_id(self, scryfall_id: str) -> Dict[str, Any]:
        is_valid, error_message = CardValidator.validate_scryfall_id(scryfall_id)
        if not is_valid:
            raise MTGAPIError(error_message, 'validation_error', {'provided_id': scryfall_id})
        cache_file = Config.CARD_CACHE_DIR / f'{scryfall_id}.json'
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, IOError) as e:
                cache_file.unlink(missing_ok=True)
        try:
            time.sleep(0.05)
            response = self.session.get(f'{Config.SCRYFALL_API_CARD_ENDPOINT}{scryfall_id}', timeout=30)
            if response.status_code == 404:
                raise MTGAPIError(f'Card not found: {scryfall_id}', 'not_found', {'scryfall_id': scryfall_id, 'suggestion': 'Check if the Scryfall ID is correct'})
            elif response.status_code == 429:
                raise MTGAPIError('Rate limit exceeded. Please try again in a moment.', 'rate_limit', {'retry_after': response.headers.get('Retry-After', '60')})
            elif response.status_code >= 500:
                raise MTGAPIError('Scryfall server error. Please try again later.', 'server_error', {'status_code': response.status_code})
            response.raise_for_status()
            card_data = response.json()
            self.card_cache_manager.cleanup_old_files()
            try:
                cache_file.write_text(json.dumps(card_data), encoding='utf-8')
            except IOError:
                pass
            return card_data
        except requests.Timeout:
            raise MTGAPIError(f'Request timeout while fetching card {scryfall_id}', 'timeout', {'suggestion': 'Check your internet connection and try again'})
        except requests.ConnectionError:
            raise MTGAPIError('Unable to connect to Scryfall. Please check your internet connection.', 'connection_error', {'suggestion': 'Verify your internet connection and firewall settings'})
        except requests.RequestException as e:
            raise MTGAPIError(f'Network error while fetching card {scryfall_id}: {str(e)}', 'network_error', {'original_error': str(e)})

    def fetch_card_collection(self, identifiers: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        if not identifiers:
            return []
        if len(identifiers) > 10000:
            raise MTGAPIError(f'Collection too large ({len(identifiers)} cards). Please process in smaller batches (<10,000 cards).')
        all_cards_data = []
        not_found_ids = []
        chunk_size = 75
        for i in range(0, len(identifiers), chunk_size):
            chunk = identifiers[i:i + chunk_size]
            payload = {'identifiers': chunk}
            try:
                time.sleep(0.1)
                response = self.session.post(SCRYFALL_API_COLLECTION_ENDPOINT, json=payload, timeout=60)
                response.raise_for_status()
                data = response.json()
                if 'data' in data and data['data']:
                    if len(all_cards_data) + len(data['data']) > 15000:
                        raise MTGAPIError('Collection response too large, aborting to prevent memory issues.')
                    all_cards_data.extend(data['data'])
                if 'not_found' in data and data['not_found']:
                    not_found_ids.extend([item.get('id', 'Unknown') for item in data['not_found']])
            except requests.RequestException as e:
                raise MTGAPIError(f'Network error while fetching card collection: {e}', 'network_error', {'chunk_start_index': i})
        if not_found_ids:
            print(f'Warning: {len(not_found_ids)} cards were not found on Scryfall.')
        return all_cards_data

    def fetch_set(self, set_code: str) -> List[Dict[str, Any]]:
        if not set_code or not isinstance(set_code, str):
            raise MTGAPIError('Set code must be a non-empty string', 'validation_error', {'provided_code': set_code})
        set_code = set_code.lower().strip()
        cache_file = Config.SET_CACHE_DIR / f'{set_code}.json'
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, IOError):
                cache_file.unlink(missing_ok=True)
        cards = []
        url = f'{Config.SCRYFALL_API_SET_ENDPOINT}?q=set:{set_code}&unique=cards'
        page_count = 0
        max_pages = 50
        while url and page_count < max_pages:
            try:
                time.sleep(0.05)
                response = self.session.get(url, timeout=30)
                if response.status_code == 404:
                    if page_count == 0:
                        raise MTGAPIError(f"Set '{set_code}' not found", 'not_found', {'suggestion': "Check the set code spelling. Common format examples: 'mh3', 'ltr', 'dmu'"})
                    else:
                        break
                elif response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', '60'))
                    raise MTGAPIError(f'Rate limit exceeded. Please wait {retry_after} seconds and try again.', 'rate_limit', {'retry_after': retry_after})
                response.raise_for_status()
                data = response.json()
                if 'data' not in data:
                    break
                cards.extend(data['data'])
                url = data.get('next_page')
                page_count += 1
            except requests.Timeout:
                raise MTGAPIError(f"Request timeout while fetching set '{set_code}' (page {page_count + 1})", 'timeout', {'suggestion': 'The set might be very large. Try again or check your connection.'})
            except requests.ConnectionError:
                raise MTGAPIError('Unable to connect to Scryfall. Please check your internet connection.', 'connection_error')
            except requests.RequestException as e:
                raise MTGAPIError(f"Network error while fetching set '{set_code}': {str(e)}", 'network_error', {'page': page_count + 1, 'original_error': str(e)})
        if not cards:
            raise MTGAPIError(f"No cards found for set '{set_code}'", 'empty_result', {'suggestion': 'Verify the set code is correct and the set exists on Scryfall'})
        self.set_cache_manager.cleanup_old_files()
        try:
            cache_file.write_text(json.dumps(cards), encoding='utf-8')
        except IOError:
            pass
        return cards

    def fetch_image(self, image_uri: str, scryfall_id: str) -> bytes:
        print(f'[API] fetch_image called for {scryfall_id}')
        print(f'[API] Image URI: {image_uri}')
        if not image_uri or not scryfall_id:
            raise MTGAPIError('Both image URI and Scryfall ID are required', 'validation_error')
        if not (image_uri.startswith('http://') or image_uri.startswith('https://')):
            raise MTGAPIError(f'Invalid image URI format: {image_uri}', 'validation_error')
        cache_file = Config.IMAGE_CACHE_DIR / f'{scryfall_id}.jpg'
        print(f'[API] Cache file: {cache_file}')
        print(f'[API] Cache file exists: {cache_file.exists()}')
        if cache_file.exists():
            print(f'[API] Cache file size: {cache_file.stat().st_size} bytes')
        if cache_file.exists():
            try:
                print(f'[API] Loading from cache')
                cached_data = cache_file.read_bytes()
                print(f'[API] Cache hit: {len(cached_data)} bytes')
                return cached_data
            except IOError as e:
                print(f'[API] Cache read failed: {e}')
                cache_file.unlink(missing_ok=True)
        else:
            print(f'[API] Cache miss - file does not exist, downloading from web')
        try:
            removed_count = self.image_cache_manager.cleanup_old_files()
            print(f'[API] Cleaned up {removed_count} old cache files')
        except Exception as e:
            print(f'[API] Cache cleanup failed: {e}')
        try:
            print(f'[API] Making HTTP request...')
            response = self.session.get(image_uri, stream=True, timeout=30)
            print(f'[API] Response status: {response.status_code}')
            if response.status_code == 404:
                raise MTGAPIError(f'Card image not found for {scryfall_id}', 'not_found', {'image_uri': image_uri})
            response.raise_for_status()
            print(f"[API] Response headers: Content-Length={response.headers.get('content-length', 'unknown')}")
            max_size = 10 * 1024 * 1024
            image_data = b''
            total_size = 0
            for chunk in response.iter_content(chunk_size=8192):
                if total_size + len(chunk) > max_size:
                    raise MTGAPIError(f'Image too large for {scryfall_id}', 'size_limit_exceeded', {'max_size_mb': max_size // (1024 * 1024)})
                image_data += chunk
                total_size += len(chunk)
            print(f'[API] Downloaded {len(image_data)} bytes')
            if len(image_data) < 1000:
                raise MTGAPIError(f'Invalid image data received for {scryfall_id}', 'invalid_data', {'size_bytes': len(image_data)})
            if not (image_data.startswith(b'\xff\xd8\xff') or image_data.startswith(b'\x89PNG\r\n\x1a\n')):
                print(f"[API] Warning: Image data doesn't match expected format")
            try:
                print(f'[API] Saving to cache...')
                cache_file.write_bytes(image_data)
                print(f'[API] Cache saved successfully')
            except IOError as e:
                print(f'[API] Cache save failed: {e}')
            print(f'[API] fetch_image completed successfully')
            return image_data
        except requests.Timeout as e:
            print(f'[API] Timeout error: {e}')
            raise MTGAPIError(f'Timeout while downloading image for {scryfall_id}', 'timeout', {'suggestion': 'Image download taking too long. Try again or check connection.'})
        except requests.ConnectionError as e:
            print(f'[API] Connection error: {e}')
            raise MTGAPIError('Unable to connect to image server. Please check your internet connection.', 'connection_error')
        except requests.RequestException as e:
            print(f'[API] Request error: {e}')
            raise MTGAPIError(f'Failed to download image for {scryfall_id}: {str(e)}', 'network_error', {'image_uri': image_uri, 'original_error': str(e)})
        except Exception as e:
            print(f'[API] Unexpected error: {e}')
            print(f'[API] Error type: {type(e)}')
            import traceback
            traceback.print_exc()
            raise MTGAPIError(f'Unexpected error downloading image for {scryfall_id}: {str(e)}', 'unexpected_error', {'image_uri': image_uri, 'original_error': str(e)})

    def get_cache_stats(self) -> Dict[str, Any]:
        try:
            card_size = self.card_cache_manager.get_cache_size()
            image_size = self.image_cache_manager.get_cache_size()
            set_size = self.set_cache_manager.get_cache_size()
            total_size = card_size + image_size + set_size

            def format_size(size_bytes):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if size_bytes < 1024:
                        return f'{size_bytes:.1f} {unit}'
                    size_bytes /= 1024
                return f'{size_bytes:.1f} TB'
            return {'card_cache_size': format_size(card_size), 'image_cache_size': format_size(image_size), 'set_cache_size': format_size(set_size), 'total_cache_size': format_size(total_size), 'card_cache_files': len(list(Config.CARD_CACHE_DIR.glob('*.json'))), 'image_cache_files': len(list(Config.IMAGE_CACHE_DIR.glob('*.jpg'))), 'set_cache_files': len(list(Config.SET_CACHE_DIR.glob('*.json')))}
        except Exception:
            return {'card_cache_size': 'Unknown', 'image_cache_size': 'Unknown', 'set_cache_size': 'Unknown', 'total_cache_size': 'Unknown', 'card_cache_files': 0, 'image_cache_files': 0, 'set_cache_files': 0}

    def clear_cache(self, cache_type: str='all') -> bool:
        try:
            if cache_type in ('all', 'cards'):
                shutil.rmtree(Config.CARD_CACHE_DIR, ignore_errors=True)
                Config.CARD_CACHE_DIR.mkdir(exist_ok=True)
            if cache_type in ('all', 'images'):
                shutil.rmtree(Config.IMAGE_CACHE_DIR, ignore_errors=True)
                Config.IMAGE_CACHE_DIR.mkdir(exist_ok=True)
            if cache_type in ('all', 'sets'):
                shutil.rmtree(Config.SET_CACHE_DIR, ignore_errors=True)
                Config.SET_CACHE_DIR.mkdir(exist_ok=True)
            return True
        except Exception:
            return False