import csv
from PyQt6.QtCore import pyqtSignal, QThread, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox, QGroupBox, QFileDialog, QMessageBox, QProgressBar, QTextEdit, QSplitter, QDialog
from api.mtgjson_api import MTGJsonAPI
from ui.debug_logger import AnalyzerTabDebugger, DebugLevel, DebugManager
from ui.sorter_tab import ManaBoxSorterTab
from ui.status_manager import StatusAwareMixin
from workers.threads import SetAnalysisWorker, WorkerManager

class SetAnalyzerTab(QWidget, StatusAwareMixin):
    RARITY_COLORS = {'common': '#9a9a9a', 'uncommon': '#c0c0c0', 'rare': '#d4af37', 'mythic': '#ff6600'}
    SET_COLORS = ['#007acc', '#ff6600', '#00cc66', '#cc0066', '#6600cc', '#cc6600', '#0066cc', '#cc0000', '#00cccc', '#cccc00']
    operation_started = pyqtSignal(str, int)
    operation_finished = pyqtSignal()
    progress_updated = pyqtSignal(int)

    def __init__(self, api: MTGJsonAPI, sorter_tab: 'ManaBoxSorterTab'):
        super().__init__()
        self.api = api
        self.sorter_tab = sorter_tab
        self.worker_manager = WorkerManager()
        self.analysis_thread = None
        self.analysis_worker = None
        self.last_analysis_data = None
        self.options: dict = {}
        self.canvas = None
        self.ax = None
        self.toolbar = None
        self.toolbar_layout = None
        self.maximized_dialog = None
        self.debugger = DebugManager.get_analyzer_debugger()
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        controls_group = QGroupBox('Analysis Options')
        controls_layout = QVBoxLayout(controls_group)
        splitter.addWidget(controls_group)
        chart_container = QWidget()
        chart_container_layout = QVBoxLayout(chart_container)
        chart_container_layout.setContentsMargins(0, 0, 0, 0)
        chart_header = QHBoxLayout()
        chart_title = QLabel('Analysis Results')
        chart_title.setStyleSheet('font-weight: bold; font-size: 12px;')
        chart_header.addWidget(chart_title)
        chart_header.addStretch()
        self.maximize_button = QPushButton(' Maximize')
        self.maximize_button.setToolTip('Maximize chart view (Escape to exit)')
        self.maximize_button.setMaximumWidth(120)
        self.maximize_button.clicked.connect(self._toggle_maximize_chart)
        chart_header.addWidget(self.maximize_button)
        chart_container_layout.addLayout(chart_header)
        self.chart_layout = QVBoxLayout()
        chart_container_layout.addLayout(self.chart_layout)
        splitter.addWidget(chart_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        self._create_controls(controls_layout)

    def _create_controls(self, layout):
        grid = QGridLayout()
        self.set_code_edit = QLineEdit()
        self.set_code_edit.setPlaceholderText("e.g., 'mh3' or 'mh3,ltr,dmu' for multiple sets")
        self.set_code_edit.setToolTip(
            'Enter Magic set code(s) to analyze\n\n'
            'Single set: mh3\n'
            'Multiple sets: mh3,ltr,dmu\n\n'
            '💡 Pro tip: Analyze related sets together for complete product coverage:\n'
            '  • Main set + special inserts (e.g., "spm,mar")\n'
            '  • Draft + collector variants (e.g., "neo,nec")\n'
            '  • Universes Beyond products\n\n'
            'This ensures all cards from the same booster box are included.'
        )
        self.subtract_owned_check = QCheckBox('Subtract Owned Cards (from Collection)')
        self.subtract_owned_check.setToolTip('Exclude owned cards from analysis')
        self.weighted_check = QCheckBox('Weighted Analysis')
        self.weighted_check.setToolTip('Weight cards by rarity or booster probability')
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(['default', 'play_booster', 'dynamic'])
        self.preset_combo.setToolTip(
            'Weight preset for Weighted Analysis:\n\n'
            '• default: Standard rarity weights (mythic=10, rare=3, uncommon=1, common=0.25)\n'
            '  Use for: Any set, quick analysis\n\n'
            '• play_booster: Actual booster probabilities from MTGJSON data\n'
            '  Use for: Sets with booster data (most standard sets)\n'
            '  Supports multi-set analysis with automatic fallback\n\n'
            '• dynamic: Balanced rarity weights (mythic=8, rare=4, uncommon=1.5, common=0.5)\n'
            '  Use for: Sets without booster data (Commander, special products)\n\n'
            '💡 If play_booster fails, switch to default or dynamic preset'
        )
        self.group_check = QCheckBox('Group low count letters')
        self.group_check.setChecked(True)
        self.group_check.setToolTip('Combine letters with few cards')
        self.threshold_edit = QLineEdit('20')
        self.threshold_edit.setToolTip('Minimum cards for grouping')
        self.color_by_combo = QComboBox()
        self.color_by_combo.addItems(['None', 'Rarity', 'Set', 'WUBRG Colors', 'Card Type'])
        self.color_by_combo.setToolTip('Choose chart coloring')
        self.export_check = QCheckBox('Export to CSV on run')
        self.export_check.setToolTip('Auto-save results to CSV')
        grid.addWidget(QLabel('Set Code:'), 0, 0)
        grid.addWidget(self.set_code_edit, 0, 1)

        # Add helpful hint label
        hint_label = QLabel('💡 Tip: Analyze related sets together (e.g., "spm,spe,mar")')
        hint_label.setStyleSheet('color: #888; font-size: 9pt; font-style: italic;')
        hint_label.setWordWrap(True)
        grid.addWidget(hint_label, 1, 0, 1, 2)

        grid.addWidget(self.subtract_owned_check, 2, 0, 1, 2)
        grid.addWidget(self.weighted_check, 3, 0, 1, 2)
        grid.addWidget(QLabel('Weight Preset:'), 4, 0)
        grid.addWidget(self.preset_combo, 4, 1)
        grid.addWidget(self.group_check, 5, 0, 1, 2)
        grid.addWidget(QLabel('Min group total:'), 6, 0)
        grid.addWidget(self.threshold_edit, 6, 1)
        grid.addWidget(QLabel('Color Code By:'), 7, 0)
        grid.addWidget(self.color_by_combo, 7, 1)
        spacer_label = QLabel('')
        spacer_label.setMinimumHeight(10)
        grid.addWidget(spacer_label, 8, 0, 1, 2)
        separator = QLabel('' * 30)
        separator.setStyleSheet('color: #666;')
        grid.addWidget(separator, 8, 0, 1, 2)
        export_label = QLabel('Export Options:')
        export_label.setStyleSheet('font-weight: bold; color: #00aaff; font-size: 12px;')
        grid.addWidget(export_label, 9, 0)
        grid.addWidget(self.export_check, 10, 0, 1, 2)
        for widget in (self.weighted_check, self.group_check, self.preset_combo, self.threshold_edit, self.color_by_combo):
            if isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self.redraw_chart)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.redraw_chart)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self.redraw_chart)
        layout.addLayout(grid)
        layout.addStretch()
        self.run_button = QPushButton('Run Analysis')
        self.run_button.setObjectName('AccentButton')
        self.run_button.setToolTip('Start analysis (Ctrl+R)')
        self.run_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.run_button)
        self.status_label = QLabel('Enter a set code to begin analysis.')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.cancel_button = QPushButton('Cancel Analysis')
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
        matplotlib.use('QtAgg')
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
        from matplotlib.figure import Figure
        try:
            screen_dpi = self.screen().logicalDotsPerInch()
            fig_dpi = min(screen_dpi * 0.8, 100)
        except:
            fig_dpi = 80
        fig = Figure(facecolor='#2b2b2b', constrained_layout=False, dpi=fig_dpi)
        self.canvas = FigureCanvas(fig)
        self.canvas.setMinimumSize(400, 300)
        self.canvas.setSizePolicy(self.canvas.sizePolicy().horizontalPolicy(), self.canvas.sizePolicy().verticalPolicy())
        self.canvas.updateGeometry()
        self.ax = self.canvas.figure.subplots()
        self.ax.tick_params(colors='white')
        for spine in self.ax.spines.values():
            spine.set_color('white')
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setObjectName('qt_toolbar_navigation')
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.addWidget(self.toolbar)
        self.toolbar_layout.addStretch()
        zoom_hint = QLabel(' Use toolbar to pan/zoom')
        zoom_hint.setStyleSheet('color: #888; font-size: 10px;')
        self.toolbar_layout.addWidget(zoom_hint)
        layout.addLayout(self.toolbar_layout)
        layout.addWidget(self.canvas, 1)

    def run_analysis(self):
        self._create_chart_area(self.chart_layout)
        set_input = self.set_code_edit.text().strip().lower()
        if not set_input:
            QMessageBox.information(self, 'Missing Set Code', 'Please enter a set code to analyze.\n\nExamples: mh3, ltr, dmu, neo\nMultiple sets: mh3,ltr,dmu')
            self.set_code_edit.setFocus()
            return
        set_codes = [code.strip() for code in set_input.split(',')]
        set_codes = [code for code in set_codes if code]
        if not set_codes:
            QMessageBox.information(self, 'Invalid Set Codes', 'Please enter valid set codes to analyze.')
            self.set_code_edit.setFocus()
            return
        invalid_codes = []
        for set_code in set_codes:
            if len(set_code) < 2 or len(set_code) > 6:
                invalid_codes.append(set_code)
        if invalid_codes:
            reply = QMessageBox.question(self, 'Unusual Set Codes', f"These set codes don't look typical: {', '.join(invalid_codes)}\n\nMost set codes are 3-4 characters (e.g., 'mh3', 'ltr').\n\nDo you want to continue anyway?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return
        try:
            threshold = float(self.threshold_edit.text())
            if threshold < 1:
                QMessageBox.warning(self, 'Invalid Threshold', 'Minimum group total must be at least 1.')
                self.threshold_edit.setFocus()
                return
        except ValueError:
            QMessageBox.warning(self, 'Invalid Number', 'Please enter a valid number for the minimum group total.')
            self.threshold_edit.setFocus()
            return
        owned_cards = None
        if self.subtract_owned_check.isChecked():
            if not self.sorter_tab.all_cards:
                reply = QMessageBox.question(self, 'No Collection Loaded', "You've chosen to subtract owned cards, but no collection is loaded in the Sorter tab.\n\nDo you want to:\n• Continue without subtracting owned cards, or\n• Cancel and load a collection first?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                else:
                    self.subtract_owned_check.setChecked(False)
            else:
                owned_cards = self.sorter_tab.all_cards
        self.options = {'set_codes': set_codes, 'weighted': self.weighted_check.isChecked(), 'preset': self.preset_combo.currentText(), 'group': self.group_check.isChecked(), 'threshold': threshold, 'owned_cards': owned_cards}
        if self.export_check.isChecked():
            if len(set_codes) == 1:
                filename = f'{set_codes[0]}_analysis.csv'
            else:
                filename = f'combined_{len(set_codes)}_sets_analysis.csv'
            filepath, _ = QFileDialog.getSaveFileName(self, 'Save Analysis CSV', filename, 'CSV Files (*.csv);All Files (*.*)')
            if not filepath:
                return
            self.options['export_path'] = filepath
        self._start_analysis()

    def _start_analysis(self):
        self.run_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.results_summary.setVisible(False)
        set_codes = self.options['set_codes']
        if len(set_codes) == 1:
            set_display = set_codes[0].upper()
            self.show_status_message(f"Starting analysis for '{set_display}'...", style='info')
            self.operation_started.emit(f'Analyzing set {set_display}', 0)
        else:
            set_display = ', '.join((code.upper() for code in set_codes))
            self.show_status_message(f'Starting analysis for {len(set_codes)} sets: {set_display}...', style='info')
            self.operation_started.emit(f'Analyzing {len(set_codes)} sets', 0)
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
        self.show_status_message(message, style='info')

    def cleanup_workers(self):
        """Clean up all worker threads before shutdown."""
        try:
            if self.analysis_worker and hasattr(self.analysis_worker, 'cancel'):
                self.analysis_worker.cancel()
        except Exception as e:
            print(f'Error canceling analysis worker: {e}')

        try:
            self.worker_manager.cleanup_all()
        except Exception as e:
            print(f'Error cleaning up worker manager: {e}')

        try:
            if self.analysis_thread and self.analysis_thread.isRunning():
                self.analysis_thread.quit()
                if not self.analysis_thread.wait(2000):
                    print('Warning: Analysis thread did not stop gracefully')
                    self.analysis_thread.terminate()
                    self.analysis_thread.wait(1000)
        except Exception as e:
            print(f'Error cleaning up analysis thread: {e}')

    def cancel_analysis(self):
        self.worker_manager.cleanup_all()
        if self.analysis_thread and self.analysis_thread.isRunning():
            from workers.threads import cleanup_worker_thread
            cleanup_worker_thread(self.analysis_thread, self.analysis_worker)
        self._reset_ui_state()
        self.show_status_message('Analysis cancelled.', style='warning')
        self.operation_finished.emit()

    def on_analysis_finished(self, result):
        set_codes = result.get('set_codes', [result.get('set_code', '')])
        if len(set_codes) == 1:
            set_code_str = f"'{set_codes[0].upper()}'"
        else:
            set_code_str = f"{len(set_codes)} sets: {', '.join((code.upper() for code in set_codes))}"
        summary_parts = [f'Analysis completed for {set_code_str}']
        if 'missing_count' in result:
            owned = result.get('owned_count', 0)
            missing = result.get('missing_count', 0)
            total = result.get('original_set_size', owned + missing)
            summary_parts.append(f'Set contains {total} cards total')
            summary_parts.append(f'You own {owned} cards ({owned / total * 100:.1f}%)')
            summary_parts.append(f'Missing {missing} cards ({missing / total * 100:.1f}%)')
            set_code_str += ' (Missing Cards Only)'
        else:
            total = result.get('total_cards_analyzed', 0)
            summary_parts.append(f'Analyzed {total} cards')
        if result['weighted']:
            summary_parts.append('Weighted analysis using ' + self.options['preset'] + ' preset')
        summary_text = '\n'.join(summary_parts)
        self.show_status_message(f'Analysis complete for {set_code_str}', style='success')
        self.results_summary.setText(summary_text)
        self.results_summary.setVisible(True)
        self._reset_ui_state()
        self.last_analysis_data = result
        self.last_analysis_cards = result.get('raw_cards', [])
        self.redraw_chart()
        if (export_path := self.analysis_worker.options.get('export_path')):
            self._export_results(export_path, result)
        self.operation_finished.emit()

    def on_analysis_error(self, error_message: str):
        self.show_status_message('Analysis failed - see details below', style='error')
        self._reset_ui_state()
        self.results_summary.setText(f'Error: {error_message}')
        self.results_summary.setVisible(True)
        if any((term in error_message.lower() for term in ['not found', 'invalid', 'connection'])):
            QMessageBox.warning(self, 'Analysis Failed', error_message)
        self.operation_finished.emit()

    def _reset_ui_state(self):
        self.run_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.progress_bar.setVisible(False)

    def _export_results(self, export_path: str, result: dict):
        try:
            if not result['sorted_groups']:
                QMessageBox.information(self, 'Export Info', 'No data to export.')
                return
            if self.color_by_combo.currentText() == 'WUBRG Colors' and hasattr(self, 'last_analysis_cards') and self.last_analysis_cards:
                self._export_wubrg_to_csv(export_path, result)
            else:
                weighted = result['weighted']
                flat_results = [(group, data['total_weighted' if weighted else 'total_raw']) for group, data in result['sorted_groups']]
                with open(export_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Letter Group', 'Count'])
                    writer.writerows(flat_results)
            QMessageBox.information(self, 'Export Successful', f'Analysis results exported to:\n{export_path}')
        except PermissionError:
            QMessageBox.critical(self, 'Export Failed', f"Cannot write to '{export_path}'.\n\nThe file may be open in another program or you may not have write permissions.")
        except Exception as e:
            QMessageBox.critical(self, 'Export Error', f'Failed to export results:\n\n{str(e)}')

    def _export_wubrg_to_csv(self, filepath: str, result: dict):
        try:
            wubrg_colors = {'W': {'name': 'White', 'color': '#f0f0f0'}, 'U': {'name': 'Blue', 'color': '#007acc'}, 'B': {'name': 'Black', 'color': '#808080'}, 'R': {'name': 'Red', 'color': '#cc0000'}, 'G': {'name': 'Green', 'color': '#00cc66'}}
            letter_mapping = self._extract_letter_grouping_from_data(result)
            single_color_groups: dict = {color: [] for color in wubrg_colors.keys()}
            multicolor_cards = []
            colorless_cards = []
            land_cards = []
            for card_data in self.last_analysis_cards:
                color_identity = card_data.get('colorIdentity', [])
                card_type = card_data.get('type', '').lower()
                if 'land' in card_type:
                    land_cards.append(card_data)
                elif not color_identity:
                    colorless_cards.append(card_data)
                elif len(color_identity) == 1:
                    single_color_groups[color_identity[0]].append(card_data)
                else:
                    multicolor_cards.append(card_data)
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Color Category', 'Color Hex', 'Letter', 'Count', 'Percentage'])
                all_categories = []
                for color_code, color_info in wubrg_colors.items():
                    if single_color_groups[color_code]:
                        all_categories.append((color_info['name'], color_info['color'], single_color_groups[color_code]))
                if multicolor_cards:
                    all_categories.append(('Multicolor', '#ff6600', multicolor_cards))
                if colorless_cards:
                    all_categories.append(('Colorless', '#9a9a9a', colorless_cards))
                if land_cards:
                    all_categories.append(('Lands', '#8b4513', land_cards))
                for category_name, color_hex, cards in all_categories:
                    letter_counts = {}
                    for card_data in cards:
                        card_name = card_data.get('name', '')
                        if not card_name:
                            continue
                        first_letter = card_name[0].upper()
                        grouped_letter = letter_mapping.get(first_letter, first_letter)
                        if grouped_letter not in letter_counts:
                            letter_counts[grouped_letter] = 0
                        letter_counts[grouped_letter] += 1
                    sorted_letters = sorted(letter_counts.items(), key=lambda x: x[1], reverse=True)
                    total_cards = sum((count for _, count in sorted_letters))
                    for letter, count in sorted_letters:
                        percentage = count / total_cards * 100 if total_cards > 0 else 0
                        writer.writerow([category_name, color_hex, letter, count, f'{percentage:.1f}%'])
        except Exception as e:
            QMessageBox.critical(self, 'WUBRG Export Error', f'Failed to export WUBRG results:\n\n{str(e)}')

    def redraw_chart(self, force_recreate=False):
        if self.last_analysis_data is None:
            return
        if not self.ax:
            return
        data = self.last_analysis_data
        color_mode = self.color_by_combo.currentText()
        labels = [item[0] for item in data['sorted_groups']] if data['sorted_groups'] else []
        current_chart_key = (tuple(labels), color_mode, data.get('weighted', False))
        need_recreate = force_recreate or not hasattr(self, '_last_chart_key') or self._last_chart_key != current_chart_key or (color_mode == 'WUBRG Colors')
        if need_recreate:
            self._last_chart_key = current_chart_key
            self.ax.clear()
            for attr in ['_chart_bars', '_chart_texts', '_rarity_bars', '_set_bars', '_set_texts', '_multiset_bars']:
                if hasattr(self, attr):
                    delattr(self, attr)
        if not data['sorted_groups']:
            self.ax.text(0.5, 0.5, 'No cards to display.\n(You might own the entire set!)', ha='center', va='center', color='white', fontsize=12, transform=self.ax.transAxes)
            set_codes = data.get('set_codes', [data.get('set_code', '')])
            if len(set_codes) == 1:
                title = f'Card Distribution for Set: {set_codes[0].upper()}'
            else:
                title = f"Card Distribution for {len(set_codes)} Sets: {', '.join((code.upper() for code in set_codes))}"
            if 'missing_count' in data:
                title += ' (Missing Cards)'
            self.ax.set_title(title, color='white')
            self.canvas.draw_idle()
            return
        if color_mode == 'WUBRG Colors':
            self._create_wubrg_charts(data)
            return
        elif color_mode == 'Card Type':
            self._create_card_type_charts(data)
            return
        elif color_mode == 'None':
            self._update_simple_chart(data, labels, need_recreate)
        elif color_mode == 'Set':
            self._create_set_colored_chart(data, labels, need_recreate)
        else:
            self._update_rarity_chart(data, labels, need_recreate)
        set_codes = data.get('set_codes', [data.get('set_code', '')])
        if len(set_codes) == 1:
            title = f'Card Distribution for Set: {set_codes[0].upper()}'
        else:
            title = f"Card Distribution for {len(set_codes)} Sets: {', '.join((code.upper() for code in set_codes))}"
        if 'missing_count' in data:
            title += ' (Missing Cards Only)'
        self.ax.set_title(title, color='white', fontsize=12, pad=20)
        ylabel = 'Count'
        if data['weighted']:
            ylabel = f"Weighted Score ({self.options.get('preset', 'default')} preset)"
        self.ax.set_ylabel(ylabel, color='white')
        self.ax.tick_params(colors='white')
        for spine in self.ax.spines.values():
            spine.set_color('white')
        if len(labels) > 10:
            self.ax.tick_params(axis='x', rotation=45)
            for label in self.ax.get_xticklabels():
                label.set_ha('right')
            self.canvas.figure.subplots_adjust(bottom=0.2)
        self.canvas.figure.tight_layout()
        self.canvas.draw_idle()

    def _update_simple_chart(self, data, labels, need_recreate):
        values = [item[1]['total_weighted' if data['weighted'] else 'total_raw'] for item in data['sorted_groups']]
        if need_recreate or not hasattr(self, '_chart_bars'):
            self._chart_bars = self.ax.bar(labels, values, color='#007acc')
            self._chart_texts = []
            for bar, value in zip(self._chart_bars, values):
                if value > 0:
                    text = self.ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01, str(int(value)), ha='center', va='bottom', color='white', fontsize=8)
                    self._chart_texts.append(text)
        else:
            max_val = max(values) if values else 1
            for bar, value in zip(self._chart_bars, values):
                bar.set_height(value)
            text_idx = 0
            for bar, value in zip(self._chart_bars, values):
                if value > 0:
                    if text_idx < len(self._chart_texts):
                        text = self._chart_texts[text_idx]
                        text.set_position((bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.01))
                        text.set_text(str(int(value)))
                        text_idx += 1
            self.ax.relim()
            self.ax.autoscale_view()

    def _update_rarity_chart(self, data, labels, need_recreate):
        all_rarities = sorted(list(self.RARITY_COLORS.keys()))
        if need_recreate or not hasattr(self, '_rarity_bars'):
            bottoms = {label: 0 for label in labels}
            self._rarity_bars = {}
            for rarity in all_rarities:
                values = [item[1]['rarity'].get(rarity, 0) for item in data['sorted_groups']]
                bars = self.ax.bar(labels, values, bottom=[bottoms[label] for label in labels], color=self.RARITY_COLORS.get(rarity, '#ffffff'), label=rarity.title())
                self._rarity_bars[rarity] = bars
                for i, label in enumerate(labels):
                    bottoms[label] += values[i]
            self.ax.legend(labelcolor='white', facecolor='#3c3f41', edgecolor='#555', loc='upper right')
        else:
            bottoms = {label: 0 for label in labels}
            for rarity in all_rarities:
                values = [item[1]['rarity'].get(rarity, 0) for item in data['sorted_groups']]
                bars = self._rarity_bars.get(rarity)
                if bars:
                    bottom_list = [bottoms[label] for label in labels]
                    for bar, value, bottom in zip(bars, values, bottom_list):
                        bar.set_height(value)
                        bar.set_y(bottom)
                    for i, label in enumerate(labels):
                        bottoms[label] += values[i]
            self.ax.relim()
            self.ax.autoscale_view()

    def _create_set_colored_chart(self, data, labels, need_recreate=True):
        set_codes = data.get('set_codes', [])
        if len(set_codes) <= 1:
            values = [item[1]['total_weighted' if data['weighted'] else 'total_raw'] for item in data['sorted_groups']]
            if need_recreate or not hasattr(self, '_set_bars'):
                self._set_bars = self.ax.bar(labels, values, color=self.SET_COLORS[0])
                self._set_texts = []
                for bar, value in zip(self._set_bars, values):
                    if value > 0:
                        text = self.ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01, str(int(value)), ha='center', va='bottom', color='white', fontsize=8)
                        self._set_texts.append(text)
            else:
                max_val = max(values) if values else 1
                for bar, value in zip(self._set_bars, values):
                    bar.set_height(value)
                text_idx = 0
                for bar, value in zip(self._set_bars, values):
                    if value > 0:
                        if text_idx < len(self._set_texts):
                            text = self._set_texts[text_idx]
                            text.set_position((bar.get_x() + bar.get_width() / 2, bar.get_height() + max_val * 0.01))
                            text.set_text(str(int(value)))
                            text_idx += 1
                self.ax.relim()
                self.ax.autoscale_view()
            return
        set_colors = {set_code: self.SET_COLORS[i % len(self.SET_COLORS)] for i, set_code in enumerate(set_codes)}
        if need_recreate or not hasattr(self, '_multiset_bars'):
            bottoms = {label: 0 for label in labels}
            legend_handles = []
            self._multiset_bars = {}
            for set_code in set_codes:
                values = []
                for item in data['sorted_groups']:
                    set_breakdown = item[1].get('set_breakdown', {})
                    values.append(set_breakdown.get(set_code, 0))
                if any((v > 0 for v in values)):
                    bars = self.ax.bar(labels, values, bottom=[bottoms[label] for label in labels], color=set_colors[set_code], label=set_code.upper())
                    self._multiset_bars[set_code] = bars
                    for i, label in enumerate(labels):
                        bottoms[label] += values[i]
                    if bars:
                        legend_handles.append(bars[0])
            if legend_handles:
                self.ax.legend(handles=legend_handles, labels=[set_code.upper() for set_code in set_codes if any((item[1].get('set_breakdown', {}).get(set_code, 0) > 0 for item in data['sorted_groups']))], labelcolor='white', facecolor='#3c3f41', edgecolor='#555', loc='upper right')
        else:
            bottoms = {label: 0 for label in labels}
            for set_code in set_codes:
                values = []
                for item in data['sorted_groups']:
                    set_breakdown = item[1].get('set_breakdown', {})
                    values.append(set_breakdown.get(set_code, 0))
                bars = self._multiset_bars.get(set_code)
                if bars and any((v > 0 for v in values)):
                    bottom_list = [bottoms[label] for label in labels]
                    for bar, value, bottom in zip(bars, values, bottom_list):
                        bar.set_height(value)
                        bar.set_y(bottom)
                    for i, label in enumerate(labels):
                        bottoms[label] += values[i]
            self.ax.relim()
            self.ax.autoscale_view()

    def _extract_letter_grouping_from_data(self, data):
        letter_mapping = {}
        if not data.get('sorted_groups'):
            return letter_mapping
        for group_name, group_data in data['sorted_groups']:
            if group_name.startswith('(') and group_name.endswith(')'):
                letters = group_name[1:-1]
                for letter in letters:
                    letter_mapping[letter] = group_name
            elif group_name.startswith('Group ') and '(' in group_name:
                letters = group_name.split('(')[1].rstrip(')')
                for letter in letters:
                    letter_mapping[letter] = group_name
            elif len(group_name) > 1 and all((c.isalpha() for c in group_name)):
                for letter in group_name:
                    letter_mapping[letter] = group_name
            else:
                letter_mapping[group_name] = group_name
        return letter_mapping

    def _create_wubrg_charts(self, data):
        self._create_wubrg_charts_impl(data)

    def _create_wubrg_charts_impl(self, data):
        wubrg_colors = {'W': {'name': 'White', 'color': '#f0f0f0'}, 'U': {'name': 'Blue', 'color': '#007acc'}, 'B': {'name': 'Black', 'color': '#808080'}, 'R': {'name': 'Red', 'color': '#cc0000'}, 'G': {'name': 'Green', 'color': '#00cc66'}}
        self.ax.clear()
        if not hasattr(self, 'last_analysis_cards') or not self.last_analysis_cards:
            self.ax.text(0.5, 0.5, 'WUBRG analysis requires card data.\nPlease re-run the analysis.', ha='center', va='center', color='white', fontsize=14, weight='bold', transform=self.ax.transAxes)
            self.canvas.draw_idle()
            return
        letter_mapping = self._extract_letter_grouping_from_data(data)
        single_color_groups = {color: [] for color in wubrg_colors.keys()}
        multicolor_cards = []
        colorless_cards = []
        land_cards = []
        for card_data in self.last_analysis_cards:
            color_identity = card_data.get('colorIdentity', [])
            card_type = card_data.get('type', '').lower()
            if 'land' in card_type:
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
                charts_to_create.append(('single', color_code, color_info, single_color_groups[color_code]))
        if multicolor_cards:
            charts_to_create.append(('multicolor', None, {'name': 'Multicolor', 'color': '#ff6600'}, multicolor_cards))
        if colorless_cards:
            charts_to_create.append(('colorless', None, {'name': 'Colorless', 'color': '#9a9a9a'}, colorless_cards))
        if land_cards:
            charts_to_create.append(('lands', None, {'name': 'Lands', 'color': '#8b4513'}, land_cards))
        if not charts_to_create:
            self.ax.text(0.5, 0.5, 'No cards to display in WUBRG analysis.', ha='center', va='center', color='white', fontsize=14, weight='bold', transform=self.ax.transAxes)
            self.canvas.draw_idle()
            return
        num_charts = len(charts_to_create)
        if num_charts <= 4:
            rows, cols = (2, 2)
        elif num_charts <= 6:
            rows, cols = (2, 3)
        elif num_charts <= 9:
            rows, cols = (3, 3)
        else:
            rows, cols = (4, 3)
        gs = fig.add_gridspec(rows, cols, hspace=0.9, wspace=0.5, bottom=0.18, top=0.84)
        for i, (chart_type, color_code, color_info, cards) in enumerate(charts_to_create):
            if i >= rows * cols:
                break
            row = i // cols
            col = i % cols
            ax = fig.add_subplot(gs[row, col])
            letter_counts = {}
            for card_data in cards:
                card_name = card_data.get('name', '')
                if not card_name:
                    continue
                first_letter = card_name[0].upper()
                grouped_letter = letter_mapping.get(first_letter, first_letter)
                if grouped_letter not in letter_counts:
                    letter_counts[grouped_letter] = 0
                letter_counts[grouped_letter] += 1
            if not letter_counts:
                ax.text(0.5, 0.5, f"No valid {color_info['name']} card names", ha='center', va='center', color='white', fontsize=11, weight='bold', transform=ax.transAxes)
                ax.set_title(f"{color_info['name']} Cards", color='white', fontsize=14, pad=10, weight='bold')
                ax.set_facecolor('#2b2b2b')
                continue
            sorted_letters = sorted(letter_counts.items(), key=lambda x: x[1], reverse=True)
            letters, counts = zip(*sorted_letters)
            bars = ax.bar(letters, counts, color=color_info['color'])
            for bar, count in zip(bars, counts):
                if count > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(counts) * 0.01, str(count), ha='center', va='bottom', color='white', fontsize=10, weight='bold')
            ax.set_title(f"{color_info['name']} ({len(cards)})", color='white', fontsize=14, pad=10, weight='bold')
            ax.set_ylabel('Count', color='white', fontsize=11, weight='bold')
            ax.set_facecolor('#2b2b2b')
            ax.tick_params(axis='y', labelsize=10, colors='white')
            for label in ax.get_yticklabels():
                label.set_fontweight('bold')
            if len(letters) > 15:
                ax.tick_params(axis='x', rotation=45, labelsize=9, colors='white', pad=3)
                for label in ax.get_xticklabels():
                    label.set_ha('right')
                    label.set_va('top')
                    label.set_fontweight('bold')
            elif len(letters) > 10:
                ax.tick_params(axis='x', rotation=45, labelsize=10, colors='white', pad=3)
                for label in ax.get_xticklabels():
                    label.set_ha('right')
                    label.set_va('top')
                    label.set_fontweight('bold')
            elif len(letters) > 6:
                ax.tick_params(axis='x', rotation=45, labelsize=11, colors='white', pad=3)
                for label in ax.get_xticklabels():
                    label.set_ha('right')
                    label.set_va('top')
                    label.set_fontweight('bold')
            else:
                ax.tick_params(colors='white', labelsize=11)
                for label in ax.get_xticklabels():
                    label.set_fontweight('bold')
            for spine in ax.spines.values():
                spine.set_color('white')
                spine.set_linewidth(1.5)
        set_codes = data.get('set_codes', [data.get('set_code', '')])
        if len(set_codes) == 1:
            title = f'WUBRG Analysis: {set_codes[0].upper()}'
        else:
            title = f"WUBRG Analysis: {len(set_codes)} Sets ({', '.join((code.upper() for code in set_codes))})"
        if 'missing_count' in data:
            title += ' - Missing Only'
        fig.suptitle(title, color='white', fontsize=16, y=0.96, weight='bold')
        self.canvas.draw_idle()
        if hasattr(self, 'last_analysis_cards') and self.last_analysis_cards and (self.color_by_combo.currentText() == 'WUBRG Colors'):
            self._add_wubrg_export_buttons()

    def _export_wubrg_results(self, result):
        try:
            if not hasattr(self, 'last_analysis_cards') or not self.last_analysis_cards:
                QMessageBox.information(self, 'Export Info', 'No WUBRG data to export.')
                return
            set_codes = result.get('set_codes', [result.get('set_code', '')])
            if len(set_codes) == 1:
                base_filename = f'{set_codes[0]}_wubrg'
            else:
                base_filename = f'combined_{len(set_codes)}_sets_wubrg'
            export_dir = QFileDialog.getExistingDirectory(self, 'Select Directory for WUBRG Export', '')
            if not export_dir:
                return
            letter_mapping = self._extract_letter_grouping_from_data(result)
            wubrg_colors = {'W': {'name': 'White', 'color': '#f0f0f0'}, 'U': {'name': 'Blue', 'color': '#007acc'}, 'B': {'name': 'Black', 'color': '#808080'}, 'R': {'name': 'Red', 'color': '#cc0000'}, 'G': {'name': 'Green', 'color': '#00cc66'}}
            single_color_groups: dict = {color: [] for color in wubrg_colors.keys()}
            multicolor_cards = []
            colorless_cards = []
            land_cards = []
            for card_data in self.last_analysis_cards:
                color_identity = card_data.get('colorIdentity', [])
                card_type = card_data.get('type', '').lower()
                if 'land' in card_type:
                    land_cards.append(card_data)
                elif not color_identity:
                    colorless_cards.append(card_data)
                elif len(color_identity) == 1:
                    single_color_groups[color_identity[0]].append(card_data)
                else:
                    multicolor_cards.append(card_data)
            exported_files = []
            for color_code, color_info in wubrg_colors.items():
                if single_color_groups[color_code]:
                    filename = f"{base_filename}_{color_info['name'].lower()}.csv"
                    filepath = f'{export_dir}/{filename}'
                    self._export_color_breakdown(filepath, single_color_groups[color_code], color_info['name'], color_info['color'], letter_mapping)
                    exported_files.append(filename)
            if multicolor_cards:
                filename = f'{base_filename}_multicolor.csv'
                filepath = f'{export_dir}/{filename}'
                self._export_color_breakdown(filepath, multicolor_cards, 'Multicolor', '#ff6600', letter_mapping)
                exported_files.append(filename)
            if colorless_cards:
                filename = f'{base_filename}_colorless.csv'
                filepath = f'{export_dir}/{filename}'
                self._export_color_breakdown(filepath, colorless_cards, 'Colorless', '#9a9a9a', letter_mapping)
                exported_files.append(filename)
            if land_cards:
                filename = f'{base_filename}_lands.csv'
                filepath = f'{export_dir}/{filename}'
                self._export_color_breakdown(filepath, land_cards, 'Lands', '#8b4513', letter_mapping)
                exported_files.append(filename)
            summary_filename = f'{base_filename}_summary.csv'
            summary_filepath = f'{export_dir}/{summary_filename}'
            self._export_wubrg_summary(summary_filepath, {**{color_info['name']: single_color_groups[color_code] for color_code, color_info in wubrg_colors.items() if single_color_groups[color_code]}, **({'Multicolor': multicolor_cards} if multicolor_cards else {}), **({'Colorless': colorless_cards} if colorless_cards else {}), **({'Lands': land_cards} if land_cards else {})}, letter_mapping)
            exported_files.append(summary_filename)
            if exported_files:
                QMessageBox.information(self, 'WUBRG Export Successful', f'WUBRG analysis exported to {len(exported_files)} files:\n\n' + '\n'.join(exported_files) + f'\n\nLocation: {export_dir}')
            else:
                QMessageBox.information(self, 'Export Info', 'No WUBRG data to export.')
        except Exception as e:
            QMessageBox.critical(self, 'WUBRG Export Error', f'Failed to export WUBRG results:\n\n{str(e)}')

    def _export_color_breakdown(self, filepath, cards, color_name, color_hex, letter_mapping=None):
        if letter_mapping is None:
            letter_mapping = {}
        letter_counts = {}
        for card_data in cards:
            card_name = card_data.get('name', '')
            if not card_name:
                continue
            first_letter = card_name[0].upper()
            grouped_letter = letter_mapping.get(first_letter, first_letter)
            if grouped_letter not in letter_counts:
                letter_counts[grouped_letter] = 0
            letter_counts[grouped_letter] += 1
        sorted_letters = sorted(letter_counts.items(), key=lambda x: x[1], reverse=True)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Color Category', 'Color Hex', 'Letter', 'Count', 'Percentage'])
            total_cards = sum((count for _, count in sorted_letters))
            for letter, count in sorted_letters:
                percentage = count / total_cards * 100 if total_cards > 0 else 0
                writer.writerow([color_name, color_hex, letter, count, f'{percentage:.1f}%'])

    def _export_wubrg_summary(self, filepath, all_categories, letter_mapping=None):
        if letter_mapping is None:
            letter_mapping = {}
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Category', 'Color Hex', 'Total Cards', 'Letter Count', 'Top Letters'])
            for category_name, cards in all_categories.items():
                if not cards:
                    continue
                color_hex = {'White': '#f0f0f0', 'Blue': '#007acc', 'Black': '#808080', 'Red': '#cc0000', 'Green': '#00cc66', 'Multicolor': '#ff6600', 'Colorless': '#9a9a9a', 'Lands': '#8b4513'}.get(category_name, '#000000')
                letter_counts = {}
                for card_data in cards:
                    card_name = card_data.get('name', '')
                    if not card_name:
                        continue
                    first_letter = card_name[0].upper()
                    grouped_letter = letter_mapping.get(first_letter, first_letter)
                    if grouped_letter not in letter_counts:
                        letter_counts[grouped_letter] = 0
                    letter_counts[grouped_letter] += 1
                sorted_letters = sorted(letter_counts.items(), key=lambda x: x[1], reverse=True)
                top_letters = ', '.join([f'{letter}({count})' for letter, count in sorted_letters[:3]])
                writer.writerow([category_name, color_hex, len(cards), len(letter_counts), top_letters])

    def _create_card_type_charts(self, data):
        type_categories = {'Creature': {'keywords': ['creature'], 'color': '#00cc66'}, 'Instant': {'keywords': ['instant'], 'color': '#007acc'}, 'Sorcery': {'keywords': ['sorcery'], 'color': '#cc0000'}, 'Enchantment': {'keywords': ['enchantment'], 'color': '#9370db'}, 'Artifact': {'keywords': ['artifact'], 'color': '#808080'}, 'Planeswalker': {'keywords': ['planeswalker'], 'color': '#ff6600'}, 'Battle': {'keywords': ['battle'], 'color': '#cc00cc'}, 'Land': {'keywords': ['land'], 'color': '#8b4513'}}
        self.ax.clear()
        if not hasattr(self, 'last_analysis_cards') or not self.last_analysis_cards:
            self.ax.text(0.5, 0.5, 'Card type analysis requires card data.\nPlease re-run the analysis.', ha='center', va='center', color='white', fontsize=14, weight='bold', transform=self.ax.transAxes)
            self.canvas.draw_idle()
            return
        letter_mapping = self._extract_letter_grouping_from_data(data)
        type_groups = {type_name: [] for type_name in type_categories.keys()}
        for card_data in self.last_analysis_cards:
            card_type = card_data.get('type', '').lower()
            categorized = False
            for type_name, type_info in type_categories.items():
                if any((keyword in card_type for keyword in type_info['keywords'])):
                    type_groups[type_name].append(card_data)
                    categorized = True
                    break
        fig = self.canvas.figure
        fig.clear()
        charts_to_create = []
        for type_name, type_info in type_categories.items():
            if type_groups[type_name]:
                charts_to_create.append((type_name, type_info, type_groups[type_name]))
        if not charts_to_create:
            self.ax.text(0.5, 0.5, 'No cards to display in card type analysis.', ha='center', va='center', color='white', fontsize=14, weight='bold', transform=self.ax.transAxes)
            self.canvas.draw_idle()
            return
        num_charts = len(charts_to_create)
        if num_charts <= 4:
            rows, cols = (2, 2)
        elif num_charts <= 6:
            rows, cols = (2, 3)
        elif num_charts <= 9:
            rows, cols = (3, 3)
        else:
            rows, cols = (4, 3)
        gs = fig.add_gridspec(rows, cols, hspace=0.9, wspace=0.5, bottom=0.18, top=0.84)
        for i, (type_name, type_info, cards) in enumerate(charts_to_create):
            if i >= rows * cols:
                break
            row = i // cols
            col = i % cols
            ax = fig.add_subplot(gs[row, col])
            letter_counts = {}
            for card_data in cards:
                card_name = card_data.get('name', '')
                if not card_name:
                    continue
                first_letter = card_name[0].upper()
                grouped_letter = letter_mapping.get(first_letter, first_letter)
                if grouped_letter not in letter_counts:
                    letter_counts[grouped_letter] = 0
                letter_counts[grouped_letter] += 1
            if not letter_counts:
                ax.text(0.5, 0.5, f'No valid {type_name} card names', ha='center', va='center', color='white', fontsize=11, weight='bold', transform=ax.transAxes)
                ax.set_title(f'{type_name} Cards', color='white', fontsize=14, pad=10, weight='bold')
                ax.set_facecolor('#2b2b2b')
                continue
            sorted_letters = sorted(letter_counts.items(), key=lambda x: x[1], reverse=True)
            letters, counts = zip(*sorted_letters)
            bars = ax.bar(letters, counts, color=type_info['color'])
            for bar, count in zip(bars, counts):
                if count > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(counts) * 0.01, str(count), ha='center', va='bottom', color='white', fontsize=10, weight='bold')
            ax.set_title(f'{type_name} ({len(cards)})', color='white', fontsize=14, pad=10, weight='bold')
            ax.set_ylabel('Count', color='white', fontsize=11, weight='bold')
            ax.set_facecolor('#2b2b2b')
            ax.tick_params(axis='y', labelsize=10, colors='white')
            for label in ax.get_yticklabels():
                label.set_fontweight('bold')
            if len(letters) > 15:
                ax.tick_params(axis='x', rotation=45, labelsize=9, colors='white', pad=3)
                for label in ax.get_xticklabels():
                    label.set_ha('right')
                    label.set_va('top')
                    label.set_fontweight('bold')
            elif len(letters) > 10:
                ax.tick_params(axis='x', rotation=45, labelsize=10, colors='white', pad=3)
                for label in ax.get_xticklabels():
                    label.set_ha('right')
                    label.set_va('top')
                    label.set_fontweight('bold')
            elif len(letters) > 6:
                ax.tick_params(axis='x', rotation=45, labelsize=11, colors='white', pad=3)
                for label in ax.get_xticklabels():
                    label.set_ha('right')
                    label.set_va('top')
                    label.set_fontweight('bold')
            else:
                ax.tick_params(colors='white', labelsize=11)
                for label in ax.get_xticklabels():
                    label.set_fontweight('bold')
            for spine in ax.spines.values():
                spine.set_color('white')
                spine.set_linewidth(1.5)
        set_codes = data.get('set_codes', [data.get('set_code', '')])
        if len(set_codes) == 1:
            title = f'Card Type Analysis: {set_codes[0].upper()}'
        else:
            title = f"Card Type Analysis: {len(set_codes)} Sets ({', '.join((code.upper() for code in set_codes))})"
        if 'missing_count' in data:
            title += ' - Missing Only'
        fig.suptitle(title, color='white', fontsize=16, y=0.96, weight='bold')
        self.canvas.draw_idle()
        if hasattr(self, 'last_analysis_cards') and self.last_analysis_cards:
            self._add_card_type_export_buttons(type_groups, type_categories)

    def _add_wubrg_export_buttons(self):
        if hasattr(self, '_wubrg_button_widget') and self._wubrg_button_widget:
            self._wubrg_button_widget.deleteLater()
            self._wubrg_button_widget = None
        wubrg_colors = {'W': {'name': 'White', 'color': '#f0f0f0'}, 'U': {'name': 'Blue', 'color': '#007acc'}, 'B': {'name': 'Black', 'color': '#808080'}, 'R': {'name': 'Red', 'color': '#cc0000'}, 'G': {'name': 'Green', 'color': '#00cc66'}}
        single_color_groups = {color: [] for color in wubrg_colors.keys()}
        multicolor_cards = []
        colorless_cards = []
        land_cards = []
        for card_data in self.last_analysis_cards:
            color_identity = card_data.get('colorIdentity', [])
            card_type = card_data.get('type', '').lower()
            if 'land' in card_type:
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
                button.setObjectName('wubrg_export_button')
                button.setToolTip(f"Export {color_info['name']} cards breakdown to CSV")
                button.clicked.connect(lambda checked, cards=single_color_groups[color_code], name=color_info['name'], color=color_info['color']: self._export_single_category(cards, name, color))
                button_layout.addWidget(button)
        if multicolor_cards:
            button = QPushButton('Export Multicolor')
            button.setObjectName('wubrg_export_button')
            button.setToolTip('Export multicolor cards breakdown to CSV')
            button.clicked.connect(lambda checked, cards=multicolor_cards: self._export_single_category(cards, 'Multicolor', '#ff6600'))
            button_layout.addWidget(button)
        if colorless_cards:
            button = QPushButton('Export Colorless')
            button.setObjectName('wubrg_export_button')
            button.setToolTip('Export colorless cards breakdown to CSV')
            button.clicked.connect(lambda checked, cards=colorless_cards: self._export_single_category(cards, 'Colorless', '#9a9a9a'))
            button_layout.addWidget(button)
        if land_cards:
            button = QPushButton('Export Lands')
            button.setObjectName('wubrg_export_button')
            button.setToolTip('Export lands breakdown to CSV')
            button.clicked.connect(lambda checked, cards=land_cards: self._export_single_category(cards, 'Lands', '#8b4513'))
            button_layout.addWidget(button)
        if button_layout.count() > 0:
            self._wubrg_button_widget = QWidget()
            self._wubrg_button_widget.setLayout(button_layout)
            self.chart_layout.addWidget(self._wubrg_button_widget)

    def _add_card_type_export_buttons(self, type_groups, type_categories):
        if hasattr(self, '_card_type_button_widget') and self._card_type_button_widget:
            self._card_type_button_widget.deleteLater()
            self._card_type_button_widget = None
        button_layout = QHBoxLayout()
        for type_name, type_info in type_categories.items():
            if type_groups[type_name]:
                button = QPushButton(f'Export {type_name}')
                button.setObjectName('card_type_export_button')
                button.setToolTip(f'Export {type_name} cards breakdown to CSV')
                button.clicked.connect(lambda checked, cards=type_groups[type_name], name=type_name, color=type_info['color']: self._export_single_category(cards, name, color))
                button_layout.addWidget(button)
        if button_layout.count() > 0:
            self._card_type_button_widget = QWidget()
            self._card_type_button_widget.setLayout(button_layout)
            self.chart_layout.addWidget(self._card_type_button_widget)

    def _export_single_category(self, cards, category_name, color_hex):
        try:
            if not cards:
                QMessageBox.information(self, 'Export Info', f'No {category_name} cards to export.')
                return
            if hasattr(self, 'last_analysis_data') and self.last_analysis_data:
                set_codes = self.last_analysis_data.get('set_codes', [self.last_analysis_data.get('set_code', '')])
                if len(set_codes) == 1:
                    base_filename = f'{set_codes[0]}_{category_name.lower()}'
                else:
                    base_filename = f'combined_{len(set_codes)}_sets_{category_name.lower()}'
                letter_mapping = self._extract_letter_grouping_from_data(self.last_analysis_data)
            else:
                base_filename = f'analysis_{category_name.lower()}'
                letter_mapping = {}
            filename = f'{base_filename}.csv'
            filepath, _ = QFileDialog.getSaveFileName(self, f'Save {category_name} Analysis', filename, 'CSV Files (*.csv);All Files (*.*)')
            if not filepath:
                return
            self._export_color_breakdown(filepath, cards, category_name, color_hex, letter_mapping)
            QMessageBox.information(self, 'Export Successful', f'{category_name} analysis exported to:\n{filepath}')
        except Exception as e:
            QMessageBox.critical(self, 'Export Error', f'Failed to export {category_name} results:\n\n{str(e)}')

    def _toggle_maximize_chart(self):
        if self.maximized_dialog and self.maximized_dialog.isVisible():
            self._restore_chart()
        else:
            self._maximize_chart()

    def _maximize_chart(self):
        if not self.canvas:
            return
        self.maximized_dialog = QDialog(self)
        self.maximized_dialog.setWindowTitle('Analysis Chart - Maximized View')
        self.maximized_dialog.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMaximizeButtonHint)
        screen = self.screen().availableGeometry()
        self.maximized_dialog.setGeometry(screen.x() + 50, screen.y() + 50, screen.width() - 100, screen.height() - 100)
        layout = QVBoxLayout(self.maximized_dialog)
        header = QHBoxLayout()
        info_label = QLabel('Press Escape or click Restore to exit fullscreen')
        info_label.setStyleSheet('color: #888; font-size: 11px; padding: 5px;')
        header.addWidget(info_label)
        header.addStretch()
        restore_button = QPushButton(' Restore')
        restore_button.setMaximumWidth(100)
        restore_button.clicked.connect(self._restore_chart)
        header.addWidget(restore_button)
        layout.addLayout(header)
        if self.toolbar_layout:
            self.chart_layout.removeItem(self.toolbar_layout)
        if self.toolbar and self.toolbar.parent():
            self.toolbar.setParent(None)
            layout.addWidget(self.toolbar)
        canvas_index = self.chart_layout.indexOf(self.canvas)
        if canvas_index >= 0:
            self.chart_layout.takeAt(canvas_index)
        if self.canvas:
            layout.addWidget(self.canvas, 1)
        self.maximize_button.setText(' Restore')
        self.maximize_button.setToolTip('Restore normal view')
        self.maximized_dialog.show()
        if self.canvas:
            self.canvas.draw_idle()

    def _restore_chart(self):
        if not self.maximized_dialog:
            return
        if self.toolbar:
            self.toolbar.setParent(None)
        if self.canvas:
            self.canvas.setParent(None)
        if self.toolbar_layout:
            self.chart_layout.insertLayout(0, self.toolbar_layout)
        if self.canvas:
            self.chart_layout.insertWidget(1, self.canvas, 1)
        self.maximize_button.setText(' Maximize')
        self.maximize_button.setToolTip('Maximize chart view (Escape to exit)')
        self.maximized_dialog.close()
        self.maximized_dialog.deleteLater()
        self.maximized_dialog = None
        if self.canvas:
            self.canvas.draw_idle()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.maximized_dialog:
            self._restore_chart()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.canvas and self.canvas.isVisible():
            self.canvas.updateGeometry()
            if self.last_analysis_data:
                if not hasattr(self, '_resize_timer'):
                    from PyQt6.QtCore import QTimer
                    self._resize_timer = QTimer()
                    self._resize_timer.setSingleShot(True)
                    self._resize_timer.timeout.connect(self._handle_resize_redraw)
                self._resize_timer.stop()
                self._resize_timer.start(250)

    def _handle_resize_redraw(self):
        if self.canvas and self.last_analysis_data:
            try:
                self.canvas.draw_idle()
            except Exception:
                pass

    def get_debug_stats(self) -> dict:
        """Get debug statistics for this tab."""
        return self.debugger.get_stats()