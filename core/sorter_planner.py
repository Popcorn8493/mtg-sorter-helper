import collections
import string
from typing import Dict, List, Tuple, Optional
from core.models import Card, SortGroup

class SorterPlanner:

    def __init__(self):
        self.sort_criteria = {'Set': self._sort_by_set, 'Color Identity': self._sort_by_color_identity, 'Rarity': self._sort_by_rarity, 'Type Line': self._sort_by_type_line, 'First Letter': self._sort_by_first_letter, 'Name': self._sort_by_name, 'Condition': self._sort_by_condition, 'Commander Staple': self._sort_by_commander_staple}

    def create_sorting_plan(self, cards: List[Card], sort_order: List[str]) -> List[SortGroup]:
        if not cards or not sort_order:
            return []
        first_criterion = sort_order[0]
        grouped_cards = self._group_cards_by_criterion(cards, first_criterion)
        sort_groups = []
        for group_name, group_cards in grouped_cards.items():
            total_count = sum((card.quantity for card in group_cards))
            unsorted_count = sum((card.quantity - card.sorted_count for card in group_cards))
            sort_group = SortGroup(group_name=group_name, count=unsorted_count, cards=group_cards)
            sort_group.total_count = total_count
            sort_group.unsorted_count = unsorted_count
            if len(sort_order) > 1:
                sort_group.sub_groups = self.create_sorting_plan(group_cards, sort_order[1:])
            sort_groups.append(sort_group)
        sort_groups.sort(key=lambda g: g.unsorted_count, reverse=True)
        return sort_groups

    def create_set_letter_plan(self, cards: List[Card], set_name: str, group_low_count: bool=True, optimal_grouping: bool=False, threshold: int=20) -> Tuple[List[SortGroup], Dict[str, str]]:
        if optimal_grouping:
            return self._create_optimal_letter_plan(cards, threshold)
        elif group_low_count:
            return self._create_grouped_letter_plan(cards, threshold)
        else:
            return self._create_simple_letter_plan(cards)

    def _create_grouped_letter_plan(self, cards: List[Card], threshold: int) -> Tuple[List[SortGroup], Dict[str, str]]:
        letter_counts = collections.defaultdict(int)
        for card in cards:
            name = getattr(card, 'name', '')
            if name and name != 'N/A':
                letter_counts[name[0].upper()] += card.quantity
        mapping = {}
        buffer = ''
        buffer_total = 0

        def flush_buffer():
            nonlocal buffer, buffer_total
            if buffer:
                for ch in buffer:
                    mapping[ch] = buffer
                buffer = ''
                buffer_total = 0
        letters = string.ascii_uppercase
        for i, letter in enumerate(letters):
            count = letter_counts.get(letter, 0)
            if 0 < count < threshold:
                buffer += letter
                buffer_total += count
                next_letter_small = i < 25 and 0 < letter_counts.get(letters[i + 1], 0) < threshold
                if buffer_total >= threshold or not next_letter_small:
                    flush_buffer()
            else:
                flush_buffer()
                if count > 0:
                    mapping[letter] = letter
        flush_buffer()
        piles = collections.defaultdict(lambda: {'cards': [], 'total': 0, 'unsorted': 0})
        for card in cards:
            name = getattr(card, 'name', '')
            if name and name != 'N/A':
                first_letter = name[0].upper()
                pile_key = mapping.get(first_letter, first_letter)
                piles[pile_key]['cards'].append(card)
                piles[pile_key]['total'] += card.quantity
                piles[pile_key]['unsorted'] += card.quantity - card.sorted_count
        groups = []
        for pile_name, pile_data in piles.items():
            group = SortGroup(group_name=pile_name, count=pile_data['unsorted'], cards=pile_data['cards'])
            group.total_count = pile_data['total']
            group.unsorted_count = pile_data['unsorted']
            groups.append(group)
        return (groups, mapping)

    def _create_optimal_letter_plan(self, cards: List[Card], threshold: int) -> Tuple[List[SortGroup], Dict[str, str]]:
        import string
        raw_letter_totals = collections.defaultdict(int)
        for card in cards:
            name = getattr(card, 'name', '')
            if name and name != 'N/A':
                raw_letter_totals[name[0].upper()] += card.quantity
        letter_counts = [(letter, raw_letter_totals.get(letter, 0)) for letter in string.ascii_uppercase]
        letter_counts.sort(key=lambda x: x[1], reverse=True)
        high_letters = [(l, c) for l, c in letter_counts if c >= threshold]
        low_letters = [(l, c) for l, c in letter_counts if 0 < c < threshold]
        mapping = {}
        for letter, count in high_letters:
            mapping[letter] = letter
        if low_letters:
            groups = self._optimal_bin_packing(low_letters, threshold)
            for group in groups:
                group_name = ''.join(sorted([letter for letter, _ in group]))
                for letter, _ in group:
                    mapping[letter] = group_name
        for letter in string.ascii_uppercase:
            if letter not in mapping:
                mapping[letter] = letter
        piles = collections.defaultdict(lambda: {'cards': [], 'total': 0, 'unsorted': 0})
        for card in cards:
            name = getattr(card, 'name', '')
            if name and name != 'N/A':
                first_letter = name[0].upper()
                pile_key = mapping.get(first_letter, first_letter)
                piles[pile_key]['cards'].append(card)
                piles[pile_key]['total'] += card.quantity
                piles[pile_key]['unsorted'] += card.quantity - card.sorted_count
        groups = []
        for pile_name, pile_data in piles.items():
            group = SortGroup(group_name=pile_name, count=pile_data['unsorted'], cards=pile_data['cards'])
            group.total_count = pile_data['total']
            group.unsorted_count = pile_data['unsorted']
            groups.append(group)
        return (groups, mapping)

    def _optimal_bin_packing(self, items, capacity):
        if not items:
            return []
        items = sorted(items, key=lambda x: x[1], reverse=True)
        bins = []
        for item in items:
            letter, count = item
            best_bin = None
            best_remaining_space = float('inf')
            for bin_items in bins:
                if len(bin_items) >= 3:
                    continue
                current_sum = sum((c for _, c in bin_items))
                if current_sum + count <= capacity:
                    remaining_space = capacity - (current_sum + count)
                    if remaining_space < best_remaining_space:
                        best_remaining_space = remaining_space
                        best_bin = bin_items
            if best_bin is not None:
                best_bin.append(item)
            else:
                bins.append([item])
        return bins

    def _create_simple_letter_plan(self, cards: List[Card]) -> Tuple[List[SortGroup], Dict[str, str]]:
        piles = collections.defaultdict(lambda: {'cards': [], 'total': 0, 'unsorted': 0})
        for card in cards:
            name = getattr(card, 'name', '')
            if name and name != 'N/A':
                pile_key = name[0].upper()
                piles[pile_key]['cards'].append(card)
                piles[pile_key]['total'] += card.quantity
                piles[pile_key]['unsorted'] += card.quantity - card.sorted_count
        groups = []
        for pile_name, pile_data in piles.items():
            group = SortGroup(group_name=pile_name, count=pile_data['unsorted'], cards=pile_data['cards'])
            group.total_count = pile_data['total']
            group.unsorted_count = pile_data['unsorted']
            groups.append(group)
        mapping = {letter: letter for letter in string.ascii_uppercase}
        return (groups, mapping)

    def _group_cards_by_criterion(self, cards: List[Card], criterion: str) -> Dict[str, List[Card]]:
        if criterion not in self.sort_criteria:
            raise ValueError(f'Unknown sort criterion: {criterion}')
        sort_func = self.sort_criteria[criterion]
        grouped = collections.defaultdict(list)
        for card in cards:
            group_key = sort_func(card)
            grouped[group_key].append(card)
        return dict(grouped)

    def _sort_by_set(self, card: Card) -> str:
        return getattr(card, 'set_name', 'Unknown Set')

    def _sort_by_color_identity(self, card: Card) -> str:
        colors = getattr(card, 'color_identity', [])
        if not colors:
            return 'Colorless'
        elif len(colors) == 1:
            color_names = {'W': 'White', 'U': 'Blue', 'B': 'Black', 'R': 'Red', 'G': 'Green'}
            return color_names.get(colors[0], 'Unknown')
        else:
            return f"Multicolor ({''.join(sorted(colors))})"

    def _sort_by_rarity(self, card: Card) -> str:
        rarity = getattr(card, 'rarity', 'common')
        rarity_order = {'mythic': 'A-Mythic', 'rare': 'B-Rare', 'uncommon': 'C-Uncommon', 'common': 'D-Common'}
        return rarity_order.get(rarity.lower(), 'E-Other')

    def _sort_by_type_line(self, card: Card) -> str:
        type_line = getattr(card, 'type_line', '')
        if not type_line:
            return 'Unknown Type'
        primary_type = type_line.split(' \x14 ')[0].strip()
        if ' ' in primary_type:
            types = primary_type.split()
            supertypes = {'Legendary', 'Basic', 'Snow', 'World', 'Ongoing'}
            main_type = next((t for t in types if t not in supertypes), types[-1])
            return main_type
        return primary_type

    def _sort_by_first_letter(self, card: Card) -> str:
        name = getattr(card, 'name', '')
        if not name or name == 'N/A':
            return 'Unknown'
        return name[0].upper()

    def _sort_by_name(self, card: Card) -> str:
        return getattr(card, 'name', 'Unknown')

    def _sort_by_condition(self, card: Card) -> str:
        condition = getattr(card, 'condition', 'Near Mint')
        condition_order = {'mint': 'A-Mint', 'near mint': 'B-Near Mint', 'lightly played': 'C-Lightly Played', 'moderately played': 'D-Moderately Played', 'heavily played': 'E-Heavily Played', 'damaged': 'F-Damaged'}
        return condition_order.get(condition.lower(), 'B-Near Mint')

    def _sort_by_commander_staple(self, card: Card) -> str:
        return 'Non-Staple'

    def get_available_criteria(self) -> List[str]:
        return list(self.sort_criteria.keys())

    def validate_sort_order(self, sort_order: List[str]) -> Tuple[bool, Optional[str]]:
        if not sort_order:
            return (False, 'Sort order cannot be empty')
        available_criteria = self.get_available_criteria()
        for criterion in sort_order:
            if criterion not in available_criteria:
                return (False, f'Unknown criterion: {criterion}')
        if len(sort_order) != len(set(sort_order)):
            return (False, 'Sort order contains duplicate criteria')
        return (True, None)

    def get_cards_at_path(self, sort_groups: List[SortGroup], path: List[str]) -> List[Card]:
        if not path:
            all_cards = []
            for group in sort_groups:
                all_cards.extend(group.cards)
            return all_cards
        current_groups = sort_groups
        for path_element in path:
            found_group = None
            for group in current_groups:
                if group.group_name == path_element:
                    found_group = group
                    break
            if not found_group:
                return []
            if path_element == path[-1]:
                return found_group.cards
            current_groups = found_group.sub_groups if found_group.sub_groups else []
        return []