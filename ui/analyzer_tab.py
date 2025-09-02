# ui/analyzer_tab.py

import csv

from PyQt6.QtCore import pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QGroupBox, QFileDialog, QMessageBox, QProgressBar, QTextEdit
)

from api.scryfall_api import ScryfallAPI
from workers.threads import SetAnalysisWorker, cleanup_worker_thread
from ui.sorter_tab import ManaBoxSorterTab


class SetAnalyzerTab(QWidget):
    RARITY_COLORS = {
        'common': '#9a9a9a',
        'uncommon': '#c0c0c0',
        'rare': '#d4af37',
        'mythic': '#ff6600'
    }

    # Signals for main window communication
    operation_started = pyqtSignal(str, int)  # message, max_value
    operation_finished = pyqtSignal()
    progress_updated = pyqtSignal(int)

    def __init__(self, api: ScryfallAPI, sorter_tab: "ManaBoxSorterTab"):
        super().__init__()
        self.api = api
        self.sorter_tab = sorter_tab  # Keep a reference to the sorter tab
        self.analysis_thread = None
        self.analysis_worker = None
        self.last_analysis_data = None
        self.options = {}  # Initialize options attribute

        # Defer chart creation to avoid startup conflicts
        self.canvas = None
        self.ax = None

        main_layout = QHBoxLayout(self)

        # Left panel - controls
        controls_group = QGroupBox("Analysis Options")
        controls_layout = QVBoxLayout(controls_group)
        main_layout.addWidget(controls_group, 1)

        # Right panel - results
        chart_group = QGroupBox("Analysis Results")
        self.chart_layout = QVBoxLayout(chart_group)
        main_layout.addWidget(chart_group, 2)

        self._create_controls(controls_layout)

    def _create_controls(self, layout):
        """Create the control panel with improved tooltips and validation"""
        grid = QGridLayout()

        # Set code input
        self.set_code_edit = QLineEdit()
        self.set_code_edit.setPlaceholderText("e.g., 'mh3', 'ltr', 'dmu'")
        self.set_code_edit.setToolTip(
            "Enter a Magic set code to analyze.\n\n"
            "Examples:\n"
            "• mh3 - Modern Horizons 3\n"
            "• ltr - Lord of the Rings\n"
            "• dmu - Dominaria United\n"
            "• neo - Kamigawa Neon Dynasty"
        )

        # Subtract owned cards option
        self.subtract_owned_check = QCheckBox("Subtract Owned Cards (from Collection)")
        self.subtract_owned_check.setToolTip(
            "When enabled, cards you already own (from the Collection Sorter) "
            "will be excluded from the analysis.\n\n"
            "This shows you which cards you're still missing from the set."
        )

        # Weighted analysis option
        self.weighted_check = QCheckBox("Weighted Analysis")
        self.weighted_check.setToolTip(
            "Weight cards by rarity to show which letters will have "
            "the most valuable/important cards.\n\n"
            "Useful for prioritizing which packs to open or cards to acquire."
        )

        # Weight preset selection
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["default", "play_booster", "dynamic"])
        self.preset_combo.setToolTip(
            "Choose weighting strategy:\n\n"
            "• Default: Balanced weights (10/3/1/0.25)\n"
            "• Play Booster: Modern pack ratios (10/5/1/0.25)\n"
            "• Dynamic: Weights based on actual set composition"
        )

        # Grouping options
        self.group_check = QCheckBox("Group low count letters")
        self.group_check.setChecked(True)
        self.group_check.setToolTip(
            "Combine letters with few cards into larger groups.\n\n"
            "This reduces the number of small piles when sorting, "
            "making organization more efficient."
        )

        self.threshold_edit = QLineEdit("20")
        self.threshold_edit.setToolTip(
            "Minimum number of cards needed before letters are grouped together.\n\n"
            "Lower values = more individual letters\n"
            "Higher values = more combined groups"
        )

        # Color coding option
        self.color_by_combo = QComboBox()
        self.color_by_combo.addItems(["None", "Rarity"])
        self.color_by_combo.setToolTip(
            "Choose how to color the chart bars:\n\n"
            "• None: Single color for all bars\n"
            "• Rarity: Stack bars by card rarity (common/uncommon/rare/mythic)"
        )

        # Export option
        self.export_check = QCheckBox("Export to CSV on run")
        self.export_check.setToolTip(
            "Automatically save analysis results to a CSV file when analysis completes.\n\n"
            "The file will contain letter groups and their card counts."
        )

        # Layout controls
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
        for widget in (self.weighted_check, self.group_check, self.preset_combo,
                       self.threshold_edit, self.color_by_combo):
            if isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self.redraw_chart)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.redraw_chart)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self.redraw_chart)

        layout.addLayout(grid)
        layout.addStretch()

        # Run button
        self.run_button = QPushButton("Run Analysis")
        self.run_button.setObjectName("AccentButton")
        self.run_button.setToolTip("Start the set analysis with current settings (Shortcut: Ctrl+R)")
        self.run_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.run_button)

        # Status and progress
        self.status_label = QLabel("Enter a set code to begin analysis.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Cancel button (hidden by default)
        self.cancel_button = QPushButton("Cancel Analysis")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        layout.addWidget(self.cancel_button)

        # Results summary (initially hidden)
        self.results_summary = QTextEdit()
        self.results_summary.setMaximumHeight(100)
        self.results_summary.setVisible(False)
        self.results_summary.setReadOnly(True)
        layout.addWidget(self.results_summary)

    def _create_chart_area(self, layout):
        """Create the chart display area"""
        # If already created, do nothing.
        if self.canvas:
            return
        # Import matplotlib components just-in-time to avoid startup conflicts
        import matplotlib
        matplotlib.use('QtAgg')  # Explicitly use modern backend for PyQt6
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
        from matplotlib.figure import Figure

        # Create matplotlib figure with dark theme
        self.canvas = FigureCanvas(Figure(facecolor='#2b2b2b'))
        self.ax = self.canvas.figure.subplots()

        # Style the plot for dark theme
        self.ax.tick_params(colors='white')
        for spine in self.ax.spines.values():
            spine.set_color('white')

        # Add navigation toolbar
        toolbar = NavigationToolbar(self.canvas, self)
        toolbar.setObjectName("qt_toolbar_navigation")

        layout.addWidget(toolbar)
        layout.addWidget(self.canvas)

    def run_analysis(self):
        """Start the analysis with improved validation and error handling"""
        # Lazily create the chart widgets right before the first analysis
        self._create_chart_area(self.chart_layout)

        # Validate inputs
        set_code = self.set_code_edit.text().strip().lower()
        if not set_code:
            QMessageBox.information(
                self,
                "Missing Set Code",
                "Please enter a set code to analyze.\n\n"
                "Examples: mh3, ltr, dmu, neo"
            )
            self.set_code_edit.setFocus()
            return

        # Validate set code format (basic check)
        if len(set_code) < 2 or len(set_code) > 6:
            reply = QMessageBox.question(
                self,
                "Unusual Set Code",
                f"'{set_code}' doesn't look like a typical set code.\n\n"
                "Most set codes are 3-4 characters (e.g., 'mh3', 'ltr').\n\n"
                "Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Validate threshold
        try:
            threshold = float(self.threshold_edit.text())
            if threshold < 1:
                QMessageBox.warning(
                    self,
                    "Invalid Threshold",
                    "Minimum group total must be at least 1."
                )
                self.threshold_edit.setFocus()
                return
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Number",
                "Please enter a valid number for the minimum group total."
            )
            self.threshold_edit.setFocus()
            return

        # Check for collection if subtracting owned cards
        owned_cards = None
        if self.subtract_owned_check.isChecked():
            if not self.sorter_tab.all_cards:
                reply = QMessageBox.question(
                    self,
                    "No Collection Loaded",
                    "You've chosen to subtract owned cards, but no collection is loaded in the Sorter tab.\n\n"
                    "Do you want to:\n"
                    "• Continue without subtracting owned cards, or\n"
                    "• Cancel and load a collection first?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                else:
                    self.subtract_owned_check.setChecked(False)
            else:
                owned_cards = self.sorter_tab.all_cards

        # Prepare options
        self.options = {
            'set_code': set_code,
            'weighted': self.weighted_check.isChecked(),
            'preset': self.preset_combo.currentText(),
            'group': self.group_check.isChecked(),
            'threshold': threshold,
            'owned_cards': owned_cards
        }

        # Handle export option
        if self.export_check.isChecked():
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Save Analysis CSV",
                f"{set_code}_analysis.csv",
                "CSV Files (*.csv);All Files (*.*)"
            )
            if not filepath:
                return
            self.options['export_path'] = filepath

        # Start analysis
        self._start_analysis()

    def _start_analysis(self):
        """Start the analysis worker thread"""
        # Update UI state
        self.run_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate initially
        self.results_summary.setVisible(False)

        set_code = self.options['set_code'].upper()
        self.status_label.setText(f"Starting analysis for '{set_code}'...")

        # Emit signal for main window
        self.operation_started.emit(f"Analyzing set {set_code}", 0)

        # Create and start worker
        self.analysis_thread = QThread()
        self.analysis_worker = SetAnalysisWorker(self.options, self.api)
        self.analysis_worker.moveToThread(self.analysis_thread)

        # Connect signals
        self.analysis_thread.started.connect(self.analysis_worker.process)
        self.analysis_worker.finished.connect(self.on_analysis_finished)
        self.analysis_worker.error.connect(self.on_analysis_error)
        self.analysis_worker.progress.connect(self.on_analysis_progress)
        self.analysis_worker.status_update.connect(self.on_status_update)

        # Cleanup
        self.analysis_worker.finished.connect(self.analysis_thread.quit)
        self.analysis_worker.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self.analysis_thread.deleteLater)

        self.analysis_thread.start()

    def on_analysis_progress(self, current: int, total: int):
        """Handle progress updates from worker"""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.progress_updated.emit(current)

    def on_status_update(self, message: str):
        """Handle status updates from worker"""
        self.status_label.setText(message)

    def cancel_analysis(self):
        """Cancel the current analysis"""
        if self.analysis_thread and self.analysis_thread.isRunning():
            cleanup_worker_thread(self.analysis_thread, self.analysis_worker)

        self._reset_ui_state()
        self.status_label.setText("Analysis cancelled.")
        self.operation_finished.emit()

    def on_analysis_finished(self, result):
        """Handle successful analysis completion"""
        set_code_str = f"'{result['set_code'].upper()}'"

        # Create detailed summary
        summary_parts = [f"Analysis completed for {set_code_str}"]

        if 'missing_count' in result:
            owned = result.get('owned_count', 0)
            missing = result.get('missing_count', 0)
            total = result.get('original_set_size', owned + missing)
            summary_parts.append(f"Set contains {total} cards total")
            summary_parts.append(f"You own {owned} cards ({owned / total * 100:.1f}%)")
            summary_parts.append(f"Missing {missing} cards ({missing / total * 100:.1f}%)")
            set_code_str += " (Missing Cards Only)"
        else:
            total = result.get('total_cards_analyzed', 0)
            summary_parts.append(f"Analyzed {total} cards")

        if result['weighted']:
            summary_parts.append("Weighted analysis using " + self.options['preset'] + " preset")

        summary_text = '\n'.join(summary_parts)

        self.status_label.setText(f"✓ Analysis complete for {set_code_str}")
        self.results_summary.setText(summary_text)
        self.results_summary.setVisible(True)

        self._reset_ui_state()
        self.last_analysis_data = result
        self.redraw_chart()

        # Handle export
        if export_path := self.analysis_worker.options.get('export_path'):
            self._export_results(export_path, result)

        self.operation_finished.emit()

    def on_analysis_error(self, error_message: str):
        """Handle analysis errors with detailed feedback"""
        self.status_label.setText("❌ Analysis failed - see details below")
        self._reset_ui_state()

        # Show detailed error in results area
        self.results_summary.setText(f"Error: {error_message}")
        self.results_summary.setVisible(True)

        # Also show popup for critical errors
        if any(term in error_message.lower() for term in ['not found', 'invalid', 'connection']):
            QMessageBox.warning(self, "Analysis Failed", error_message)

        self.operation_finished.emit()

    def _reset_ui_state(self):
        """Reset UI to ready state"""
        self.run_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.progress_bar.setVisible(False)

    def _export_results(self, export_path: str, result: dict):
        """Export analysis results to CSV"""
        try:
            if not result['sorted_groups']:
                QMessageBox.information(self, "Export Info", "No data to export.")
                return

            # Prepare data for export
            weighted = result['weighted']
            flat_results = [
                (group, data['total_weighted' if weighted else 'total_raw'])
                for group, data in result['sorted_groups']
            ]

            # Write CSV
            with open(export_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Letter Group", "Count"])
                writer.writerows(flat_results)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Analysis results exported to:\n{export_path}"
            )

        except PermissionError:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Cannot write to '{export_path}'.\n\n"
                "The file may be open in another program or you may not have write permissions."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export results:\n\n{str(e)}"
            )

    def redraw_chart(self):
        """Redraw the analysis chart with current options"""
        if self.last_analysis_data is None:
            return

        # This is a safeguard; chart should exist if we have data, but check anyway.
        if not self.ax:
            return

        self.ax.clear()
        data = self.last_analysis_data

        if not data['sorted_groups']:
            self.ax.text(
                0.5, 0.5,
                "No cards to display.\n(You might own the entire set!)",
                ha='center', va='center', color='white', fontsize=12,
                transform=self.ax.transAxes
            )
            title = f"Card Distribution for Set: {data['set_code'].upper()}"
            if 'missing_count' in data:
                title += " (Missing Cards)"
            self.ax.set_title(title, color='white')
            self.canvas.draw()
            return

        # Prepare data
        color_mode = self.color_by_combo.currentText()
        labels = [item[0] for item in data['sorted_groups']]

        # Create chart based on color mode
        if color_mode == "None":
            values = [
                item[1]['total_weighted' if data['weighted'] else 'total_raw']
                for item in data['sorted_groups']
            ]
            bars = self.ax.bar(labels, values, color='#007acc')

            # Add value labels on bars
            for bar, value in zip(bars, values):
                if value > 0:
                    self.ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(values) * 0.01,
                        str(int(value)),
                        ha='center', va='bottom', color='white', fontsize=8
                    )
        else:  # Rarity coloring
            all_rarities = sorted(list(self.RARITY_COLORS.keys()))
            bottoms = {label: 0 for label in labels}

            for rarity in all_rarities:
                values = [item[1]['rarity'].get(rarity, 0) for item in data['sorted_groups']]
                bars = self.ax.bar(
                    labels, values,
                    bottom=[bottoms[l] for l in labels],
                    color=self.RARITY_COLORS.get(rarity, '#ffffff'),
                    label=rarity.title()
                )

                # Update bottoms for stacking
                for i, label in enumerate(labels):
                    bottoms[label] += values[i]

            # Add legend
            self.ax.legend(
                labelcolor='white',
                facecolor='#3c3f41',
                edgecolor='#555',
                loc='upper right'
            )

        # Set title and labels
        title = f"Card Distribution for Set: {data['set_code'].upper()}"
        if 'missing_count' in data:
            title += " (Missing Cards Only)"

        self.ax.set_title(title, color='white', fontsize=12, pad=20)

        ylabel = "Count"
        if data['weighted']:
            ylabel = f"Weighted Score ({self.options.get('preset', 'default')} preset)"
        self.ax.set_ylabel(ylabel, color='white')

        # Style the plot
        self.ax.tick_params(colors='white')
        for spine in self.ax.spines.values():
            spine.set_color('white')

        # Rotate x-axis labels if needed
        if len(labels) > 10:
            self.ax.tick_params(axis='x', rotation=45)

        # Adjust layout and draw
        self.canvas.figure.tight_layout()
        self.canvas.draw()