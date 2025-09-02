# core/lazy_loader.py

import asyncio
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import threading
from queue import Queue, Empty
import time

from core.models import Card
from api.scryfall_api import ScryfallAPI, MTGAPIError


@dataclass
class LazyCard:
    """A lightweight card representation that loads full data on demand"""
    scryfall_id: str
    name: str = "Loading..."
    set_name: str = "Loading..."
    rarity: str = "Loading..."
    type_line: str = "Loading..."
    color_identity: List[str] = None
    edhrec_rank: Optional[int] = None
    image_uri: Optional[str] = None
    mana_cost: Optional[str] = None
    prices: Dict[str, Optional[str]] = None
    quantity: int = 1
    condition: str = "N/A"
    sorted_count: int = 0
    
    # Lazy loading state
    _is_loaded: bool = False
    _is_loading: bool = False
    _load_error: Optional[str] = None
    _image_loaded: bool = False
    _image_loading: bool = False
    _image_error: Optional[str] = None
    
    def __post_init__(self):
        if self.color_identity is None:
            self.color_identity = []
        if self.prices is None:
            self.prices = {}
    
    @property
    def unsorted_quantity(self) -> int:
        return max(0, self.quantity - self.sorted_count)
    
    @property
    def is_fully_sorted(self) -> bool:
        return self.sorted_count >= self.quantity
    
    @property
    def is_fully_loaded(self) -> bool:
        return self._is_loaded and not self._load_error
    
    @property
    def has_image_loaded(self) -> bool:
        return self._image_loaded and not self._image_error


class LazyCardLoader:
    """Manages on-demand loading of card data and images"""
    
    def __init__(self, api: ScryfallAPI, max_concurrent_loads: int = 5):
        self.api = api
        self.max_concurrent_loads = max_concurrent_loads
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent_loads)
        self.load_queue = Queue()
        self.image_queue = Queue()
        self.loaded_cards: Dict[str, Card] = {}
        self.loaded_images: Dict[str, bytes] = {}
        self.load_callbacks: Dict[str, List[Callable]] = {}
        self.image_callbacks: Dict[str, List[Callable]] = {}
        
        # Start background workers
        self._start_workers()
    
    def _start_workers(self):
        """Start background worker threads"""
        self._card_worker_thread = threading.Thread(target=self._card_worker, daemon=True)
        self._image_worker_thread = threading.Thread(target=self._image_worker, daemon=True)
        self._card_worker_thread.start()
        self._image_worker_thread.start()
    
    def _card_worker(self):
        """Background worker for loading card data"""
        while True:
            try:
                scryfall_id = self.load_queue.get(timeout=1)
                if scryfall_id is None:  # Shutdown signal
                    break
                
                self._load_card_data(scryfall_id)
                self.load_queue.task_done()
                
            except Empty:
                continue
            except Exception as e:
                print(f"Card worker error: {e}")
    
    def _image_worker(self):
        """Background worker for loading images"""
        while True:
            try:
                item = self.image_queue.get(timeout=1)
                if item is None:  # Shutdown signal
                    break
                
                scryfall_id, image_uri = item
                self._load_card_image(scryfall_id, image_uri)
                self.image_queue.task_done()
                
            except Empty:
                continue
            except Exception as e:
                print(f"Image worker error: {e}")
    
    def _load_card_data(self, scryfall_id: str):
        """Load full card data from API"""
        try:
            card_data = self.api.fetch_card_by_id(scryfall_id)
            card = Card.from_scryfall_dict(card_data)
            self.loaded_cards[scryfall_id] = card
            
            # Notify callbacks
            if scryfall_id in self.load_callbacks:
                for callback in self.load_callbacks[scryfall_id]:
                    try:
                        callback(card, None)
                    except Exception as e:
                        print(f"Callback error: {e}")
                del self.load_callbacks[scryfall_id]
                
        except Exception as e:
            error_msg = str(e)
            # Notify callbacks of error
            if scryfall_id in self.load_callbacks:
                for callback in self.load_callbacks[scryfall_id]:
                    try:
                        callback(None, error_msg)
                    except Exception as callback_error:
                        print(f"Callback error: {callback_error}")
                del self.load_callbacks[scryfall_id]
    
    def _load_card_image(self, scryfall_id: str, image_uri: str):
        """Load card image from API"""
        try:
            image_data = self.api.fetch_image(image_uri, scryfall_id)
            self.loaded_images[scryfall_id] = image_data
            
            # Notify callbacks
            if scryfall_id in self.image_callbacks:
                for callback in self.image_callbacks[scryfall_id]:
                    try:
                        callback(image_data, None)
                    except Exception as e:
                        print(f"Image callback error: {e}")
                del self.image_callbacks[scryfall_id]
                
        except Exception as e:
            error_msg = str(e)
            # Notify callbacks of error
            if scryfall_id in self.image_callbacks:
                for callback in self.image_callbacks[scryfall_id]:
                    try:
                        callback(None, error_msg)
                    except Exception as callback_error:
                        print(f"Image callback error: {callback_error}")
                del self.image_callbacks[scryfall_id]
    
    def request_card_data(self, scryfall_id: str, callback: Callable[[Card, Optional[str]], None]):
        """Request card data to be loaded. Returns immediately if already loaded."""
        if scryfall_id in self.loaded_cards:
            # Already loaded, call callback immediately
            callback(self.loaded_cards[scryfall_id], None)
            return
        
        # Add callback to list
        if scryfall_id not in self.load_callbacks:
            self.load_callbacks[scryfall_id] = []
        self.load_callbacks[scryfall_id].append(callback)
        
        # Queue for loading if not already loading
        if scryfall_id not in [item for item in list(self.load_queue.queue)]:
            self.load_queue.put(scryfall_id)
    
    def request_card_image(self, scryfall_id: str, image_uri: str, 
                          callback: Callable[[bytes, Optional[str]], None]):
        """Request card image to be loaded. Returns immediately if already loaded."""
        if scryfall_id in self.loaded_images:
            # Already loaded, call callback immediately
            callback(self.loaded_images[scryfall_id], None)
            return
        
        # Add callback to list
        if scryfall_id not in self.image_callbacks:
            self.image_callbacks[scryfall_id] = []
        self.image_callbacks[scryfall_id].append(callback)
        
        # Queue for loading if not already loading
        if (scryfall_id, image_uri) not in [item for item in list(self.image_queue.queue)]:
            self.image_queue.put((scryfall_id, image_uri))
    
    def get_card_data(self, scryfall_id: str) -> Optional[Card]:
        """Get card data if already loaded, otherwise None"""
        return self.loaded_cards.get(scryfall_id)
    
    def get_card_image(self, scryfall_id: str) -> Optional[bytes]:
        """Get card image if already loaded, otherwise None"""
        return self.loaded_images.get(scryfall_id)
    
    def preload_cards(self, scryfall_ids: List[str], callback: Callable[[], None] = None):
        """Preload a batch of cards in the background"""
        for scryfall_id in scryfall_ids:
            if scryfall_id not in self.loaded_cards:
                self.load_queue.put(scryfall_id)
        
        if callback:
            # Wait for all cards to be processed
            def check_completion():
                while not self.load_queue.empty():
                    time.sleep(0.1)
                callback()
            
            threading.Thread(target=check_completion, daemon=True).start()
    
    def preload_images(self, card_data: List[tuple], callback: Callable[[], None] = None):
        """Preload images for a batch of cards in the background"""
        for scryfall_id, image_uri in card_data:
            if scryfall_id not in self.loaded_images:
                self.image_queue.put((scryfall_id, image_uri))
        
        if callback:
            # Wait for all images to be processed
            def check_completion():
                while not self.image_queue.empty():
                    time.sleep(0.1)
                callback()
            
            threading.Thread(target=check_completion, daemon=True).start()
    
    def clear_cache(self):
        """Clear all loaded data and images"""
        self.loaded_cards.clear()
        self.loaded_images.clear()
        self.load_callbacks.clear()
        self.image_callbacks.clear()
    
    def shutdown(self):
        """Shutdown the loader and stop workers"""
        self.load_queue.put(None)
        self.image_queue.put(None)
        self.executor.shutdown(wait=True)
        if self._card_worker_thread.is_alive():
            self._card_worker_thread.join(timeout=5)
        if self._image_worker_thread.is_alive():
            self._image_worker_thread.join(timeout=5)


class LazyCardFactory:
    """Factory for creating lazy card objects from CSV data"""
    
    @staticmethod
    def create_lazy_cards_from_csv(csv_data: List[Dict[str, Any]]) -> List[LazyCard]:
        """Create lazy card objects from CSV data without fetching from API"""
        lazy_cards = []
        
        for row in csv_data:
            scryfall_id = row.get('Scryfall ID', '').strip()
            if not scryfall_id:
                continue
            
            try:
                quantity = int(row.get('Quantity', 1))
                if quantity <= 0:
                    continue
            except (ValueError, TypeError):
                quantity = 1
            
            # Create lazy card with minimal data
            lazy_card = LazyCard(
                scryfall_id=scryfall_id,
                quantity=quantity,
                condition=row.get('Condition', 'N/A')
            )
            lazy_cards.append(lazy_card)
        
        return lazy_cards
