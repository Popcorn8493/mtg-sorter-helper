from PyQt6.QtWidgets import QMainWindow, QTabWidget
from PyQt6.QtCore import QSettings

from api.scryfall_api import ScryfallAPI
from ui.sorter_tab import ManaBoxSorterTab
from ui.analyzer_tab import SetAnalyzerTab
from core.constants import Config


class MTGToolkitWindow(QMainWindow):
    def __init__(self):
        super().__init__();
        self.setWindowTitle("MTG Toolkit");
        self.setGeometry(100, 100, 1280, 800)
        self.settings = QSettings(Config.ORG_NAME, Config.APP_NAME)
        self.api = ScryfallAPI()
        tab_widget = QTabWidget();
        self.setCentralWidget(tab_widget)

        # Initialize Sorter first, then pass it to the Analyzer
        self.sorter_tab = ManaBoxSorterTab(self.api)
        self.analyzer_tab = SetAnalyzerTab(self.api, self.sorter_tab)

        tab_widget.addTab(self.sorter_tab, "Collection Sorter")
        tab_widget.addTab(self.analyzer_tab, "Set Analyzer")

        self.load_settings()

    def load_settings(self):
        self.analyzer_tab.set_code_edit.setText(self.settings.value("analyzer/lastSetCode", "", str))
        selected_items = self.settings.value("sorter/sortCriteria", [], str)
        if isinstance(selected_items, str): selected_items = [selected_items]  # Handle single item case
        for item_text in selected_items: self.sorter_tab.selected_list.addItem(item_text)

    def save_settings(self):
        self.settings.setValue("analyzer/lastSetCode", self.analyzer_tab.set_code_edit.text())
        selected_items = [self.sorter_tab.selected_list.item(i).text() for i in
                          range(self.sorter_tab.selected_list.count())]
        self.settings.setValue("sorter/sortCriteria", selected_items)

    def closeEvent(self, event):
        self.save_settings();
        super().closeEvent(event)
