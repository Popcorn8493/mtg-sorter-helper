"""
Booster probability calculator for MTGJSON booster configuration data.

This module calculates the probability of pulling each card from a booster pack
based on MTGJSON's sheet configuration and booster contents data.
"""

from typing import Dict, Any, Optional
import logging


class BoosterProbabilityCalculator:
    """
    Calculates per-card probabilities from MTGJSON booster configuration data.

    The probability calculation works as follows:
    1. For each sheet in the booster config, calculate card probability as:
       card_prob_in_sheet = card_weight / sheet_total_weight
    2. For each booster configuration, determine how many picks from each sheet
    3. Final probability = (card_prob_in_sheet) * (picks_from_that_sheet)
    4. If card appears in multiple sheets, sum probabilities

    Example:
        If a card has weight 2 in a common sheet (totalWeight=100),
        and draft boosters pick 10 cards from common sheet:
        probability = (2/100) * 10 = 0.2 cards per pack
    """

    def __init__(self, booster_data: Dict[str, Any]):
        """
        Initialize the calculator with MTGJSON booster data.

        Args:
            booster_data: Dictionary from MTGJsonAPI.fetch_booster_config()
                Expected structure:
                {
                    'booster': {
                        'default': {
                            'sheets': {
                                'common': {
                                    'cards': {uuid: weight, ...},
                                    'totalWeight': int,
                                    ...
                                },
                                ...
                            },
                            'boosters': [
                                {
                                    'contents': {sheet_name: picks, ...}
                                },
                                ...
                            ]
                        }
                    }
                }
        """
        self.booster_data = booster_data
        self.logger = logging.getLogger(__name__)

    def calculate_card_probabilities(self) -> Dict[str, float]:
        """
        Calculate the expected number of each card per booster pack.

        Returns:
            Dictionary mapping card UUID to expected count per pack.
            For example: {'card-uuid-1': 0.15, 'card-uuid-2': 2.5, ...}
            A value of 2.5 means you'd expect to see that card 2.5 times per pack.

        Raises:
            ValueError: If booster data structure is invalid
        """
        if 'booster' not in self.booster_data:
            raise ValueError('Invalid booster data: missing "booster" key')

        booster_configs = self.booster_data['booster']

        # Try to find the default/draft booster configuration
        # Priority: 'default' > 'draft' > first available
        config_name = self._select_booster_config(booster_configs)

        if not config_name:
            raise ValueError('No booster configuration found in data')

        config = booster_configs[config_name]
        self.logger.info(f'Using booster configuration: {config_name}')

        # Validate structure
        if 'sheets' not in config:
            raise ValueError(f'Booster config "{config_name}" missing "sheets" data')

        if 'boosters' not in config or not config['boosters']:
            raise ValueError(f'Booster config "{config_name}" missing "boosters" array')

        sheets = config['sheets']
        booster_contents = config['boosters'][0].get('contents', {})

        # Calculate probabilities
        card_probabilities: Dict[str, float] = {}

        for sheet_name, picks_from_sheet in booster_contents.items():
            if sheet_name not in sheets:
                self.logger.warning(
                    f'Sheet "{sheet_name}" referenced in booster contents '
                    f'but not found in sheets data'
                )
                continue

            sheet_data = sheets[sheet_name]

            # Validate sheet structure
            if 'cards' not in sheet_data:
                self.logger.warning(f'Sheet "{sheet_name}" missing "cards" data')
                continue

            if 'totalWeight' not in sheet_data:
                self.logger.warning(f'Sheet "{sheet_name}" missing "totalWeight"')
                continue

            cards_in_sheet = sheet_data['cards']
            total_weight = sheet_data['totalWeight']

            if total_weight <= 0:
                self.logger.warning(
                    f'Sheet "{sheet_name}" has invalid totalWeight: {total_weight}'
                )
                continue

            # Calculate probability for each card in this sheet
            for card_uuid, card_weight in cards_in_sheet.items():
                # Probability of pulling this card from one pick of this sheet
                prob_per_pick = card_weight / total_weight

                # Expected number of this card from all picks of this sheet
                expected_count = prob_per_pick * picks_from_sheet

                # Accumulate (in case card appears in multiple sheets)
                if card_uuid in card_probabilities:
                    card_probabilities[card_uuid] += expected_count
                else:
                    card_probabilities[card_uuid] = expected_count

        return card_probabilities

    def _select_booster_config(self, booster_configs: Dict[str, Any]) -> Optional[str]:
        """
        Select which booster configuration to use.

        Priority order: 'default' > 'draft' > first available

        Args:
            booster_configs: Dictionary of booster configurations

        Returns:
            Name of selected configuration, or None if no configs available
        """
        if 'default' in booster_configs:
            return 'default'
        elif 'draft' in booster_configs:
            return 'draft'
        elif booster_configs:
            # Return first available config
            return next(iter(booster_configs.keys()))
        return None

    def get_probability_by_name(
        self,
        card_name: str,
        card_mappings: Optional[Dict[str, str]] = None
    ) -> float:
        """
        Get the probability for a specific card by name.

        Args:
            card_name: Name of the card to look up
            card_mappings: Optional UUID->name mapping (from booster_data['card_mappings'])

        Returns:
            Expected count per pack, or 0.0 if not found
        """
        if card_mappings is None:
            card_mappings = self.booster_data.get('card_mappings', {})

        # Calculate all probabilities
        probabilities = self.calculate_card_probabilities()

        # Find UUID(s) for this card name
        total_prob = 0.0
        for uuid, name in card_mappings.items():
            if name == card_name and uuid in probabilities:
                total_prob += probabilities[uuid]

        return total_prob

    def get_summary_statistics(self) -> Dict[str, Any]:
        """
        Get summary statistics about the booster probabilities.

        Returns:
            Dictionary with statistics like:
            {
                'total_unique_cards': int,
                'avg_probability': float,
                'max_probability': float,
                'min_probability': float
            }
        """
        probabilities = self.calculate_card_probabilities()

        if not probabilities:
            return {
                'total_unique_cards': 0,
                'avg_probability': 0.0,
                'max_probability': 0.0,
                'min_probability': 0.0
            }

        prob_values = list(probabilities.values())

        return {
            'total_unique_cards': len(probabilities),
            'avg_probability': sum(prob_values) / len(prob_values),
            'max_probability': max(prob_values),
            'min_probability': min(prob_values)
        }
