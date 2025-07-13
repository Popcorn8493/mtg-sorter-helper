import csv
import json
import string
import collections
from typing import Dict, List

from PyQt6.QtCore import QThread, pyqtSignal

from api.scryfall_api import ScryfallAPI
from core.models import Card

class CsvImportWorker(QThread):
    progress = pyqtSignal(int, int); finished = pyqtSignal(list); error = pyqtSignal(str)
    def __init__(self, filepath: str, api: ScryfallAPI):
        super().__init__(); self.filepath = filepath; self.api = api
    def run(self):
        try:
            cards = []
            with open(self.filepath, 'r', encoding='utf-8') as f:
                header = None
                for _ in range(20):
                    if 'Scryfall ID' in (line := f.readline()) and 'Quantity' in line: header = [h.strip() for h in line.split(',')]; break
                if not header: self.error.emit("Could not find header. Ensure 'Scryfall ID' and 'Quantity' are columns."); return
                f.seek(0); content = f.read(); csv_content = content[content.find(','.join(header)):]
                reader = csv.DictReader(csv_content.splitlines(), fieldnames=header); next(reader)
                card_list = list(reader); total = len(card_list)
                for i, row in enumerate(card_list):
                    self.progress.emit(i + 1, total)
                    card_data = self.api.fetch_card_by_id(row.get('Scryfall ID'))
                    card = Card.from_scryfall_dict(card_data)
                    card.quantity = int(row.get('Quantity', 1)); card.condition = row.get('Condition', 'N/A')
                    cards.append(card)
            self.finished.emit(cards)
        except (ValueError, ConnectionError, KeyError) as e: self.error.emit(f"An error occurred during import: {e}")
        except Exception as e: self.error.emit(f"An unexpected error occurred: {e}")

class SetAnalysisWorker(QThread):
    finished = pyqtSignal(dict); error = pyqtSignal(str)
    def __init__(self, options: Dict, api: ScryfallAPI):
        super().__init__(); self.options = options; self.api = api
    def run(self):
        try:
            set_code = self.options['set_code']
            cards_data = self.api.fetch_set(set_code)

            # New: Filter out owned cards if provided
            owned_cards_list = self.options.get('owned_cards')
            if owned_cards_list:
                owned_ids = {card.scryfall_id for card in owned_cards_list}
                cards_data = [card_dict for card_dict in cards_data if card_dict.get('id') not in owned_ids]
                if not cards_data:
                    self.finished.emit({"sorted_groups": [], "set_code": set_code, "weighted": self.options['weighted']})
                    return

            cards = [Card.from_scryfall_dict(c) for c in cards_data]
            detailed_breakdown = collections.defaultdict(lambda: {'total_raw': 0, 'total_weighted': 0, 'rarity': collections.defaultdict(float)})
            wts = self._get_weights(cards); raw_letter_totals = collections.defaultdict(float)
            for c in cards:
                if c.name != 'N/A': raw_letter_totals[c.name[0].upper()] += 1
            group_map = self._get_group_map(raw_letter_totals)
            for c in cards:
                if c.name == 'N/A': continue
                group_key = group_map.get(c.name[0].upper(), c.name[0].upper())
                weight = wts.get(c.rarity, 1)
                value_to_add = weight if self.options['weighted'] else 1
                detailed_breakdown[group_key]['total_raw'] += 1; detailed_breakdown[group_key]['total_weighted'] += value_to_add
                detailed_breakdown[group_key]['rarity'][c.rarity] += value_to_add
            sort_key = 'total_weighted' if self.options['weighted'] else 'total_raw'
            sorted_groups = sorted(detailed_breakdown.items(), key=lambda item: item[1][sort_key], reverse=True)
            self.finished.emit({"sorted_groups": sorted_groups, "set_code": set_code, "weighted": self.options['weighted']})
        except (ConnectionError, KeyError) as e: self.error.emit(f"An error occurred during analysis: {e}")
        except Exception as e: self.error.emit(f"An unexpected error occurred: {e}")

    def _get_group_map(self, raw_totals):
        if not self.options['group']: return {letter: letter for letter in string.ascii_uppercase}
        thr = self.options['threshold']; mapping = {}; buf, tot = "", 0
        def flush():
            nonlocal buf, tot
            if buf:
                for ch in buf: mapping[ch] = buf
                buf, tot = "", 0
        letters = string.ascii_uppercase
        for i, l in enumerate(letters):
            if raw_totals.get(l, 0) < thr:
                buf += l; tot += raw_totals.get(l, 0)
                if tot >= thr or not (i < 25 and raw_totals.get(letters[i + 1], 0) < thr): flush()
            else: flush(); mapping[l] = l
        flush(); return mapping

    def _get_weights(self, cards):
        preset = self.options['preset']
        if preset == "play_booster": return {"common": 10, "uncommon": 5, "rare": 1, "mythic": 0.25}
        if preset == "dynamic":
            rarities = ["common", "uncommon", "rare", "mythic"]; rarity_counts = {r: 0 for r in rarities}
            total = sum(1 for c in cards if c.rarity in rarities)
            if total > 0:
                for c in cards:
                    if c.rarity in rarities: rarity_counts[c.rarity] += 1
                return {r: (count / total) * 100 for r, count in rarity_counts.items()}
        return {"common": 10, "uncommon": 3, "rare": 1, "mythic": 0.25}

class ImageFetchWorker(QThread):
    finished = pyqtSignal(bytes, str); error = pyqtSignal(str)
    def __init__(self, image_uri: str, scryfall_id: str, api: ScryfallAPI):
        super().__init__(); self.image_uri = image_uri; self.scryfall_id = scryfall_id; self.api = api
    def run(self):
        try:
            image_data = self.api.fetch_image(self.image_uri, self.scryfall_id)
            self.finished.emit(image_data, self.scryfall_id)
        except ConnectionError as e: self.error.emit(str(e))
