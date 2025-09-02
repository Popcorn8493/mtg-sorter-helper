# workers/threads.py

import csv
from typing import Any, Dict

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from api.scryfall_api import MTGAPIError, ScryfallAPI
from core.models import Card


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
    """FIXED: Worker object for CSV import operations with on-demand loading"""
    
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
        """FIXED: Main processing function with on-demand loading - minimal API calls during import"""
        try:
            # Stream CSV processing to avoid loading entire file into memory
            cards = []
            total_rows = 0
            
            # Process CSV and create card objects with minimal data
            with open(self.csv_path, 'r', encoding='utf-8', newline='') as file:
                reader = csv.DictReader(file)
                
                for row_num, row in enumerate(reader):
                    if self._is_cancelled:
                        return
                    
                    # Memory safety: limit processing if file is too large
                    if row_num > 50000:  # Reasonable limit for most collections
                        self.error.emit("CSV file too large (>50,000 rows). Please split into smaller files.")
                        return
                    
                    total_rows += 1
                    
                    scryfall_id = row.get('Scryfall ID', '').strip()
                    if not scryfall_id:
                        continue
                    
                    try:
                        quantity = int(row.get('Quantity', 1))
                        if quantity <= 0:
                            continue
                    except (ValueError, TypeError):
                        quantity = 1
                    
                    # Create card object with minimal data - full data will be loaded on demand
                    card = Card(
                        scryfall_id=scryfall_id,
                        name="Loading...",  # Will be loaded when needed
                        set_name="Loading...",
                        rarity="Loading...",
                        type_line="Loading...",
                        color_identity=[],
                        edhrec_rank=None,
                        image_uri=None,
                        mana_cost=None,
                        prices={},
                        quantity=quantity,
                        condition=row.get('Condition', 'N/A'),
                        sorted_count=0
                    )
                    cards.append(card)
                    
                    # Throttled progress to prevent signal overload
                    if row_num % 100 == 0:
                        self.progress.emit(row_num, total_rows)
                    
                    # Periodic memory check during processing
                    if row_num % 1000 == 0 and not check_memory_safety("CSV Import - Processing", 800):
                        self.error.emit("Memory usage too high during import. Process aborted.")
                        return
            
            if not cards:
                self.error.emit("No valid cards found in the CSV file.")
                return
            
            # Final progress update
            self.progress.emit(total_rows, total_rows)
            
            # Return cards - they will load full data on demand when accessed
            self.finished.emit(cards)
            
        except Exception as e:
            self.error.emit(f"Unexpected error during import: {str(e)}")


class ImageFetchWorker(QObject):
	"""FIXED: Worker object for image fetching operations"""
	
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
		if self._is_cancelled:
			return
		
		try:
			image_data = self.api.fetch_image(self.image_uri, self.scryfall_id)
			
			if not self._is_cancelled:
				self.finished.emit(image_data, self.scryfall_id)
		
		except MTGAPIError as e:
			if not self._is_cancelled:
				self.error.emit(f"Failed to fetch image: {e}")
		except Exception as e:
			if not self._is_cancelled:
				self.error.emit(f"Unexpected error fetching image: {str(e)}")


class SetAnalysisWorker(QObject):
	"""FIXED: Worker object for set analysis operations"""
	
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
	
	def cancel(self):
		"""Cancel the analysis operation"""
		self._is_cancelled = True
	
	def process(self):
		"""Main processing function - runs in worker thread"""
		try:
			set_code = self.options['set_code']
			self.status_update.emit(f"Fetching cards for set '{set_code.upper()}'...")
			
			if self._is_cancelled:
				return
			
			# Fetch set data
			try:
				set_cards = self.api.fetch_set(set_code)
			except MTGAPIError as e:
				self.error.emit(str(e))
				return
			
			if self._is_cancelled:
				return
			
			if not set_cards:
				self.error.emit(f"No cards found for set '{set_code}'")
				return
			
			self.status_update.emit(f"Analyzing {len(set_cards)} cards from set '{set_code.upper()}'...")
			
			# Process owned cards if requested
			owned_cards = self.options.get('owned_cards', [])
			owned_by_id = {}
			if owned_cards:
				owned_by_id = {card.scryfall_id: card for card in owned_cards}
			
			# Filter cards if subtracting owned
			cards_to_analyze = set_cards
			if self.options.get('owned_cards') and owned_by_id:
				original_count = len(set_cards)
				cards_to_analyze = [card for card in set_cards if card['id'] not in owned_by_id]
				owned_count = original_count - len(cards_to_analyze)
				self.status_update.emit(
						f"Found {owned_count} owned cards, analyzing {len(cards_to_analyze)} missing cards...")
			
			if self._is_cancelled:
				return
			
			# Perform letter analysis
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
				
				if first_letter not in letter_counts:
					letter_counts[first_letter] = {
							'total_raw':      0,
							'total_weighted': 0,
							'rarity':         {'common': 0, 'uncommon': 0, 'rare': 0, 'mythic': 0}
					}
				
				letter_counts[first_letter]['total_raw'] += 1
				letter_counts[first_letter]['total_weighted'] += rarity_weights.get(rarity, 1)
				letter_counts[first_letter]['rarity'][rarity] = letter_counts[first_letter]['rarity'].get(rarity, 0) + 1
				
				# FIXED: Less frequent progress updates to prevent signal overload
				if i % 100 == 0 or i == total_cards - 1:
					self.progress.emit(i, total_cards)
			
			if self._is_cancelled:
				return
			
			# Apply grouping if requested
			if self.options.get('group', False):
				letter_counts = self._group_low_count_letters(letter_counts)
			
			# Sort results
			weighted = self.options.get('weighted', False)
			sort_key = 'total_weighted' if weighted else 'total_raw'
			sorted_groups = sorted(letter_counts.items(), key=lambda x: x[1][sort_key], reverse=True)
			
			# Prepare result
			result = {
					'set_code':             set_code,
					'total_cards_analyzed': len(cards_to_analyze),
					'sorted_groups':        sorted_groups,
					'weighted':             weighted,
					'preset':               self.options.get('preset', 'default')
			}
			
			# Add owned card info if applicable
			if owned_by_id:
				result['original_set_size'] = len(set_cards)
				result['owned_count'] = len(set_cards) - len(cards_to_analyze)
				result['missing_count'] = len(cards_to_analyze)
			
			self.progress.emit(total_cards, total_cards)
			self.finished.emit(result)
		
		except Exception as e:
			if not self._is_cancelled:
				self.error.emit(f"Analysis failed: {str(e)}")
	
	def _get_rarity_weights(self) -> Dict[str, float]:
		"""Get rarity weights based on preset"""
		preset = self.options.get('preset', 'default')
		
		weights = {
				'default':      {'mythic': 10, 'rare': 3, 'uncommon': 1, 'common': 0.25},
				'play_booster': {'mythic': 10, 'rare': 5, 'uncommon': 1, 'common': 0.25},
				'dynamic':      {'mythic': 8, 'rare': 4, 'uncommon': 1.5, 'common': 0.5}
		}
		
		return weights.get(preset, weights['default'])
	
	def _group_low_count_letters(self, letter_counts: Dict) -> Dict:
		"""Group letters with low counts together"""
		threshold = self.options.get('threshold', 20)
		
		# Separate high and low count letters
		high_count = {}
		low_count_letters = []
		
		for letter, data in letter_counts.items():
			if data['total_raw'] >= threshold:
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
				current_total += data['total_raw']
				
				if current_total >= threshold or letter == low_count_letters[-1][0]:
					# Create group
					group_name = ''.join(sorted(current_group))
					if len(current_group) == 1:
						group_key = current_group[0]
					else:
						group_key = f"Group {group_number} ({group_name})"
						group_number += 1
					
					# Combine data
					combined_data = {
							'total_raw':      sum(letter_counts[l]['total_raw'] for l in current_group),
							'total_weighted': sum(letter_counts[l]['total_weighted'] for l in current_group),
							'rarity':         {'common': 0, 'uncommon': 0, 'rare': 0, 'mythic': 0}
					}
					
					for l in current_group:
						for rarity in combined_data['rarity']:
							combined_data['rarity'][rarity] += letter_counts[l]['rarity'].get(rarity, 0)
					
					high_count[group_key] = combined_data
					
					# Reset for next group
					current_group = []
					current_total = 0
		
		return high_count


def cleanup_worker_thread(thread: QThread | None, worker: QObject | None):
	"""
	Safely clean up a worker thread and its associated worker object.
	"""
	try:
		# Signal the worker to stop its processing loop
		if worker and hasattr(worker, 'cancel'):
			worker.cancel()
		
		# Quit the thread's event loop
		if thread and thread.isRunning():
			thread.quit()
			# Wait for the thread to finish. If it doesn't, terminate it.
			if not thread.wait(2000):  # Wait up to 2 seconds
				print(f"Warning: Thread {thread} did not quit gracefully, terminating.")
				thread.terminate()
				thread.wait(1000)  # Wait 1 more second for termination
	except RuntimeError:
		# This can happen if the thread or worker is already deleted
		pass
	except Exception as e:  # Catch other potential errors during cleanup
		print(f"Warning: Error during thread cleanup: {e}")
