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
from ui.status_manager import StatusAwareMixin


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
        grid = QGridLayout()

        self.set_code_edit = QLineEdit()
        self.set_code_edit.setPlaceholderText(
            "e.g., 'mh3' or 'mh3,ltr,dmu' for multiple sets"
        )
        self.set_code_edit.setToolTip("Enter Magic set code(s) to analyze")

        self.subtract_owned_check = QCheckBox("Subtract Owned Cards (from Collection)")
        self.subtract_owned_check.setToolTip("Exclude owned cards from analysis")

        self.weighted_check = QCheckBox("Weighted Analysis")
        self.weighted_check.setToolTip("Weight cards by rarity")

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["default", "play_booster", "dynamic"])
        self.preset_combo.setToolTip("Choose weighting strategy")

        self.group_check = QCheckBox("Group low count letters")
        self.group_check.setChecked(True)
        self.group_check.setToolTip("Combine letters with few cards")

        self.threshold_edit = QLineEdit("20")
        self.threshold_edit.setToolTip("Minimum cards for grouping")

        self.color_by_combo = QComboBox()
        self.color_by_combo.addItems(["None", "Rarity", "Set", "WUBRG Colors"])
        self.color_by_combo.setToolTip("Choose chart coloring")

        self.export_check = QCheckBox("Export to CSV on run")
        self.export_check.setToolTip("Auto-save results to CSV")

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

        spacer_label = QLabel("")
        spacer_label.setMinimumHeight(10)
        grid.addWidget(spacer_label, 7, 0, 1, 2)

        separator = QLabel("─" * 30)
        separator.setStyleSheet("color: #666;")
        grid.addWidget(separator, 7, 0, 1, 2)

        export_label = QLabel("Export Options:")
        export_label.setStyleSheet(
            "font-weight: bold; color: #00aaff; font-size: 12px;"
        )
        grid.addWidget(export_label, 8, 0)

        grid.addWidget(self.export_check, 9, 0, 1, 2)

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

        self.run_button = QPushButton("Run Analysis")
        self.run_button.setObjectName("AccentButton")
        self.run_button.setToolTip("Start analysis (Ctrl+R)")
        self.run_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.run_button)

        self.status_label = QLabel("Enter a set code to begin analysis.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("Cancel Analysis")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        layout.addWidget(self.cancel_button)

        self.results_summary = QTextEdit()
        self.results_summary.setMaximumHeight(100)
        self.results_summary.setVisible(False)
        self.results_summary.setReadOnly(True)
        layout.addWidget(self.results_summary)

        StatusAwareMixin.__init__(self)
        self._init_status_manager()

    def _create_chart_area(self, layout):
        if self.canvas:
            return
        import matplotlib

        matplotlib.use("QtAgg")
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qtagg import (
            NavigationToolbar2QT as NavigationToolbar,
        )
        from matplotlib.figure import Figure

        self.canvas = FigureCanvas(Figure(facecolor="#2b2b2b"))
        self.ax = self.canvas.figure.subplots()

        self.ax.tick_params(colors="white")
        for spine in self.ax.spines.values():
            spine.set_color("white")

        toolbar = NavigationToolbar(self.canvas, self)
        toolbar.setObjectName("qt_toolbar_navigation")

        layout.addWidget(toolbar)
        layout.addWidget(self.canvas)

    def run_analysis(self):
        self._create_chart_area(self.chart_layout)

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

        set_codes = [code.strip() for code in set_input.split(",")]
        set_codes = [code for code in set_codes if code]

        if not set_codes:
            QMessageBox.information(
                self, "Invalid Set Codes", "Please enter valid set codes to analyze."
            )
            self.set_code_edit.setFocus()
            return

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

        self.options = {
            "set_codes": set_codes,
            "weighted": self.weighted_check.isChecked(),
            "preset": self.preset_combo.currentText(),
            "group": self.group_check.isChecked(),
            "threshold": threshold,
            "owned_cards": owned_cards,
        }

        if self.export_check.isChecked():
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

        self._start_analysis()

    def _start_analysis(self):
        self.run_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
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

        self.analysis_thread = QThread()
        self.analysis_worker = SetAnalysisWorker(self.options, self.api)
        self.analysis_worker.moveToThread(self.analysis_thread)

        self.analysis_thread.started.connect(self.analysis_worker.process)
        self.analysis_worker.finished.connect(self.on_analysis_finished)
        self.analysis_worker.error.connect(self.on_analysis_error)
        self.analysis_worker.progress.connect(self.on_analysis_progress)
        self.analysis_worker.status_update.connect(self.on_status_update)

        self.analysis_worker.finished.connect(self.analysis_thread.quit)
        self.analysis_worker.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self.analysis_thread.deleteLater)

        self.analysis_thread.start()

    def on_analysis_progress(self, current: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.progress_updated.emit(current)

    def on_status_update(self, message: str):
        self.show_status_message(message, style="info")

    def cancel_analysis(self):
        self.worker_manager.cleanup_all()

        if self.analysis_thread and self.analysis_thread.isRunning():
            from workers.threads import cleanup_worker_thread

            cleanup_worker_thread(self.analysis_thread, self.analysis_worker)

        self._reset_ui_state()
        self.show_status_message("Analysis cancelled.", style="warning")
        self.operation_finished.emit()

    def on_analysis_finished(self, result):
        set_codes = result.get("set_codes", [result.get("set_code", "")])
        if len(set_codes) == 1:
            set_code_str = f"'{set_codes[0].upper()}'"
        else:
            set_code_str = f"{len(set_codes)} sets: {', '.join(code.upper() for code in set_codes)}"

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

        if hasattr(self.analysis_worker, "raw_cards"):
            self.last_analysis_cards = self.analysis_worker.raw_cards
        else:
            self.last_analysis_cards = []

        self.redraw_chart()

        if export_path := self.analysis_worker.options.get("export_path"):
            self._export_results(export_path, result)

        self.operation_finished.emit()

    def on_analysis_error(self, error_message: str):
        self.show_status_message("Analysis failed - see details below", style="error")
        self._reset_ui_state()

        self.results_summary.setText(f"Error: {error_message}")
        self.results_summary.setVisible(True)

        if any(
            term in error_message.lower()
            for term in ["not found", "invalid", "connection"]
        ):
            QMessageBox.warning(self, "Analysis Failed", error_message)

        self.operation_finished.emit()

    def _reset_ui_state(self):
        self.run_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.progress_bar.setVisible(False)

    def _export_results(self, export_path: str, result: dict):
        try:
            if not result["sorted_groups"]:
                QMessageBox.information(self, "Export Info", "No data to export.")
                return

            if (
                self.color_by_combo.currentText() == "WUBRG Colors"
                and hasattr(self, "last_analysis_cards")
                and self.last_analysis_cards
            ):
                self._export_wubrg_to_csv(export_path, result)
            else:
                weighted = result["weighted"]
                flat_results = [
                    (group, data["total_weighted" if weighted else "total_raw"])
                    for group, data in result["sorted_groups"]
                ]

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

    def _export_wubrg_to_csv(self, filepath: str, result: dict):
        try:
            wubrg_colors = {
                "W": {"name": "White", "color": "#f0f0f0"},
                "U": {"name": "Blue", "color": "#007acc"},
                "B": {"name": "Black", "color": "#808080"},
                "R": {"name": "Red", "color": "#cc0000"},
                "G": {"name": "Green", "color": "#00cc66"},
            }

            single_color_groups: dict = {color: [] for color in wubrg_colors.keys()}
            multicolor_cards = []
            colorless_cards = []
            land_cards = []

            for card_data in self.last_analysis_cards:
                color_identity = card_data.get("color_identity", [])
                card_type = card_data.get("type_line", "").lower()

                if "land" in card_type:
                    land_cards.append(card_data)
                elif not color_identity:
                    colorless_cards.append(card_data)
                elif len(color_identity) == 1:
                    single_color_groups[color_identity[0]].append(card_data)
                else:
                    multicolor_cards.append(card_data)

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["Color Category", "Color Hex", "Letter", "Count", "Percentage"]
                )

                all_categories = []

                for color_code, color_info in wubrg_colors.items():
                    if single_color_groups[color_code]:
                        all_categories.append(
                            (
                                color_info["name"],
                                color_info["color"],
                                single_color_groups[color_code],
                            )
                        )

                if multicolor_cards:
                    all_categories.append(("Multicolor", "#ff6600", multicolor_cards))

                if colorless_cards:
                    all_categories.append(("Colorless", "#9a9a9a", colorless_cards))

                if land_cards:
                    all_categories.append(("Lands", "#8b4513", land_cards))

                for category_name, color_hex, cards in all_categories:
                    letter_counts = {}
                    for card_data in cards:
                        card_name = card_data.get("name", "")
                        if not card_name:
                            continue
                        first_letter = card_name[0].upper()
                        if first_letter not in letter_counts:
                            letter_counts[first_letter] = 0
                        letter_counts[first_letter] += 1

                    sorted_letters = sorted(
                        letter_counts.items(), key=lambda x: x[1], reverse=True
                    )
                    total_cards = sum(count for _, count in sorted_letters)

                    for letter, count in sorted_letters:
                        percentage = (
                            (count / total_cards * 100) if total_cards > 0 else 0
                        )
                        writer.writerow(
                            [
                                category_name,
                                color_hex,
                                letter,
                                count,
                                f"{percentage:.1f}%",
                            ]
                        )

        except Exception as e:
            QMessageBox.critical(
                self,
                "WUBRG Export Error",
                f"Failed to export WUBRG results:\n\n{str(e)}",
            )

    def redraw_chart(self):
        if self.last_analysis_data is None:
            return

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

        color_mode = self.color_by_combo.currentText()
        labels = [item[0] for item in data["sorted_groups"]]

        if color_mode == "None":
            values = [
                item[1]["total_weighted" if data["weighted"] else "total_raw"]
                for item in data["sorted_groups"]
            ]
            bars = self.ax.bar(labels, values, color="#007acc")

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
        elif color_mode == "WUBRG Colors":
            self._create_wubrg_charts(data)
            return
        elif color_mode == "Set":
            self._create_set_colored_chart(data, labels)
        else:
            all_rarities = sorted(list(self.RARITY_COLORS.keys()))
            bottoms = {label: 0 for label in labels}

            for rarity in all_rarities:
                values = [
                    item[1]["rarity"].get(rarity, 0) for item in data["sorted_groups"]
                ]
                bars = self.ax.bar(
                    labels,
                    values,
                    bottom=[bottoms[label] for label in labels],
                    color=self.RARITY_COLORS.get(rarity, "#ffffff"),
                    label=rarity.title(),
                )

                for i, label in enumerate(labels):
                    bottoms[label] += values[i]

            self.ax.legend(
                labelcolor="white",
                facecolor="#3c3f41",
                edgecolor="#555",
                loc="upper right",
            )

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

        self.ax.tick_params(colors="white")
        for spine in self.ax.spines.values():
            spine.set_color("white")

        if len(labels) > 10:
            self.ax.tick_params(axis="x", rotation=45)

        self.canvas.figure.tight_layout()
        self.canvas.draw()

    def _create_set_colored_chart(self, data, labels):
        set_codes = data.get("set_codes", [])

        if len(set_codes) <= 1:
            values = [
                item[1]["total_weighted" if data["weighted"] else "total_raw"]
                for item in data["sorted_groups"]
            ]
            bars = self.ax.bar(labels, values, color=self.SET_COLORS[0])

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

        set_colors = {
            set_code: self.SET_COLORS[i % len(self.SET_COLORS)]
            for i, set_code in enumerate(set_codes)
        }

        bottoms = {label: 0 for label in labels}
        legend_handles = []

        for set_code in set_codes:
            values = []
            for item in data["sorted_groups"]:
                set_breakdown = item[1].get("set_breakdown", {})
                values.append(set_breakdown.get(set_code, 0))

            if any(v > 0 for v in values):
                bars = self.ax.bar(
                    labels,
                    values,
                    bottom=[bottoms[label] for label in labels],
                    color=set_colors[set_code],
                    label=set_code.upper(),
                )

                for i, label in enumerate(labels):
                    bottoms[label] += values[i]

                if bars:
                    legend_handles.append(bars[0])

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
        wubrg_colors = {
            "W": {"name": "White", "color": "#f0f0f0"},
            "U": {"name": "Blue", "color": "#007acc"},
            "B": {"name": "Black", "color": "#808080"},
            "R": {"name": "Red", "color": "#cc0000"},
            "G": {"name": "Green", "color": "#00cc66"},
        }

        self.ax.clear()

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

        single_color_groups = {color: [] for color in wubrg_colors.keys()}
        multicolor_cards = []
        colorless_cards = []
        land_cards = []

        for card_data in self.last_analysis_cards:
            color_identity = card_data.get("color_identity", [])
            card_type = card_data.get("type_line", "").lower()

            if "land" in card_type:
                land_cards.append(card_data)
            elif not color_identity:
                colorless_cards.append(card_data)
            elif len(color_identity) == 1:
                single_color_groups[color_identity[0]].append(card_data)
            else:
                multicolor_cards.append(card_data)

        fig = self.canvas.figure
        fig.clear()

        charts_to_create = []

        for color_code, color_info in wubrg_colors.items():
            if single_color_groups[color_code]:
                charts_to_create.append(
                    ("single", color_code, color_info, single_color_groups[color_code])
                )

        if multicolor_cards:
            charts_to_create.append(
                (
                    "multicolor",
                    None,
                    {"name": "Multicolor", "color": "#ff6600"},
                    multicolor_cards,
                )
            )

        if colorless_cards:
            charts_to_create.append(
                (
                    "colorless",
                    None,
                    {"name": "Colorless", "color": "#9a9a9a"},
                    colorless_cards,
                )
            )

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

        num_charts = len(charts_to_create)
        if num_charts <= 6:
            rows, cols = 2, 3
        elif num_charts <= 9:
            rows, cols = 3, 3
        else:
            rows, cols = 4, 3

        gs = fig.add_gridspec(rows, cols, hspace=0.4, wspace=0.4)

        for i, (chart_type, color_code, color_info, cards) in enumerate(
            charts_to_create
        ):
            if i >= rows * cols:
                break

            row = i // cols
            col = i % cols
            ax = fig.add_subplot(gs[row, col])

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

            sorted_letters = sorted(
                letter_counts.items(), key=lambda x: x[1], reverse=True
            )
            letters, counts = zip(*sorted_letters)

            bars = ax.bar(letters, counts, color=color_info["color"])

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

            ax.set_title(
                f"{color_info['name']} Cards ({len(cards)} total)",
                color="white",
                fontsize=10,
                pad=15,
            )
            ax.set_ylabel("Count", color="white", fontsize=8)
            ax.tick_params(colors="white", labelsize=8)
            ax.set_facecolor("#2b2b2b")

            if len(letters) > 8:
                ax.tick_params(axis="x", rotation=45, labelsize=7)

            for spine in ax.spines.values():
                spine.set_color("white")

        set_codes = data.get("set_codes", [data.get("set_code", "")])
        if len(set_codes) == 1:
            title = f"WUBRG Analysis for Set: {set_codes[0].upper()}"
        else:
            title = f"WUBRG Analysis for {len(set_codes)} Sets: {', '.join(code.upper() for code in set_codes)}"
        if "missing_count" in data:
            title += " (Missing Cards Only)"

        fig.suptitle(title, color="white", fontsize=14, y=0.98)

        self.canvas.draw()

        if (
            hasattr(self, "last_analysis_cards")
            and self.last_analysis_cards
            and self.color_by_combo.currentText() == "WUBRG Colors"
        ):
            self._add_wubrg_export_buttons()

    def _export_wubrg_results(self, result):
        try:
            if not hasattr(self, "last_analysis_cards") or not self.last_analysis_cards:
                QMessageBox.information(self, "Export Info", "No WUBRG data to export.")
                return

            # Get set codes for filename
            set_codes = result.get("set_codes", [result.get("set_code", "")])
            if len(set_codes) == 1:
                base_filename = f"{set_codes[0]}_wubrg"
            else:
                base_filename = f"combined_{len(set_codes)}_sets_wubrg"

            # Ask user for export directory
            export_dir = QFileDialog.getExistingDirectory(
                self, "Select Directory for WUBRG Export", ""
            )
            if not export_dir:
                return

            # Categorize cards
            wubrg_colors = {
                "W": {"name": "White", "color": "#f0f0f0"},
                "U": {"name": "Blue", "color": "#007acc"},
                "B": {"name": "Black", "color": "#808080"},
                "R": {"name": "Red", "color": "#cc0000"},
                "G": {"name": "Green", "color": "#00cc66"},
            }

            single_color_groups: dict = {color: [] for color in wubrg_colors.keys()}
            multicolor_cards = []
            colorless_cards = []
            land_cards = []

            for card_data in self.last_analysis_cards:
                color_identity = card_data.get("color_identity", [])
                card_type = card_data.get("type_line", "").lower()

                if "land" in card_type:
                    land_cards.append(card_data)
                elif not color_identity:
                    colorless_cards.append(card_data)
                elif len(color_identity) == 1:
                    single_color_groups[color_identity[0]].append(card_data)
                else:
                    multicolor_cards.append(card_data)

            # Export individual color files
            exported_files = []

            # Single color exports
            for color_code, color_info in wubrg_colors.items():
                if single_color_groups[color_code]:
                    filename = f"{base_filename}_{color_info['name'].lower()}.csv"
                    filepath = f"{export_dir}/{filename}"
                    self._export_color_breakdown(
                        filepath,
                        single_color_groups[color_code],
                        color_info["name"],
                        color_info["color"],
                    )
                    exported_files.append(filename)

            # Multicolor export
            if multicolor_cards:
                filename = f"{base_filename}_multicolor.csv"
                filepath = f"{export_dir}/{filename}"
                self._export_color_breakdown(
                    filepath, multicolor_cards, "Multicolor", "#ff6600"
                )
                exported_files.append(filename)

            # Colorless export
            if colorless_cards:
                filename = f"{base_filename}_colorless.csv"
                filepath = f"{export_dir}/{filename}"
                self._export_color_breakdown(
                    filepath, colorless_cards, "Colorless", "#9a9a9a"
                )
                exported_files.append(filename)

            # Lands export
            if land_cards:
                filename = f"{base_filename}_lands.csv"
                filepath = f"{export_dir}/{filename}"
                self._export_color_breakdown(filepath, land_cards, "Lands", "#8b4513")
                exported_files.append(filename)

            # Combined summary export
            summary_filename = f"{base_filename}_summary.csv"
            summary_filepath = f"{export_dir}/{summary_filename}"
            self._export_wubrg_summary(
                summary_filepath,
                {
                    **{
                        color_info["name"]: single_color_groups[color_code]
                        for color_code, color_info in wubrg_colors.items()
                        if single_color_groups[color_code]
                    },
                    **({"Multicolor": multicolor_cards} if multicolor_cards else {}),
                    **({"Colorless": colorless_cards} if colorless_cards else {}),
                    **({"Lands": land_cards} if land_cards else {}),
                },
            )
            exported_files.append(summary_filename)

            if exported_files:
                QMessageBox.information(
                    self,
                    "WUBRG Export Successful",
                    f"WUBRG analysis exported to {len(exported_files)} files:\n\n"
                    + "\n".join(exported_files)
                    + f"\n\nLocation: {export_dir}",
                )
            else:
                QMessageBox.information(self, "Export Info", "No WUBRG data to export.")

        except Exception as e:
            QMessageBox.critical(
                self,
                "WUBRG Export Error",
                f"Failed to export WUBRG results:\n\n{str(e)}",
            )

    def _export_color_breakdown(self, filepath, cards, color_name, color_hex):
        letter_counts = {}
        for card_data in cards:
            card_name = card_data.get("name", "")
            if not card_name:
                continue
            first_letter = card_name[0].upper()
            if first_letter not in letter_counts:
                letter_counts[first_letter] = 0
            letter_counts[first_letter] += 1

        sorted_letters = sorted(letter_counts.items(), key=lambda x: x[1], reverse=True)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Color Category", "Color Hex", "Letter", "Count", "Percentage"]
            )

            total_cards = sum(count for _, count in sorted_letters)
            for letter, count in sorted_letters:
                percentage = (count / total_cards * 100) if total_cards > 0 else 0
                writer.writerow(
                    [color_name, color_hex, letter, count, f"{percentage:.1f}%"]
                )

    def _export_wubrg_summary(self, filepath, all_categories):
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Category", "Color Hex", "Total Cards", "Letter Count", "Top Letters"]
            )

            for category_name, cards in all_categories.items():
                if not cards:
                    continue

                color_hex = {
                    "White": "#f0f0f0",
                    "Blue": "#007acc",
                    "Black": "#808080",
                    "Red": "#cc0000",
                    "Green": "#00cc66",
                    "Multicolor": "#ff6600",
                    "Colorless": "#9a9a9a",
                    "Lands": "#8b4513",
                }.get(category_name, "#000000")

                letter_counts = {}
                for card_data in cards:
                    card_name = card_data.get("name", "")
                    if not card_name:
                        continue
                    first_letter = card_name[0].upper()
                    if first_letter not in letter_counts:
                        letter_counts[first_letter] = 0
                    letter_counts[first_letter] += 1

                sorted_letters = sorted(
                    letter_counts.items(), key=lambda x: x[1], reverse=True
                )
                top_letters = ", ".join(
                    [f"{letter}({count})" for letter, count in sorted_letters[:3]]
                )

                writer.writerow(
                    [
                        category_name,
                        color_hex,
                        len(cards),
                        len(letter_counts),
                        top_letters,
                    ]
                )

    def _add_wubrg_export_buttons(self):
        for widget in self.chart_layout.parent().findChildren(QPushButton):
            if widget.objectName() == "wubrg_export_button":
                widget.deleteLater()

        wubrg_colors = {
            "W": {"name": "White", "color": "#f0f0f0"},
            "U": {"name": "Blue", "color": "#007acc"},
            "B": {"name": "Black", "color": "#808080"},
            "R": {"name": "Red", "color": "#cc0000"},
            "G": {"name": "Green", "color": "#00cc66"},
        }

        single_color_groups = {color: [] for color in wubrg_colors.keys()}
        multicolor_cards = []
        colorless_cards = []
        land_cards = []

        for card_data in self.last_analysis_cards:
            color_identity = card_data.get("color_identity", [])
            card_type = card_data.get("type_line", "").lower()

            if "land" in card_type:
                land_cards.append(card_data)
            elif not color_identity:
                colorless_cards.append(card_data)
            elif len(color_identity) == 1:
                single_color_groups[color_identity[0]].append(card_data)
            else:
                multicolor_cards.append(card_data)

        button_layout = QHBoxLayout()

        for color_code, color_info in wubrg_colors.items():
            if single_color_groups[color_code]:
                button = QPushButton(f"Export {color_info['name']}")
                button.setObjectName("wubrg_export_button")
                button.setToolTip(f"Export {color_info['name']} cards breakdown to CSV")
                button.clicked.connect(
                    lambda checked, cards=single_color_groups[
                        color_code
                    ], name=color_info["name"], color=color_info[
                        "color"
                    ]: self._export_single_category(
                        cards, name, color
                    )
                )
                button_layout.addWidget(button)

        if multicolor_cards:
            button = QPushButton("Export Multicolor")
            button.setObjectName("wubrg_export_button")
            button.setToolTip("Export multicolor cards breakdown to CSV")
            button.clicked.connect(
                lambda checked, cards=multicolor_cards: self._export_single_category(
                    cards, "Multicolor", "#ff6600"
                )
            )
            button_layout.addWidget(button)

        if colorless_cards:
            button = QPushButton("Export Colorless")
            button.setObjectName("wubrg_export_button")
            button.setToolTip("Export colorless cards breakdown to CSV")
            button.clicked.connect(
                lambda checked, cards=colorless_cards: self._export_single_category(
                    cards, "Colorless", "#9a9a9a"
                )
            )
            button_layout.addWidget(button)

        if land_cards:
            button = QPushButton("Export Lands")
            button.setObjectName("wubrg_export_button")
            button.setToolTip("Export lands breakdown to CSV")
            button.clicked.connect(
                lambda checked, cards=land_cards: self._export_single_category(
                    cards, "Lands", "#8b4513"
                )
            )
            button_layout.addWidget(button)

        if button_layout.count() > 0:
            button_widget = QWidget()
            button_widget.setLayout(button_layout)
            self.chart_layout.addWidget(button_widget)

    def _export_single_category(self, cards, category_name, color_hex):
        try:
            if not cards:
                QMessageBox.information(
                    self, "Export Info", f"No {category_name} cards to export."
                )
                return

            if hasattr(self, "last_analysis_data") and self.last_analysis_data:
                set_codes = self.last_analysis_data.get(
                    "set_codes", [self.last_analysis_data.get("set_code", "")]
                )
                if len(set_codes) == 1:
                    base_filename = f"{set_codes[0]}_{category_name.lower()}"
                else:
                    base_filename = (
                        f"combined_{len(set_codes)}_sets_{category_name.lower()}"
                    )
            else:
                base_filename = f"analysis_{category_name.lower()}"

            filename = f"{base_filename}.csv"
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                f"Save {category_name} Analysis",
                filename,
                "CSV Files (*.csv);All Files (*.*)",
            )
            if not filepath:
                return

            self._export_color_breakdown(filepath, cards, category_name, color_hex)

            QMessageBox.information(
                self,
                "Export Successful",
                f"{category_name} analysis exported to:\n{filepath}",
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export {category_name} results:\n\n{str(e)}",
            )
