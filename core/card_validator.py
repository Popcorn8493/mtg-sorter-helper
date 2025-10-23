from typing import Dict, Any, Optional, Tuple

class CardValidator:

    @staticmethod
    def validate_card_data(card_data: Any, scryfall_id: str) -> Tuple[bool, Optional[str]]:
        if not isinstance(card_data, dict):
            return (False, f'Invalid card data type for {scryfall_id}: {type(card_data)}')
        if not card_data.get('id'):
            return (False, f'Card data missing ID for {scryfall_id}')
        if card_data.get('id') != scryfall_id:
            return (False, f"Card ID mismatch: expected {scryfall_id}, got {card_data.get('id')}")
        required_fields = ['name', 'set_name', 'rarity', 'type_line']
        missing_fields = [field for field in required_fields if not card_data.get(field)]
        if missing_fields:
            return (False, f'Card data missing required fields for {scryfall_id}: {missing_fields}')
        return (True, None)

    @staticmethod
    def validate_scryfall_id(scryfall_id: str) -> Tuple[bool, Optional[str]]:
        if not scryfall_id or not isinstance(scryfall_id, str):
            return (False, 'Scryfall ID must be a non-empty string')
        clean_id = scryfall_id.replace('-', '')
        if len(clean_id) != 32:
            return (False, f'Invalid Scryfall ID format: {scryfall_id} (expected UUID format)')
        try:
            int(clean_id, 16)
        except ValueError:
            return (False, f'Invalid Scryfall ID format: {scryfall_id} (not hexadecimal)')
        return (True, None)

    @staticmethod
    def validate_card_creation_data(card_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        is_valid, error = CardValidator.validate_card_data(card_data, card_data.get('id', ''))
        if not is_valid:
            return (is_valid, error)
        color_identity = card_data.get('color_identity', [])
        if not isinstance(color_identity, list):
            return (False, f'Invalid color_identity type: {type(color_identity)}')
        prices = card_data.get('prices', {})
        if not isinstance(prices, dict):
            return (False, f'Invalid prices type: {type(prices)}')
        image_uris = card_data.get('image_uris')
        if image_uris is not None and (not isinstance(image_uris, dict)):
            return (False, f'Invalid image_uris type: {type(image_uris)}')
        return (True, None)

    @staticmethod
    def get_validation_summary(card_data: Any, scryfall_id: str) -> Dict[str, Any]:
        is_valid, error = CardValidator.validate_card_data(card_data, scryfall_id)
        summary = {'is_valid': is_valid, 'error': error, 'scryfall_id': scryfall_id, 'data_type': type(card_data).__name__, 'is_dict': isinstance(card_data, dict)}
        if isinstance(card_data, dict):
            summary.update({'has_id': 'id' in card_data, 'has_name': 'name' in card_data, 'has_set_name': 'set_name' in card_data, 'has_rarity': 'rarity' in card_data, 'has_type_line': 'type_line' in card_data, 'keys': list(card_data.keys()) if card_data else [], 'id_value': card_data.get('id'), 'name_value': card_data.get('name')})
        return summary