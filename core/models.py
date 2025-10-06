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
    image_uri: Optional[str]
    mana_cost: Optional[str]
    prices: Dict[str, Optional[str]]
    quantity: int = 1
    condition: str = "N/A"
    sorted_count: int = 0

    @classmethod
    def from_scryfall_dict(cls, data: Dict[str, Any]) -> "Card":
        image_uris = data.get("image_uris", {})
        mana_cost = data.get("mana_cost")
        if not mana_cost and "card_faces" in data:
            mana_cost = data["card_faces"][0].get("mana_cost")

        return cls(
            scryfall_id=data.get("id", ""),
            name=data.get("name", "N/A"),
            set_name=data.get("set_name", "N/A"),
            rarity=data.get("rarity", "N/A"),
            type_line=data.get("type_line", "N/A"),
            color_identity=data.get("color_identity", []),
            edhrec_rank=data.get("edhrec_rank"),
            image_uri=image_uris.get("normal") if image_uris else None,
            mana_cost=mana_cost,
            prices=data.get("prices", {}),
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
            self.total_count = sum(card.quantity for card in self.cards)
        if self.unsorted_count == 0 and self.cards:
            self.unsorted_count = sum(card.unsorted_quantity for card in self.cards)
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
        return (self.sorted_count / self.total_count) * 100
