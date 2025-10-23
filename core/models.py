from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

@dataclass
class Card:
    scryfall_id: str
    name: str
    set_name: str
    rarity: str
    type_line: str
    color_identity: List[str]
    edhrec_rank: Optional[int]
    mana_cost: Optional[str]
    prices: Dict[str, Optional[str]]
    quantity: int = 1
    condition: str = 'N/A'
    sorted_count: int = 0

    @classmethod
    def from_scryfall_dict(cls, data: Dict[str, Any]) -> 'Card':
        mana_cost = data.get('mana_cost')
        if not mana_cost and 'card_faces' in data:
            mana_cost = data['card_faces'][0].get('mana_cost')
        return cls(scryfall_id=data.get('id', ''), name=data.get('name', 'N/A'), set_name=data.get('set_name', 'N/A'), rarity=data.get('rarity', 'N/A'), type_line=data.get('type_line', 'N/A'), color_identity=data.get('color_identity', []), edhrec_rank=data.get('edhrec_rank'), mana_cost=mana_cost, prices=data.get('prices', {}))

    @classmethod
    def from_mtgjson_dict(cls, data: Dict[str, Any], set_name: str = None) -> 'Card':
        """
        Create a Card from MTGJSON card data.

        Args:
            data: MTGJSON card dictionary
            set_name: Optional set name (if not provided, uses setCode)

        Returns:
            Card instance
        """
        # Get Scryfall ID from identifiers
        scryfall_id = data.get('identifiers', {}).get('scryfallId', '')

        # Reconstruct type_line from MTGJSON's separate fields
        supertypes = data.get('supertypes', [])
        types = data.get('types', [])
        subtypes = data.get('subtypes', [])

        type_parts = []
        if supertypes:
            type_parts.extend(supertypes)
        if types:
            type_parts.extend(types)

        if subtypes:
            type_line = ' '.join(type_parts) + ' — ' + ' '.join(subtypes)
        else:
            type_line = ' '.join(type_parts) if type_parts else data.get('type', 'N/A')

        # Use provided set_name or fall back to setCode
        if not set_name:
            set_name = data.get('setCode', 'N/A')

        return cls(
            scryfall_id=scryfall_id,
            name=data.get('name', 'N/A'),
            set_name=set_name,
            rarity=data.get('rarity', 'N/A').lower(),  # MTGJSON uses lowercase
            type_line=type_line,
            color_identity=data.get('colorIdentity', []),
            edhrec_rank=data.get('edhrecRank'),
            mana_cost=data.get('manaCost'),
            prices={}  # MTGJSON doesn't include prices in card data
        )

    @property
    def unsorted_quantity(self) -> int:
        return max(0, self.quantity - self.sorted_count)

    @property
    def is_fully_sorted(self) -> bool:
        return self.sorted_count >= self.quantity

@dataclass
class SortGroup:
    group_name: str
    count: int
    cards: List[Card] = field(default_factory=list)
    is_card_leaf: bool = False
    total_count: int = 0
    unsorted_count: int = 0

    def __post_init__(self):
        if self.total_count == 0 and self.cards:
            self.total_count = sum((card.quantity for card in self.cards))
        if self.unsorted_count == 0 and self.cards:
            self.unsorted_count = sum((card.unsorted_quantity for card in self.cards))
        if self.count == 0:
            self.count = self.unsorted_count

    @property
    def is_fully_sorted(self) -> bool:
        return self.unsorted_count == 0

    @property
    def sorted_count(self) -> int:
        return self.total_count - self.unsorted_count

    @property
    def sorted_percentage(self) -> float:
        if self.total_count == 0:
            return 100.0
        return self.sorted_count / self.total_count * 100