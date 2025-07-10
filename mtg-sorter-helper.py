import collections
import csv
import json
import pathlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, List
import matplotlib.pyplot as plt
import requests

# Configuration
SCRYFALL_ENDPOINT = "https://api.scryfall.com/cards/search"
CACHE_DIR = pathlib.Path(".scryfall_cache")
CACHE_DIR.mkdir(exist_ok=True)

# Default rarity weights, adjust as needed
DEFAULT_WEIGHTS = {"common": 10, "uncommon": 3, "rare": 1, "mythic": 0.25}

PLAY_BOOSTER_WEIGHTS = {"common": 10, "uncommon": 5, "rare": 1, "mythic": 0.25}


# Helper functions
def get_all_cards_from_set(set_code: str) -> List[dict]:
    cache_file = CACHE_DIR / f"{set_code}.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    all_cards = []
    url = f"{SCRYFALL_ENDPOINT}?q=set:{set_code}&unique=cards"
    while url:
        resp = requests.get(url)
        data = resp.json()
        all_cards.extend(data["data"])
        url = data.get("next_page")

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(all_cards, f)
    return all_cards


def parse_weights(weight_args: List[str]) -> Dict[str, float]:
    weights = {}
    for item in weight_args:
        k, v = item.split(":")
        weights[k.strip()] = float(v.strip())
    return weights


def analyze_card_name_alphabet(set_code,
                               weighted=False,
                               rarity_weights=None,
                               export_csv=None,
                               show_chart=False):
    if rarity_weights is None:
        rarity_weights = DEFAULT_WEIGHTS

    cards = get_all_cards_from_set(set_code)
    if not cards:
        print(f"No cards found for set '{set_code}'.")
        return

    letter_totals = collections.defaultdict(float if weighted else int)
    for card in cards:
        first = card["name"][0].upper()
        rarity = card.get("rarity", "common")
        weight = rarity_weights.get(rarity, 1)
        letter_totals[first] += weight if weighted else 1

    sorted_totals = sorted(letter_totals.items(),
                           key=lambda kv: kv[1],
                           reverse=True)
    print(
        f"--- {'WEIGHTED' if weighted else 'RAW'} First‑Letter Analysis for {set_code.upper()} ---"
    )
    for letter, total in sorted_totals:
        print(f"'{letter}': {total:.2f}"
              if weighted else f"'{letter}': {int(total)}")

    if export_csv:
        with open(export_csv, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Letter", "Count"])
            for letter, total in sorted_totals:
                writer.writerow([letter, total])
        print(f"Exported to {export_csv}")

    if show_chart:
        letters, counts = zip(*sorted_totals)
        plt.bar(letters, counts)
        plt.title(f"First Letter Frequency in Set '{set_code.upper()}'")
        plt.xlabel("First Letter")
        plt.ylabel("Weighted Count" if weighted else "Raw Count")
        plt.show()


# UI


def launch_ui():

    def run_analysis():
        set_code = set_entry.get().strip().lower()
        if not set_code:
            messagebox.showerror("Error", "Please enter a set code.")
            return

        weighted = weight_var.get()
        preset = preset_var.get()
        weights = DEFAULT_WEIGHTS
        if preset == "play_booster":
            weights = PLAY_BOOSTER_WEIGHTS

        export = export_var.get()
        show = chart_var.get()

        export_path = None
        if export:
            export_path = filedialog.asksaveasfilename(defaultextension=".csv",
                                                       filetypes=[("CSV Files",
                                                                   "*.csv")])

        analyze_card_name_alphabet(set_code, weighted, weights, export_path,
                                   show)

    root = tk.Tk()
    root.title("MTG Set Letter Analyzer")

    ttk.Label(root, text="Set Code:").grid(row=0, column=0, sticky="w")
    set_entry = ttk.Entry(root)
    set_entry.grid(row=0, column=1, columnspan=2, sticky="ew")

    weight_var = tk.BooleanVar()
    ttk.Checkbutton(root, text="Use Weighted Rarity",
                    variable=weight_var).grid(row=1,
                                              column=0,
                                              columnspan=3,
                                              sticky="w")

    preset_var = tk.StringVar(value="default")
    ttk.Label(root, text="Weight Preset:").grid(row=2, column=0, sticky="w")
    ttk.OptionMenu(root, preset_var, "default", "default",
                   "play_booster").grid(row=2,
                                        column=1,
                                        columnspan=2,
                                        sticky="ew")

    export_var = tk.BooleanVar()
    ttk.Checkbutton(root, text="Export to CSV",
                    variable=export_var).grid(row=3,
                                              column=0,
                                              columnspan=3,
                                              sticky="w")

    chart_var = tk.BooleanVar()
    ttk.Checkbutton(root, text="Show Chart",
                    variable=chart_var).grid(row=4,
                                             column=0,
                                             columnspan=3,
                                             sticky="w")

    ttk.Button(root, text="Run Analysis",
               command=run_analysis).grid(row=5,
                                          column=0,
                                          columnspan=3,
                                          pady=10)

    root.columnconfigure(1, weight=1)
    root.mainloop()


if __name__ == "__main__":
    launch_ui()
