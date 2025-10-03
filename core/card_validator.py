"""
Centralized card data validation utilities.

This module provides a unified approach to validating card data from the Scryfall API,
eliminating code duplication across different workers and components.
"""

from typing import Dict, Any, Optional, Tuple


class CardValidator:
    """Centralized card data validation utilities."""
    
    @staticmethod
    def validate_card_data(card_data: Any, scryfall_id: str) -> Tuple[bool, Optional[str]]:
        """
        Centralized card data validation.
        
        Args:
            card_data: The card data to validate (usually from Scryfall API)
            scryfall_id: The Scryfall ID for error reporting
            
        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if card data is valid, False otherwise
            - error_message: None if valid, error description if invalid
        """
        # Check if card_data is a dictionary
        if not isinstance(card_data, dict):
            return False, f"Invalid card data type for {scryfall_id}: {type(card_data)}"
        
        # Check if card has required ID field
        if not card_data.get('id'):
            return False, f"Card data missing ID for {scryfall_id}"
        
        # Check if the ID matches the expected scryfall_id
        if card_data.get('id') != scryfall_id:
            return False, f"Card ID mismatch: expected {scryfall_id}, got {card_data.get('id')}"
        
        # Check for required fields that Card.from_scryfall_dict expects
        required_fields = ['name', 'set_name', 'rarity', 'type_line']
        missing_fields = [field for field in required_fields if not card_data.get(field)]
        
        if missing_fields:
            return False, f"Card data missing required fields for {scryfall_id}: {missing_fields}"
        
        return True, None
    
    @staticmethod
    def validate_scryfall_id(scryfall_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate Scryfall ID format.
        
        Args:
            scryfall_id: The Scryfall ID to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not scryfall_id or not isinstance(scryfall_id, str):
            return False, "Scryfall ID must be a non-empty string"
        
        # Check if ID looks like a valid UUID (32 hex characters with dashes)
        clean_id = scryfall_id.replace('-', '')
        if len(clean_id) != 32:
            return False, f"Invalid Scryfall ID format: {scryfall_id} (expected UUID format)"
        
        # Check if it contains only hex characters
        try:
            int(clean_id, 16)
        except ValueError:
            return False, f"Invalid Scryfall ID format: {scryfall_id} (not hexadecimal)"
        
        return True, None
    
    @staticmethod
    def validate_card_creation_data(card_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate card data specifically for Card object creation.
        
        This performs additional validation beyond basic structure checks,
        focusing on data that the Card.from_scryfall_dict method needs.
        
        Args:
            card_data: The card data dictionary to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # First do basic validation
        is_valid, error = CardValidator.validate_card_data(card_data, card_data.get('id', ''))
        if not is_valid:
            return is_valid, error
        
        # Check for valid color_identity (should be a list)
        color_identity = card_data.get('color_identity', [])
        if not isinstance(color_identity, list):
            return False, f"Invalid color_identity type: {type(color_identity)}"
        
        # Check for valid prices (should be a dict)
        prices = card_data.get('prices', {})
        if not isinstance(prices, dict):
            return False, f"Invalid prices type: {type(prices)}"
        
        # Check for valid image_uris if present (should be a dict)
        image_uris = card_data.get('image_uris')
        if image_uris is not None and not isinstance(image_uris, dict):
            return False, f"Invalid image_uris type: {type(image_uris)}"
        
        return True, None
    
    @staticmethod
    def get_validation_summary(card_data: Any, scryfall_id: str) -> Dict[str, Any]:
        """
        Get a comprehensive validation summary for debugging purposes.
        
        Args:
            card_data: The card data to analyze
            scryfall_id: The Scryfall ID for context
            
        Returns:
            Dictionary with validation results and metadata
        """
        is_valid, error = CardValidator.validate_card_data(card_data, scryfall_id)
        
        summary = {
            'is_valid': is_valid,
            'error': error,
            'scryfall_id': scryfall_id,
            'data_type': type(card_data).__name__,
            'is_dict': isinstance(card_data, dict)
        }
        
        if isinstance(card_data, dict):
            summary.update({
                'has_id': 'id' in card_data,
                'has_name': 'name' in card_data,
                'has_set_name': 'set_name' in card_data,
                'has_rarity': 'rarity' in card_data,
                'has_type_line': 'type_line' in card_data,
                'keys': list(card_data.keys()) if card_data else [],
                'id_value': card_data.get('id'),
                'name_value': card_data.get('name')
            })
        
        return summary
