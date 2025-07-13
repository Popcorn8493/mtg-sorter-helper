import csv
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QMessageBox
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

from api.scryfall_api import ScryfallAPI
from workers.threads import SetAnalysisWorker

if TYPE_CHECKING:
    from ui.sorter_tab import ManaBoxSorterTab


class SetAnalyzerTab(QWidget):
    RARITY_COLORS = {'common': '#9a9a9a', 'uncommon': '#c0c0c0', 'rare': '#d4af37', 'mythic': '#ff6600'}

    def __init__(self, api: ScryfallAPI, sorter_tab: 'ManaBoxSorterTab'):
        super().__init__()
        self.api = api
        self.sorter_tab = sorter_tab  # Keep a reference to the sorter tab
        self.worker = None
        self.last_analysis_data = None
        self.options = {}  # Initialize options attribute
        main_layout = QHBoxLayout(self)
        controls_group = QGroupBox("Analysis Options")
        controls_layout = QVBoxLayout(controls_group)
        main_layout.addWidget(controls_group, 1)
        chart_group = QGroupBox("Analysis Results")
        chart_layout = QVBoxLayout(chart_group)
        main_layout.addWidget(chart_group, 2)
        self._create_controls(controls_layout)
        self.canvas = FigureCanvas(Figure(facecolor='#2b2b2b'))
        self.ax = self.canvas.figure.subplots()
        self.ax.tick_params(colors='white')
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['top'].set_color('white')
        self.ax.spines['right'].set_color('white')
        self.ax.spines['left'].set_color('white')
        toolbar = NavigationToolbar(self.canvas, self)
        toolbar.setObjectName("qt_toolbar_navigation")
        chart_layout.addWidget(toolbar)
        chart_layout.addWidget(self.canvas)

    def _create_controls(self, layout):
        grid = QGridLayout()
        self.set_code_edit = QLineEdit()
        self.set_code_edit.setPlaceholderText("e.g., 'mh3'")
        self.subtract_owned_check = QCheckBox("Subtract Owned Cards (from Sorter)")
        self.weighted_check = QCheckBox("Weighted Analysis")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["default", "play_booster", "dynamic"])
        self.group_check = QCheckBox("Group low count letters")
        self.group_check.setChecked(True)
        self.threshold_edit = QLineEdit("20")
        self.color_by_combo = QComboBox()
        self.color_by_combo.addItems(["None", "Rarity"])
        self.export_check = QCheckBox("Export to CSV on run")

        grid.addWidget(QLabel("Set Code:"), 0, 0)
        grid.addWidget(self.set_code_edit, 0, 1)
        grid.addWidget(self.subtract_owned_check, 1, 0, 1, 2)
        grid.addWidget(self.weighted_check, 2, 0, 1, 2)
        grid.addWidget(QLabel("Weight Preset:"), 3, 0)
        grid.addWidget(self.preset_combo, 3, 1)
        grid.addWidget(self.group_check, 4, 0, 1, 2)
        grid.addWidget(QLabel("Min group total:"), 5, 0)
        grid.addWidget(self.threshold_edit, 5, 1)
        grid.addWidget(QLabel("Color Code By:"), 6, 0)
        grid.addWidget(self.color_by_combo, 6, 1)
        grid.addWidget(self.export_check, 7, 0, 1, 2)

        # Connect signals for dynamic updates
        for widget in (self.weighted_check, self.group_check, self.preset_combo, self.threshold_edit,
                       self.color_by_combo):
            if isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self.redraw_chart)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.redraw_chart)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self.redraw_chart)

        layout.addLayout(grid)
        layout.addStretch()
        self.run_button = QPushButton("Run Analysis")
        self.run_button.setObjectName("AccentButton")
        self.run_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.run_button)
        self.status_label = QLabel("Enter a set code to begin.")
        layout.addWidget(self.status_label)

    def run_analysis(self):
        set_code = self.set_code_edit.text().strip().lower()
        if not set_code: QMessageBox.warning(self, "Input Error", "Please enter a set code."); return
        try:
            threshold = float(self.threshold_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Min group total must be a number.");
            return

        owned_cards = None
        if self.subtract_owned_check.isChecked():
            if not self.sorter_tab.all_cards:
                QMessageBox.warning(self, "No Collection", "Please import a collection in the Sorter tab first.")
                return
            owned_cards = self.sorter_tab.all_cards

        self.options = {'set_code': set_code, 'weighted': self.weighted_check.isChecked(),
                        'preset': self.preset_combo.currentText(), 'group': self.group_check.isChecked(),
                        'threshold': threshold, 'owned_cards': owned_cards}

        if self.export_check.isChecked():
            filepath, _ = QFileDialog.askSaveAsFileName(self, "Save Analysis CSV", f"{set_code}_analysis.csv",
                                                        "CSV Files (*.csv)")
            if not filepath: return
            self.options['export_path'] = filepath

        self.run_button.setEnabled(False)
        self.status_label.setText(f"Running analysis for '{set_code.upper()}'...")
        self.worker = SetAnalysisWorker(self.options, self.api)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    def on_analysis_finished(self, result):
        set_code_str = f"'{result['set_code'].upper()}'"
        if self.options.get('owned_cards'):
            set_code_str += " (Missing Cards)"
        self.status_label.setText(f"Analysis for {set_code_str} complete.")
        self.run_button.setEnabled(True)
        self.last_analysis_data = result
        self.redraw_chart()
        if export_path := self.worker.options.get('export_path'):
            try:
                if not result['sorted_groups']:
                    QMessageBox.information(self, "Export Info", "No data to export.")
                    return
                flat_results = [(group, data['total_weighted' if result['weighted'] else 'total_raw']) for group, data
                                in result['sorted_groups']]
                with open(export_path, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(flat_results)
                QMessageBox.information(self, "Export Success", f"Exported analysis to {export_path}")
            except IOError as e:
                QMessageBox.critical(self, "Export Error", f"Error exporting file: {e}")

    def redraw_chart(self):
        if self.last_analysis_data is None: return
        self.ax.clear()
        data = self.last_analysis_data

        if not data['sorted_groups']:
            self.ax.text(0.5, 0.5, "No cards to display.\n(You might own the entire set!)",
                         ha='center', va='center', color='white', fontsize=12)
            self.ax.set_title(f"Card Distribution for Set: {data['set_code'].upper()}", color='white')
            self.canvas.draw()
            return

        color_mode = self.color_by_combo.currentText()
        labels = [item[0] for item in data['sorted_groups']]
        if color_mode == "None":
            self.ax.bar(labels, [item[1]['total_weighted' if data['weighted'] else 'total_raw'] for item in
                                 data['sorted_groups']], color='#007acc')
        else:
            all_rarities = sorted(list(self.RARITY_COLORS.keys()))
            bottoms = {label: 0 for label in labels}
            for rarity in all_rarities:
                values = [item[1]['rarity'].get(rarity, 0) for item in data['sorted_groups']]
                self.ax.bar(labels, values, bottom=[bottoms[l] for l in labels],
                            color=self.RARITY_COLORS.get(rarity, '#ffffff'), label=rarity)
                for i, label in enumerate(labels): bottoms[label] += values[i]
            self.ax.legend(labelcolor='white', facecolor='#3c3f41', edgecolor='#555')

        title = f"Card Distribution for Set: {data['set_code'].upper()}"
        if self.options.get('owned_cards'):
            title += " (Missing Cards)"
        self.ax.set_title(title, color='white')
        self.ax.set_ylabel("Count" if not data['weighted'] else "Weighted Score", color='white')
        self.canvas.figure.autofmt_xdate(rotation=45)
        self.canvas.figure.tight_layout()
        self.canvas.draw()

    def on_analysis_error(self, error_message):
        self.status_label.setText("Analysis failed.")
        self.run_button.setEnabled(True)
        QMessageBox.critical(self, "Analysis Error", error_message)
