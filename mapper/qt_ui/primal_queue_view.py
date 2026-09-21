"""PyQt6 Tab 3: Primal Queue View with catalog search and interactive 2D shelf viewer."""

from __future__ import annotations

from collections import Counter
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mapper.common import MAX_VISIBLE_PRODUCTS, clean_location_segment, make_slot_name, normalize_search
from mapper.database import Placement, WarehouseDatabase
from .designer_view import ShelfVisualizerWidget
from utils.barcode_scanner import format_product_id


class PrimalQueueView(QWidget):
    """Tab 3: Primal Queue search (hot sellers) & full catalog with integrated 2D shelf view."""

    def __init__(self, parent: QWidget | None, database: WarehouseDatabase):
        super().__init__(parent)
        self.database = database

        self.products: dict[str, str] = {}
        self.product_shortened: dict[str, str] = {}
        self.product_search: dict[str, str] = {}

        self.catalog_products: dict[str, tuple[str, str]] = {}
        self.catalog_search: dict[str, str] = {}

        self.placements: dict[str, Placement] = {}
        self.shelves: list[tuple[int, str, str, str]] = []
        self.shelf_choices: dict[str, int] = {}

        self.current_shelf_id: int | None = None
        self.current_layout: list[int] = []
        self.current_contents: list[tuple[str, str, Placement]] = []
        self.selected_slot_name: str | None = None

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self.refresh_results)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        lbl = QLabel("Primal Product Queue (Hot Sellers from CSV) · Catalog Search · Shelf Viewer")
        lbl.setStyleSheet("font-weight: 600; color: #1f2328; font-size: 13px;")
        header.addWidget(lbl)
        header.addStretch()
        main_layout.addLayout(header)

        # Splitter (Left: Products, Right: Shelf Viewer)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT PANE: Search & Products Table
        left_box = QGroupBox("Products (Primal Queue & Full Catalog)")
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(8, 14, 8, 8)
        left_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search code, full name, or shortened name")
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._on_search_return)
        search_row.addWidget(self.search_input)
        left_layout.addLayout(search_row)

        mode_row = QHBoxLayout()
        self.rb_primal = QRadioButton("Primal Queue (CSV)")
        self.rb_primal.setChecked(True)
        self.rb_primal.toggled.connect(self.refresh_results)
        mode_row.addWidget(self.rb_primal)

        self.rb_catalog = QRadioButton("Full Catalog")
        self.rb_catalog.toggled.connect(self.refresh_results)
        mode_row.addWidget(self.rb_catalog)
        mode_row.addStretch()
        left_layout.addLayout(mode_row)

        self.search_status_lbl = QLabel("")
        self.search_status_lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
        left_layout.addWidget(self.search_status_lbl)

        self.product_table = QTableWidget(0, 4)
        self.product_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock", "Location"])
        self.product_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.product_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.product_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.itemDoubleClicked.connect(self._on_product_double_click)
        left_layout.addWidget(self.product_table)

        splitter.addWidget(left_box)

        # RIGHT PANE: Shelf Selector, Visualizer & Slot Contents
        right_box = QGroupBox("Shelf View")
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(8, 14, 8, 8)
        right_layout.setSpacing(8)

        shelf_sel_row = QHBoxLayout()
        shelf_sel_row.addWidget(QLabel("Select shelf:"))
        self.shelf_combo = QComboBox()
        self.shelf_combo.setFixedWidth(280)
        self.shelf_combo.currentIndexChanged.connect(self._on_shelf_combo_changed)
        shelf_sel_row.addWidget(self.shelf_combo)
        shelf_sel_row.addStretch()
        right_layout.addLayout(shelf_sel_row)

        # Visualizer
        self.visualizer = ShelfVisualizerWidget()
        self.visualizer.slot_clicked.connect(self._on_slot_clicked)
        right_layout.addWidget(self.visualizer, stretch=3)

        # Slot contents
        self.slot_contents_lbl = QLabel("Slot Contents:")
        self.slot_contents_lbl.setStyleSheet("font-weight: 600; color: #1f2328; font-size: 12px;")
        right_layout.addWidget(self.slot_contents_lbl)

        self.slot_table = QTableWidget(0, 3)
        self.slot_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock"])
        self.slot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.slot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.slot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.slot_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.slot_table, stretch=2)

        splitter.addWidget(right_box)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        main_layout.addWidget(splitter)

    def refresh(self, reload_catalog: bool = False):
        product_rows = self.database.get_product_records()
        self.products = {pid: name for pid, name, _ in product_rows}
        self.product_shortened = {pid: sname for pid, _, sname in product_rows}
        self.product_search = {
            pid: normalize_search(f"{pid} {name} {sname}")
            for pid, name, sname in product_rows
        }

        if reload_catalog or not self.catalog_products:
            cat_rows = self.database.get_catalog_products()
            self.catalog_products = {pid: (name, sname) for pid, name, sname in cat_rows}
            self.catalog_search = {
                pid: normalize_search(f"{pid} {name} {sname}")
                for pid, name, sname in cat_rows
            }

        self.placements = self.database.get_placement_details()
        self.shelves = self.database.list_shelves()
        self.shelf_choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in self.shelves
        }

        self.shelf_combo.blockSignals(True)
        self.shelf_combo.clear()
        self.shelf_combo.addItem("— Select a shelf —", None)
        for label, s_id in self.shelf_choices.items():
            self.shelf_combo.addItem(label, s_id)
        self.shelf_combo.blockSignals(False)

        if self.current_shelf_id is not None:
            idx = self.shelf_combo.findData(self.current_shelf_id)
            if idx > 0:
                self.shelf_combo.setCurrentIndex(idx)
                self._load_shelf_by_id(self.current_shelf_id, select_slot=self.selected_slot_name)
            else:
                self.current_shelf_id = None
                self.visualizer.clear()
        else:
            self.visualizer.clear()

        self.refresh_results()

    def _on_search_changed(self, _text: str):
        self.search_timer.start()

    def _on_search_return(self):
        cur = self.search_input.text().strip()
        fmt = format_product_id(cur)
        if fmt != cur:
            self.search_input.setText(fmt)
        self.refresh_results()

    def refresh_results(self):
        raw = self.search_input.text().strip()
        query = normalize_search(raw)
        is_catalog = self.rb_catalog.isChecked()

        mono_font = QFont("JetBrains Mono", 9)

        if not is_catalog:
            matches = [
                pid for pid in self.products
                if not query or query in self.product_search[pid]
            ]
            matches.sort(key=lambda pid: (pid.casefold() != raw.casefold(), pid not in self.placements, pid.casefold()))

            self.product_table.setRowCount(min(len(matches), MAX_VISIBLE_PRODUCTS))
            for row, pid in enumerate(matches[:MAX_VISIBLE_PRODUCTS]):
                name = self.products[pid]
                placement = self.placements.get(pid)
                loc = placement.slot_name if placement else "Unassigned"
                qty = str(placement.stock_qty) if placement and placement.stock_qty is not None else "—"

                item0 = QTableWidgetItem(pid)
                item0.setFont(mono_font)
                item1 = QTableWidgetItem(name)
                item2 = QTableWidgetItem(qty)
                item3 = QTableWidgetItem(loc)
                item3.setFont(mono_font)

                self.product_table.setItem(row, 0, item0)
                self.product_table.setItem(row, 1, item1)
                self.product_table.setItem(row, 2, item2)
                self.product_table.setItem(row, 3, item3)

            self.search_status_lbl.setText(f"Showing {min(len(matches), MAX_VISIBLE_PRODUCTS)} of {len(matches)} primal products.")
        else:
            matches = [
                pid for pid in self.catalog_products
                if not query or query in self.catalog_search[pid]
            ]
            matches.sort(key=lambda pid: (pid.casefold() != raw.casefold(), pid not in self.placements, pid.casefold()))

            self.product_table.setRowCount(min(len(matches), MAX_VISIBLE_PRODUCTS))
            for row, pid in enumerate(matches[:MAX_VISIBLE_PRODUCTS]):
                name, _ = self.catalog_products[pid]
                placement = self.placements.get(pid)
                loc = placement.slot_name if placement else "Unassigned"
                qty = str(placement.stock_qty) if placement and placement.stock_qty is not None else "—"

                item0 = QTableWidgetItem(pid)
                item0.setFont(mono_font)
                item1 = QTableWidgetItem(name)
                item2 = QTableWidgetItem(qty)
                item3 = QTableWidgetItem(loc)
                item3.setFont(mono_font)

                self.product_table.setItem(row, 0, item0)
                self.product_table.setItem(row, 1, item1)
                self.product_table.setItem(row, 2, item2)
                self.product_table.setItem(row, 3, item3)

            self.search_status_lbl.setText(f"Showing {min(len(matches), MAX_VISIBLE_PRODUCTS)} of {len(matches)} catalog products.")

    def _on_shelf_combo_changed(self, index: int):
        shelf_id = self.shelf_combo.itemData(index)
        if shelf_id:
            self._load_shelf_by_id(shelf_id)
        else:
            self.current_shelf_id = None
            self.visualizer.clear()
            self.slot_table.setRowCount(0)

    def _load_shelf_by_id(self, shelf_id: int, select_slot: str | None = None):
        self.current_shelf_id = shelf_id
        meta = self.database.get_shelf_metadata(shelf_id)
        if not meta:
            self.visualizer.clear("Shelf not found.")
            return

        floor, side, shelf_code = meta
        layout = self.database.get_shelf_layout(shelf_id)
        self.current_layout = layout
        self.current_contents = self.database.get_shelf_contents(shelf_id)
        self.selected_slot_name = select_slot

        # Slot counts
        slot_counts: dict[str, tuple[int, int]] = {}
        for _, _, placement in self.current_contents:
            s_name = placement.slot_name
            saved, staged = slot_counts.get(s_name, (0, 0))
            slot_counts[s_name] = (saved + 1, staged)

        self.visualizer.render_shelf(
            floor=floor,
            side=side,
            shelf_code=shelf_code,
            layout=layout,
            slot_counts=slot_counts,
            selected_slot=select_slot,
        )

        if select_slot:
            self._populate_slot_contents(select_slot)
        else:
            self.slot_contents_lbl.setText("Slot Contents: (Click a cell above to view)")
            self.slot_table.setRowCount(0)

    def _on_slot_clicked(self, slot_name: str):
        self.selected_slot_name = slot_name
        self._populate_slot_contents(slot_name)

    def _populate_slot_contents(self, slot_name: str):
        self.slot_contents_lbl.setText(f"Slot Contents: {slot_name}")
        slot_items = [
            (pid, name, plc) for pid, name, plc in self.current_contents
            if plc.slot_name == slot_name
        ]
        self.slot_table.setRowCount(len(slot_items))
        mono_font = QFont("JetBrains Mono", 9)
        for row, (pid, name, plc) in enumerate(slot_items):
            item0 = QTableWidgetItem(pid)
            item0.setFont(mono_font)
            item1 = QTableWidgetItem(name)
            item2 = QTableWidgetItem(str(plc.stock_qty if plc.stock_qty is not None else 1))

            self.slot_table.setItem(row, 0, item0)
            self.slot_table.setItem(row, 1, item1)
            self.slot_table.setItem(row, 2, item2)

    def _on_product_double_click(self, item: QTableWidgetItem):
        row = item.row()
        pid = self.product_table.item(row, 0).text()
        placement = self.placements.get(pid)
        if not placement:
            return

        slot_name = placement.slot_name
        slot_info = self.database.get_slot_address(slot_name)
        if not slot_info:
            return

        shelf_id = self.database.get_shelf_id(slot_info.floor, slot_info.shelf_code, side=slot_info.side)
        if shelf_id:
            idx = self.shelf_combo.findData(shelf_id)
            if idx > 0:
                self.shelf_combo.setCurrentIndex(idx)
                self._load_shelf_by_id(shelf_id, select_slot=slot_name)
