from typing import List
from PyQt6.QtWidgets import QTreeWidgetItem
from api.mtgjson_api import MTGJsonAPI
from core.models import Card

class SorterPreview:

    def __init__(self, parent):
        self.parent = parent
        self.api: MTGJsonAPI = parent.api
        self.preview_card: Card | None = None

    def reset_preview_pane(self, *args):
        self.preview_card = None
        self.parent.card_details_label.setText('Navigate to individual cards to see details.')

    def update_card_preview(self, item: QTreeWidgetItem):
        self.reset_preview_pane()
        cards = self.parent._get_cards_from_item(item)
        if not cards:
            return
        card = cards[0] if cards else None
        if not isinstance(card, Card):
            self.preview_card = None
            return
        self.preview_card = card
        if len(cards) == 1:
            self.parent.card_details_label.setText(f"<b>{card.name}</b><br>{card.mana_cost or ''}<br>{card.type_line}<br><i>{card.set_name} ({card.rarity.upper()})</i><br><br>Total Owned: {card.quantity}<br>Sorted: {card.sorted_count}")
        else:
            self.parent.card_details_label.setText(f'<b>Group: {item.text(0)}</b><br>Contains {len(cards)} different cards<br>Total cards: {sum((c.quantity for c in cards))}<br>Showing preview of: {card.name}')
