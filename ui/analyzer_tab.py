# ui/analyzer_tab.py

import csv

from PyQt6.QtCore import pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QTextEdit,
)

from api.scryfall_api import ScryfallAPI
from workers.threads import SetAnalysisWorker, WorkerManager
from ui.sorter_tab import ManaBoxSorterTab
from .status_manager import StatusManager, StatusAwareMixin


class SetAnalyzerTab(QWidget, StatusAwareMixin):
    RARITY_COLORS = {
        "common": "#9a9a9a",
        "uncommon": "#c0c0c0",
        "rare": "#d4af37",
        "mythic": "#ff6600",
    }

    # Color palette for different sets
    SET_COLORS = [
        "#007acc",  # Blue
        "#ff6600",  # Orange
        "#00cc66",  # Green
        "#cc0066",  # Magenta
        "#6600cc",  # Purple
        "#cc6600",  # Brown
        "#0066cc",  # Dark Blue
        "#cc0000",  # Red
        "#00cccc",  # Cyan
        "#cccc00",  # Yellow
    ]

    # Signals for main window communication
    operation_started = pyqtSignal(str, int)  # message, max_value
    operation_finished = pyqtSignal()
    progress_updated = pyqtSignal(int)

    def __init__(self, api: ScryfallAPI, sorter_tab: "ManaBoxSorterTab"):
        super().__init__()
        self.api = api
        self.sorter_tab = sorter_tab  # Keep a reference to the sorter tab

        # Centralized worker management
        self.worker_manager = WorkerManager()

        # Legacy thread/worker attributes for backward compatibility
        self.analysis_thread = None
        self.analysis_worker = None
        self.last_analysis_data = None
        self.options: dict = {}  # Initialize options attribute

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
        self.set_code_edit.setPlaceholderText(
            "e.g., 'mh3' or 'mh3,ltr,dmu' for multiple sets"
        )
        self.set_code_edit.setToolTip(
            "Enter Magic set code(s) to analyze.\n\n"
            "Single set:\n"
            "• mh3 - Modern Horizons 3\n"
            "• ltr - Lord of the Rings\n\n"
            "Multiple sets (comma-separated):\n"
            "• mh3,ltr,dmu - Analyze all three sets combined\n"
            "• neo,neo2 - Analyze both Kamigawa sets\n\n"
            "This will combine all cards from the specified sets for analysis."
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
        self.color_by_combo.addItems(["None", "Rarity", "Set", "WUBRG Colors"])
        self.color_by_combo.setToolTip(
            "Choose how to color the chart bars:\n\n"
            "• None: Single color for all bars\n"
            "• Rarity: Stack bars by card rarity (common/uncommon/rare/mythic)\n"
            "• Set: Color bars by source set (useful for multiple sets)\n"
            "• WUBRG Colors: Create 5 separate charts by color identity (White/Blue/Black/Red/Green)"
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
        for widget in (
            self.weighted_check,
            self.group_check,
            self.preset_combo,
            self.threshold_edit,
            self.color_by_combo,
        ):
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
        self.run_button.setToolTip(
            "Start the set analysis with current settings (Shortcut: Ctrl+R)"
        )
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

        # Initialize StatusAwareMixin after UI is set up
        StatusAwareMixin.__init__(self)
        self._init_status_manager()

    def _create_chart_area(self, layout):
        """Create the chart display area"""
        # If already created, do nothing.
        if self.canvas:
            return
        # Import matplotlib components just-in-time to avoid startup conflicts
        import matplotlib

        matplotlib.use("QtAgg")  # Explicitly use modern backend for PyQt6
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qtagg import (
            NavigationToolbar2QT as NavigationToolbar,
        )
        from matplotlib.figure import Figure

        # Create matplotlib figure with dark theme
        self.canvas = FigureCanvas(Figure(facecolor="#2b2b2b"))
        self.ax = self.canvas.figure.subplots()

        # Style the plot for dark theme
        self.ax.tick_params(colors="white")
        for spine in self.ax.spines.values():
            spine.set_color("white")

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
        set_input = self.set_code_edit.text().strip().lower()
        if not set_input:
            QMessageBox.information(
                self,
                "Missing Set Code",
                "Please enter a set code to analyze.\n\n"
                "Examples: mh3, ltr, dmu, neo\n"
                "Multiple sets: mh3,ltr,dmu",
            )
            self.set_code_edit.setFocus()
            return

        # Parse multiple set codes
        set_codes = [code.strip() for code in set_input.split(",")]
        set_codes = [code for code in set_codes if code]  # Remove empty strings

        if not set_codes:
            QMessageBox.information(
                self, "Invalid Set Codes", "Please enter valid set codes to analyze."
            )
            self.set_code_edit.setFocus()
            return

        # Validate each set code format
        invalid_codes = []
        for set_code in set_codes:
            if len(set_code) < 2 or len(set_code) > 6:
                invalid_codes.append(set_code)

        if invalid_codes:
            reply = QMessageBox.question(
                self,
                "Unusual Set Codes",
                f"These set codes don't look typical: {', '.join(invalid_codes)}\n\n"
                "Most set codes are 3-4 characters (e.g., 'mh3', 'ltr').\n\n"
                "Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Validate threshold
        try:
            threshold = float(self.threshold_edit.text())
            if threshold < 1:
                QMessageBox.warning(
                    self, "Invalid Threshold", "Minimum group total must be at least 1."
                )
                self.threshold_edit.setFocus()
                return
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Number",
                "Please enter a valid number for the minimum group total.",
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
                    QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                else:
                    self.subtract_owned_check.setChecked(False)
            else:
                owned_cards = self.sorter_tab.all_cards

        # Prepare options
        self.options = {
            "set_codes": set_codes,
            "weighted": self.weighted_check.isChecked(),
            "preset": self.preset_combo.currentText(),
            "group": self.group_check.isChecked(),
            "threshold": threshold,
            "owned_cards": owned_cards,
        }

        # Handle export option
        if self.export_check.isChecked():
            # Create filename based on number of sets
            if len(set_codes) == 1:
                filename = f"{set_codes[0]}_analysis.csv"
            else:
                filename = f"combined_{len(set_codes)}_sets_analysis.csv"

            filepath, _ = QFileDialog.getSaveFileName(
                self, "Save Analysis CSV", filename, "CSV Files (*.csv);All Files (*.*)"
            )
            if not filepath:
                return
            self.options["export_path"] = filepath

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

        set_codes = self.options["set_codes"]
        if len(set_codes) == 1:
            set_display = set_codes[0].upper()
            self.show_status_message(
                f"Starting analysis for '{set_display}'...", style="info"
            )
            self.operation_started.emit(f"Analyzing set {set_display}", 0)
        else:
            set_display = ", ".join(code.upper() for code in set_codes)
            self.show_status_message(
                f"Starting analysis for {len(set_codes)} sets: {set_display}...",
                style="info",
            )
            self.operation_started.emit(f"Analyzing {len(set_codes)} sets", 0)

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
        self.show_status_message(message, style="info")

    def cancel_analysis(self):
        """Cancel the current analysis"""
        # Use centralized worker management
        self.worker_manager.cleanup_all()

        # Legacy cleanup for backward compatibility
        if self.analysis_thread and self.analysis_thread.isRunning():
            from workers.threads import cleanup_worker_thread

            cleanup_worker_thread(self.analysis_thread, self.analysis_worker)

        self._reset_ui_state()
        self.show_status_message("Analysis cancelled.", style="warning")
        self.operation_finished.emit()

    def on_analysis_finished(self, result):
        """Handle successful analysis completion"""
        set_codes = result.get("set_codes", [result.get("set_code", "")])
        if len(set_codes) == 1:
            set_code_str = f"'{set_codes[0].upper()}'"
        else:
            set_code_str = f"{len(set_codes)} sets: {', '.join(code.upper() for code in set_codes)}"

        # Create detailed summary
        summary_parts = [f"Analysis completed for {set_code_str}"]

        if "missing_count" in result:
            owned = result.get("owned_count", 0)
            missing = result.get("missing_count", 0)
            total = result.get("original_set_size", owned + missing)
            summary_parts.append(f"Set contains {total} cards total")
            summary_parts.append(f"You own {owned} cards ({owned / total * 100:.1f}%)")
            summary_parts.append(
                f"Missing {missing} cards ({missing / total * 100:.1f}%)"
            )
            set_code_str += " (Missing Cards Only)"
        else:
            total = result.get("total_cards_analyzed", 0)
            summary_parts.append(f"Analyzed {total} cards")

        if result["weighted"]:
            summary_parts.append(
                "Weighted analysis using " + self.options["preset"] + " preset"
            )

        summary_text = "\n".join(summary_parts)

        self.show_status_message(
            f"Analysis complete for {set_code_str}", style="success"
        )
        self.results_summary.setText(summary_text)
        self.results_summary.setVisible(True)

        self._reset_ui_state()
        self.last_analysis_data = result

        # Store raw card data for WUBRG analysis
        if hasattr(self.analysis_worker, "raw_cards"):
            self.last_analysis_cards = self.analysis_worker.raw_cards
        else:
            self.last_analysis_cards = []

        self.redraw_chart()

        # Handle export
        if export_path := self.analysis_worker.options.get("export_path"):
            self._export_results(export_path, result)

        self.operation_finished.emit()

    def on_analysis_error(self, error_message: str):
        """Handle analysis errors with detailed feedback"""
        self.show_status_message("Analysis failed - see details below", style="error")
        self._reset_ui_state()

        # Show detailed error in results area
        self.results_summary.setText(f"Error: {error_message}")
        self.results_summary.setVisible(True)

        # Also show popup for critical errors
        if any(
            term in error_message.lower()
            for term in ["not found", "invalid", "connection"]
        ):
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
            if not result["sorted_groups"]:
                QMessageBox.information(self, "Export Info", "No data to export.")
                return

            # Prepare data for export
            weighted = result["weighted"]
            flat_results = [
                (group, data["total_weighted" if weighted else "total_raw"])
                for group, data in result["sorted_groups"]
            ]

            # Write CSV
            with open(export_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Letter Group", "Count"])
                writer.writerows(flat_results)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Analysis results exported to:\n{export_path}",
            )

        except PermissionError:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Cannot write to '{export_path}'.\n\n"
                "The file may be open in another program or you may not have write permissions.",
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Export Error", f"Failed to export results:\n\n{str(e)}"
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

        if not data["sorted_groups"]:
            self.ax.text(
                0.5,
                0.5,
                "No cards to display.\n(You might own the entire set!)",
                ha="center",
                va="center",
                color="white",
                fontsize=12,
                transform=self.ax.transAxes,
            )
            set_codes = data.get("set_codes", [data.get("set_code", "")])
            if len(set_codes) == 1:
                title = f"Card Distribution for Set: {set_codes[0].upper()}"
            else:
                title = f"Card Distribution for {len(set_codes)} Sets: {', '.join(code.upper() for code in set_codes)}"
            if "missing_count" in data:
                title += " (Missing Cards)"
            self.ax.set_title(title, color="white")
            self.canvas.draw()
            return

        # Prepare data
        color_mode = self.color_by_combo.currentText()
        labels = [item[0] for item in data["sorted_groups"]]

        # Create chart based on color mode
        if color_mode == "None":
            values = [
                item[1]["total_weighted" if data["weighted"] else "total_raw"]
                for item in data["sorted_groups"]
            ]
            bars = self.ax.bar(labels, values, color="#007acc")

            # Add value labels on bars
            for bar, value in zip(bars, values):
                if value > 0:
                    self.ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(values) * 0.01,
                        str(int(value)),
                        ha="center",
                        va="bottom",
                        color="white",
                        fontsize=8,
                    )
        elif color_mode == "WUBRG Colors":  # WUBRG color-based charts
            self._create_wubrg_charts(data)
            return  # Early return since we create multiple charts
        elif color_mode == "Set":  # Set-based coloring
            self._create_set_colored_chart(data, labels)
        else:  # Rarity coloring
            all_rarities = sorted(list(self.RARITY_COLORS.keys()))
            bottoms = {label: 0 for label in labels}

            for rarity in all_rarities:
                values = [
                    item[1]["rarity"].get(rarity, 0) for item in data["sorted_groups"]
                ]
                bars = self.ax.bar(
                    labels,
                    values,
                    bottom=[bottoms[l] for l in labels],
                    color=self.RARITY_COLORS.get(rarity, "#ffffff"),
                    label=rarity.title(),
                )

                # Update bottoms for stacking
                for i, label in enumerate(labels):
                    bottoms[label] += values[i]

            # Add legend
            self.ax.legend(
                labelcolor="white",
                facecolor="#3c3f41",
                edgecolor="#555",
                loc="upper right",
            )

        # Set title and labels
        set_codes = data.get("set_codes", [data.get("set_code", "")])
        if len(set_codes) == 1:
            title = f"Card Distribution for Set: {set_codes[0].upper()}"
        else:
            title = f"Card Distribution for {len(set_codes)} Sets: {', '.join(code.upper() for code in set_codes)}"
        if "missing_count" in data:
            title += " (Missing Cards Only)"

        self.ax.set_title(title, color="white", fontsize=12, pad=20)

        ylabel = "Count"
        if data["weighted"]:
            ylabel = f"Weighted Score ({self.options.get('preset', 'default')} preset)"
        self.ax.set_ylabel(ylabel, color="white")

        # Style the plot
        self.ax.tick_params(colors="white")
        for spine in self.ax.spines.values():
            spine.set_color("white")

        # Rotate x-axis labels if needed
        if len(labels) > 10:
            self.ax.tick_params(axis="x", rotation=45)

        # Adjust layout and draw
        self.canvas.figure.tight_layout()
        self.canvas.draw()

    def _create_set_colored_chart(self, data, labels):
        """Create a chart colored by set with legend"""
        set_codes = data.get("set_codes", [])

        # If only one set, use single color
        if len(set_codes) <= 1:
            values = [
                item[1]["total_weighted" if data["weighted"] else "total_raw"]
                for item in data["sorted_groups"]
            ]
            bars = self.ax.bar(labels, values, color=self.SET_COLORS[0])

            # Add value labels
            for bar, value in zip(bars, values):
                if value > 0:
                    self.ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(values) * 0.01,
                        str(int(value)),
                        ha="center",
                        va="bottom",
                        color="white",
                        fontsize=8,
                    )
            return

        # Multiple sets - create stacked bars
        set_colors = {
            set_code: self.SET_COLORS[i % len(self.SET_COLORS)]
            for i, set_code in enumerate(set_codes)
        }

        # Create stacked bars for each set
        bottoms = {label: 0 for label in labels}
        legend_handles = []

        for set_code in set_codes:
            values = []
            for item in data["sorted_groups"]:
                set_breakdown = item[1].get("set_breakdown", {})
                values.append(set_breakdown.get(set_code, 0))

            if any(v > 0 for v in values):  # Only show sets with cards
                bars = self.ax.bar(
                    labels,
                    values,
                    bottom=[bottoms[label] for label in labels],
                    color=set_colors[set_code],
                    label=set_code.upper(),
                )

                # Update bottoms for stacking
                for i, label in enumerate(labels):
                    bottoms[label] += values[i]

                # Store handle for legend
                if bars:
                    legend_handles.append(bars[0])

        # Add legend
        if legend_handles:
            self.ax.legend(
                handles=legend_handles,
                labels=[
                    set_code.upper()
                    for set_code in set_codes
                    if any(
                        item[1].get("set_breakdown", {}).get(set_code, 0) > 0
                        for item in data["sorted_groups"]
                    )
                ],
                labelcolor="white",
                facecolor="#3c3f41",
                edgecolor="#555",
                loc="upper right",
            )

    def _create_wubrg_charts(self, data):
        """Create separate charts organized by WUBRG color identity with proper categorization"""
        # WUBRG color mapping with improved visibility
        wubrg_colors = {
            "W": {"name": "White", "color": "#f0f0f0"},
            "U": {"name": "Blue", "color": "#007acc"},
            "B": {
                "name": "Black",
                "color": "#808080",
            },  # Changed from dark to light gray for visibility
            "R": {"name": "Red", "color": "#cc0000"},
            "G": {"name": "Green", "color": "#00cc66"},
        }

        # Clear the current chart
        self.ax.clear()

        # Get the original card data to determine color identities
        if not hasattr(self, "last_analysis_cards") or not self.last_analysis_cards:
            self.ax.text(
                0.5,
                0.5,
                "WUBRG analysis requires card data.\nPlease re-run the analysis.",
                ha="center",
                va="center",
                color="white",
                fontsize=12,
                transform=self.ax.transAxes,
            )
            self.canvas.draw()
            return

        # Categorize cards properly
        single_color_groups = {color: [] for color in wubrg_colors.keys()}
        multicolor_cards = []
        colorless_cards = []
        land_cards = []

        for card_data in self.last_analysis_cards:
            color_identity = card_data.get("color_identity", [])
            card_type = card_data.get("type_line", "").lower()

            # Check if it's a land
            if "land" in card_type:
                land_cards.append(card_data)
            elif not color_identity:
                # True colorless (artifacts, etc.)
                colorless_cards.append(card_data)
            elif len(color_identity) == 1:
                # Single color cards only
                single_color_groups[color_identity[0]].append(card_data)
            else:
                # Multicolor cards
                multicolor_cards.append(card_data)

        # Create subplots - we need space for all categories
        fig = self.canvas.figure
        fig.clear()

        # Determine grid layout based on what we have
        charts_to_create = []

        # Add single color charts
        for color_code, color_info in wubrg_colors.items():
            if single_color_groups[color_code]:
                charts_to_create.append(
                    ("single", color_code, color_info, single_color_groups[color_code])
                )

        # Add multicolor chart if we have multicolor cards
        if multicolor_cards:
            charts_to_create.append(
                (
                    "multicolor",
                    None,
                    {"name": "Multicolor", "color": "#ff6600"},
                    multicolor_cards,
                )
            )

        # Add colorless chart if we have colorless cards
        if colorless_cards:
            charts_to_create.append(
                (
                    "colorless",
                    None,
                    {"name": "Colorless", "color": "#9a9a9a"},
                    colorless_cards,
                )
            )

        # Add lands chart if we have lands
        if land_cards:
            charts_to_create.append(
                ("lands", None, {"name": "Lands", "color": "#8b4513"}, land_cards)
            )

        if not charts_to_create:
            self.ax.text(
                0.5,
                0.5,
                "No cards to display in WUBRG analysis.",
                ha="center",
                va="center",
                color="white",
                fontsize=12,
                transform=self.ax.transAxes,
            )
            self.canvas.draw()
            return

        # Create grid layout - use 2x3 for up to 6 charts
        num_charts = len(charts_to_create)
        if num_charts <= 6:
            rows, cols = 2, 3
        elif num_charts <= 9:
            rows, cols = 3, 3
        else:
            rows, cols = 4, 3

        gs = fig.add_gridspec(rows, cols, hspace=0.3, wspace=0.3)

        # Create charts
        for i, (chart_type, color_code, color_info, cards) in enumerate(
            charts_to_create
        ):
            if i >= rows * cols:
                break

            row = i // cols
            col = i % cols
            ax = fig.add_subplot(gs[row, col])

            # Analyze letter frequency for this category
            letter_counts = {}
            for card_data in cards:
                card_name = card_data.get("name", "")
                if not card_name:
                    continue

                first_letter = card_name[0].upper()
                if first_letter not in letter_counts:
                    letter_counts[first_letter] = 0
                letter_counts[first_letter] += 1

            if not letter_counts:
                ax.text(
                    0.5,
                    0.5,
                    f"No valid {color_info['name']} card names",
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=10,
                    transform=ax.transAxes,
                )
                ax.set_title(f"{color_info['name']} Cards", color="white", fontsize=10)
                ax.set_facecolor("#2b2b2b")
                continue

            # Sort letters by count (descending) for better visualization
            sorted_letters = sorted(
                letter_counts.items(), key=lambda x: x[1], reverse=True
            )
            letters, counts = zip(*sorted_letters)

            # Create bar chart
            bars = ax.bar(letters, counts, color=color_info["color"])

            # Add value labels on bars
            for bar, count in zip(bars, counts):
                if count > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(counts) * 0.01,
                        str(count),
                        ha="center",
                        va="bottom",
                        color="white",
                        fontsize=8,
                    )

            # Style the chart
            ax.set_title(
                f"{color_info['name']} Cards ({len(cards)} total)",
                color="white",
                fontsize=10,
            )
            ax.set_ylabel("Count", color="white", fontsize=8)
            ax.tick_params(colors="white", labelsize=8)
            ax.set_facecolor("#2b2b2b")

            # Style spines
            for spine in ax.spines.values():
                spine.set_color("white")

        # Set overall title
        set_codes = data.get("set_codes", [data.get("set_code", "")])
        if len(set_codes) == 1:
            title = f"WUBRG Analysis for Set: {set_codes[0].upper()}"
        else:
            title = f"WUBRG Analysis for {len(set_codes)} Sets: {', '.join(code.upper() for code in set_codes)}"
        if "missing_count" in data:
            title += " (Missing Cards Only)"

        fig.suptitle(title, color="white", fontsize=14, y=0.95)

        # Draw the updated figure
        self.canvas.draw()
