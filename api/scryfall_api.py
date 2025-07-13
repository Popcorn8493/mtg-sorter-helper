import json
import pathlib
import time
import requests
from typing import Dict, List, Any

from core.constants import Config

class ScryfallAPI:
    """Handles all requests and caching for the Scryfall API."""
    def fetch_card_by_id(self, scryfall_id: str) -> Dict[str, Any]:
        if not scryfall_id: raise ValueError("Scryfall ID cannot be empty.")
        cache_file = Config.CARD_CACHE_DIR / f"{scryfall_id}.json"
        if cache_file.exists(): return json.loads(cache_file.read_text())
        try:
            time.sleep(0.05)
            response = requests.get(f"{Config.SCRYFALL_API_CARD_ENDPOINT}{scryfall_id}")
            response.raise_for_status()
            card_data = response.json()
            cache_file.write_text(json.dumps(card_data))
            return card_data
        except requests.RequestException as e:
            raise ConnectionError(f"Could not fetch card {scryfall_id}: {e}") from e

    def fetch_set(self, set_code: str) -> List[Dict[str, Any]]:
        cache_file = Config.SET_CACHE_DIR / f"{set_code}.json"
        if cache_file.exists(): return json.loads(cache_file.read_text())
        cards, url = [], f"{Config.SCRYFALL_API_SET_ENDPOINT}?q=set:{set_code}&unique=cards"
        while url:
            try:
                resp = requests.get(url, timeout=30); resp.raise_for_status(); j = resp.json()
                cards.extend(j["data"]); url = j.get("next_page"); time.sleep(0.05)
            except requests.RequestException as e:
                raise ConnectionError(f"Failed to fetch set data for {set_code}: {e}") from e
        cache_file.write_text(json.dumps(cards)); return cards

    def fetch_image(self, image_uri: str, scryfall_id: str) -> bytes:
        cache_file = Config.IMAGE_CACHE_DIR / f"{scryfall_id}.jpg"
        if cache_file.exists(): return cache_file.read_bytes()
        try:
            response = requests.get(image_uri, stream=True); response.raise_for_status()
            image_data = response.content
            cache_file.write_bytes(image_data)
            return image_data
        except requests.RequestException as e:
            raise ConnectionError(f"Failed to fetch image for {scryfall_id}: {e}") from e
