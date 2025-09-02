# MTG Set Letter Analyzer

Python tool for analyzing the frequency of starting letters in card names from a Magic: The Gathering set, with optional rarity-based weighting. This helps optimize how to sort large piles of cards by starting with the letters that occur most frequently.

## Features

- Pulls card data directly from the Scryfall API
- Automatically caches data to avoid repeated downloads
- Weights card counts by rarity (commons, uncommons, rares, mythics)
- Supports “Play Booster” rarity distributions
- Interactive GUI
- Optional CSV export and visual bar chart display

## Example

> _![img.png](img.png)_


### Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/popcorn8493/mtg-sorter-helper.git
    cd mtg-sorter-helper
    ```

2.  **Install the dependencies:**
    The required Python packages are listed in `requirements.txt`. Install them using pip:

    ```bash
    pip install -r requirements.txt
    ```


3.  **Run the application:**

    ```bash
    python main.py
    ```

## Usage

### Sorting Your Collection

1.  Navigate to the **Collection Sorter** tab.
2.  Click the **Import ManaBox CSV** button and select your exported collection file.
3.  Wait for the application to fetch all the necessary card data. Progress will be shown in the progress bar.
4.  In the **Sorting Options** section, define the order you want to sort your cards in by adding criteria from the "Available" list to the "Selected" list.
5.  Click the **Generate Sorting Plan** button.
6.  The **Sorting Plan** section will populate with a navigable tree. Double-click on any group to drill down further into your collection.
7.  Select a group and click **Mark Group as Sorted** to update your progress.

### Analyzing a Set

1.  Navigate to the **Set Analyzer** tab.
2.  Enter the three-letter set code of the set you wish to analyze (e.g., 'MKM' for Murders at Karlov Manor).
3.  Select your desired analysis options (e.g., "Weighted Analysis", "Subtract Owned Cards").
4.  Click the **Run Analysis** button.
5.  The results will be displayed as a bar chart. You can use the toolbar to zoom, pan, and save the chart.

