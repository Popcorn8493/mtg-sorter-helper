from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

@dataclass
class Card:
    """Represents a single Magic: The Gathering card."""
    scryfall_id: str
    name: str
    set_name: str
    rarity: str
    type_line: str
    color_identity: List[str]
    edhrec_rank: Optional[int]
    image_uri: Optional[str]
    mana_cost: Optional[str]
    prices: Dict[str, Optional[str]]
    quantity: int = 1
    condition: str = "N/A"
    sorted_count: int = 0  # New: Tracks how many have been sorted

    @classmethod
    def from_scryfall_dict(cls, data: Dict[str, Any]) -> 'Card':
        """Creates a Card object from a Scryfall API dictionary."""
        image_uris = data.get('image_uris', {})
        mana_cost = data.get('mana_cost')
        if not mana_cost and 'card_faces' in data:
            mana_cost = data['card_faces'][0].get('mana_cost')

        return cls(
            scryfall_id=data.get('id', ''),
            name=data.get('name', 'N/A'),
            set_name=data.get('set_name', 'N/A'),
            rarity=data.get('rarity', 'N/A'),
            type_line=data.get('type_line', 'N/A'),
            color_identity=data.get('color_identity', []),
            edhrec_rank=data.get('edhrec_rank'),
            image_uri=image_uris.get('normal') if image_uris else None,
            mana_cost=mana_cost,
            prices=data.get('prices', {})
        )

@dataclass
class SortGroup:
    """Represents a group of cards in the sorter view."""
    group_name: str
    count: int
    cards: List[Card] = field(default_factory=list)
    is_card_leaf: bool = False
