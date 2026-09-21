"""PyQt6 Tab 2: Location Assignment View with exact 3-panel split and zero emojis."""

from __future__ import annotations

from typing import Callable
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mapper.common import clean_location_segment, make_slot_name, normalize_search
from utils.barcode_scanner import format_product_id


class LocationAssignmentView(QWidget):
    """Tab 2: 3-panel layout: Products, On-hand Queue & Address, and Loaded Address Contents."""

    # Signals for actions
    search_changed = pyqtSignal(str)
    queue_to_hand_requested = pyqtSignal(list)       # list of product_ids
    catalog_to_queue_requested = pyqtSignal(list)     # list of product_ids
    load_address_requested = pyqtSignal(str, str, str, int, int) # floor, side, shelf, row, slot
    assign_address_requested = pyqtSignal()
    dequeue_hand_requested = pyqtSignal(list)        # list of product_ids
    hand_to_address_requested = pyqtSignal()
    slot_to_hand_requested = pyqtSignal(list)         # list of product_ids from loaded address
    remove_from_slot_requested = pyqtSignal(list)     # list of product_ids to unassign
    connect_chrome_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # Header bar
        header = QHBoxLayout()
        desc = QLabel("Build a persistent on-hand batch, then assign it to one exact shelf address.")
        desc.setStyleSheet("font-weight: 600; color: #1f2328; font-size: 13px;")
        header.addWidget(desc)

        header.addStretch()

        self.connect_chrome_btn = QPushButton("Connect Chrome")
        self.connect_chrome_btn.clicked.connect(self.connect_chrome_requested.emit)
        header.addWidget(self.connect_chrome_btn)

        main_layout.addLayout(header)

        # 3-Panel Horizontal Splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # PANEL 1: Products
        products_panel = QGroupBox("Products")
        p1_layout = QVBoxLayout(products_panel)
        p1_layout.setContentsMargins(8, 14, 8, 8)
        p1_layout.setSpacing(8)

        p1_splitter = QSplitter(Qt.Orientation.Vertical)

        # Sub-panel 1A: Unassigned Queue
        queue_box = QGroupBox("Total unassigned product queue")
        q_layout = QVBoxLayout(queue_box)
        q_layout.setContentsMargins(8, 14, 8, 8)
        q_layout.setSpacing(6)

        q_search_layout = QHBoxLayout()
        q_search_layout.addWidget(QLabel("Search:"))
        self.queue_search = QLineEdit()
        self.queue_search.setPlaceholderText("Search code, full name, or shortened name")
        self.queue_search.textChanged.connect(self._on_search_text_changed)
        self.queue_search.returnPressed.connect(self._on_search_return)
        q_search_layout.addWidget(self.queue_search)
        q_layout.addLayout(q_search_layout)

        self.search_loc_lbl = QLabel("")
        self.search_loc_lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
        q_layout.addWidget(self.search_loc_lbl)

        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock", "Date Added"])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.queue_table.verticalHeader().setVisible(False)
        q_layout.addWidget(self.queue_table)

        q_btn_layout = QHBoxLayout()
        self.move_to_hand_btn = QPushButton("Move selected → on-hand")
        self.move_to_hand_btn.setProperty("primary", "true")
        self.move_to_hand_btn.clicked.connect(self._on_move_to_hand)
        q_btn_layout.addWidget(self.move_to_hand_btn)
        q_btn_layout.addStretch()
        q_layout.addLayout(q_btn_layout)

        p1_splitter.addWidget(queue_box)

        # Sub-panel 1B: Full Product Catalog
        catalog_box = QGroupBox("Full product catalog")
        cat_layout = QVBoxLayout(catalog_box)
        cat_layout.setContentsMargins(8, 14, 8, 8)
        cat_layout.setSpacing(6)

        self.catalog_table = QTableWidget(0, 4)
        self.catalog_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock", "Location"])
        self.catalog_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.catalog_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.catalog_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.catalog_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.catalog_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.catalog_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.catalog_table.verticalHeader().setVisible(False)
        self.catalog_table.doubleClicked.connect(self._on_catalog_double_click)
        cat_layout.addWidget(self.catalog_table)

        cat_btn_layout = QHBoxLayout()
        self.cat_to_queue_btn = QPushButton("Transfer selected to queue")
        self.cat_to_queue_btn.clicked.connect(self._on_catalog_to_queue)
        cat_btn_layout.addWidget(self.cat_to_queue_btn)
        cat_btn_layout.addStretch()
        cat_layout.addLayout(cat_btn_layout)

        p1_splitter.addWidget(catalog_box)
        p1_splitter.setStretchFactor(0, 1)
        p1_splitter.setStretchFactor(1, 1)
        p1_layout.addWidget(p1_splitter)

        main_splitter.addWidget(products_panel)

        # PANEL 2: On-hand Queue and Shelf Address
        hand_panel = QGroupBox("On-hand queue and shelf address")
        p2_layout = QVBoxLayout(hand_panel)
        p2_layout.setContentsMargins(8, 14, 8, 8)
        p2_layout.setSpacing(8)

        # Address Inputs Group
        addr_box = QFrame()
        addr_box.setStyleSheet("background-color: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 4px; padding: 6px;")
        addr_layout = QVBoxLayout(addr_box)
        addr_layout.setSpacing(6)

        coords_layout = QHBoxLayout()
        coords_layout.addWidget(QLabel("Fl:"))
        self.floor_input = QLineEdit("1")
        self.floor_input.setFixedWidth(38)
        coords_layout.addWidget(self.floor_input)

        coords_layout.addWidget(QLabel("Sd:"))
        self.side_input = QLineEdit("1")
        self.side_input.setFixedWidth(32)
        coords_layout.addWidget(self.side_input)

        coords_layout.addWidget(QLabel("Sh:"))
        self.shelf_input = QLineEdit("A")
        self.shelf_input.setFixedWidth(42)
        coords_layout.addWidget(self.shelf_input)

        coords_layout.addWidget(QLabel("Rw:"))
        self.row_input = QLineEdit("1")
        self.row_input.setFixedWidth(38)
        coords_layout.addWidget(self.row_input)

        coords_layout.addWidget(QLabel("Sl:"))
        self.slot_input = QLineEdit("1")
        self.slot_input.setFixedWidth(38)
        coords_layout.addWidget(self.slot_input)

        self.load_addr_btn = QPushButton("Load")
        self.load_addr_btn.setFixedWidth(55)
        self.load_addr_btn.clicked.connect(self._on_load_address)
        coords_layout.addWidget(self.load_addr_btn)
        addr_layout.addLayout(coords_layout)

        # Target badge
        self.target_badge = QLabel("Target: None")
        self.target_badge.setStyleSheet("font-weight: 700; color: #1d4ed8; background-color: #dbeafe; padding: 4px 8px; border-radius: 3px; font-family: 'JetBrains Mono', monospace;")
        addr_layout.addWidget(self.target_badge)

        p2_layout.addWidget(addr_box)

        # On-hand queue table
        p2_layout.addWidget(QLabel("Products in on-hand queue:"))
        self.hand_table = QTableWidget(0, 3)
        self.hand_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock"])
        self.hand_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.hand_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.hand_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.hand_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hand_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.hand_table.verticalHeader().setVisible(False)
        p2_layout.addWidget(self.hand_table)

        # Hand actions
        hand_btns = QVBoxLayout()
        hand_btns.setSpacing(6)

        self.assign_btn = QPushButton("Assign on-hand to address")
        self.assign_btn.setProperty("primary", "true")
        self.assign_btn.setFixedHeight(32)
        self.assign_btn.clicked.connect(self.assign_address_requested.emit)
        hand_btns.addWidget(self.assign_btn)

        sub_hand_btns = QHBoxLayout()
        self.clear_hand_btn = QPushButton("Clear on-hand")
        self.clear_hand_btn.clicked.connect(self._on_clear_hand)
        sub_hand_btns.addWidget(self.clear_hand_btn)

        self.kiotviet_sync = QCheckBox("Sync KiotViet")
        self.kiotviet_sync.setChecked(False)
        sub_hand_btns.addWidget(self.kiotviet_sync)
        sub_hand_btns.addStretch()
        hand_btns.addLayout(sub_hand_btns)

        p2_layout.addLayout(hand_btns)
        main_splitter.addWidget(hand_panel)

        # PANEL 3: Loaded Address Contents
        contents_panel = QGroupBox("Loaded address contents")
        p3_layout = QVBoxLayout(contents_panel)
        p3_layout.setContentsMargins(8, 14, 8, 8)
        p3_layout.setSpacing(8)

        self.slot_header = QLabel("Slot: (None loaded)")
        self.slot_header.setStyleSheet("font-weight: 700; color: #1f2328; font-size: 13px; font-family: 'JetBrains Mono', monospace;")
        p3_layout.addWidget(self.slot_header)

        self.slot_table = QTableWidget(0, 4)
        self.slot_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock", "Assigned Date"])
        self.slot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.slot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.slot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.slot_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.slot_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.slot_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.slot_table.verticalHeader().setVisible(False)
        p3_layout.addWidget(self.slot_table)

        slot_actions = QHBoxLayout()
        self.slot_to_hand_btn = QPushButton("Move to on-hand")
        self.slot_to_hand_btn.clicked.connect(self._on_slot_to_hand)
        slot_actions.addWidget(self.slot_to_hand_btn)

        self.remove_slot_btn = QPushButton("Remove")
        self.remove_slot_btn.setProperty("danger", "true")
        self.remove_slot_btn.clicked.connect(self._on_remove_from_slot)
        slot_actions.addWidget(self.remove_slot_btn)
        slot_actions.addStretch()
        p3_layout.addLayout(slot_actions)

        # Activity Log
        p3_layout.addWidget(QLabel("Activity Log:"))
        self.activity_log = QListWidget()
        self.activity_log.setFixedHeight(120)
        self.activity_log.setStyleSheet("background-color: #f7f8fa; border: 1px solid #e5e7eb; font-size: 11px; color: #4b5563;")
        p3_layout.addWidget(self.activity_log)

        main_splitter.addWidget(contents_panel)

        # Panel proportions: 4 : 3 : 3
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setStretchFactor(2, 3)
        main_layout.addWidget(main_splitter)

    # UI Event handlers
    def _on_search_text_changed(self, text: str):
        self.search_changed.emit(text)

    def _on_search_return(self):
        current = self.queue_search.text().strip()
        formatted = format_product_id(current)
        if formatted != current:
            self.queue_search.setText(formatted)

    def _on_move_to_hand(self):
        selected_rows = self.queue_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        prod_ids = [self.queue_table.item(r.row(), 0).text() for r in selected_rows]
        self.queue_to_hand_requested.emit(prod_ids)

    def _on_catalog_to_queue(self):
        selected_rows = self.catalog_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        prod_ids = [self.catalog_table.item(r.row(), 0).text() for r in selected_rows]
        self.catalog_to_queue_requested.emit(prod_ids)

    def _on_catalog_double_click(self):
        self._on_catalog_to_queue()

    def _on_load_address(self):
        floor = clean_location_segment(self.floor_input.text())
        side = clean_location_segment(self.side_input.text())
        shelf = clean_location_segment(self.shelf_input.text()).upper()
        try:
            row = int(self.row_input.text())
            slot = int(self.slot_input.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Address", "Row and Slot must be integers.")
            return

        if not floor or not side or not shelf:
            QMessageBox.warning(self, "Invalid Address", "Floor, Side, and Shelf cannot be empty.")
            return

        self.load_address_requested.emit(floor, side, shelf, row, slot)

    def _on_clear_hand(self):
        selected_rows = self.hand_table.selectionModel().selectedRows()
        if selected_rows:
            prod_ids = [self.hand_table.item(r.row(), 0).text() for r in selected_rows]
        else:
            prod_ids = [self.hand_table.item(r, 0).text() for r in range(self.hand_table.rowCount())]
        self.dequeue_hand_requested.emit(prod_ids)

    def _on_slot_to_hand(self):
        selected_rows = self.slot_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        prod_ids = [self.slot_table.item(r.row(), 0).text() for r in selected_rows]
        self.slot_to_hand_requested.emit(prod_ids)

    def _on_remove_from_slot(self):
        selected_rows = self.slot_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        prod_ids = [self.slot_table.item(r.row(), 0).text() for r in selected_rows]
        self.remove_from_slot_requested.emit(prod_ids)

    # Populate Helpers
    def populate_queue(self, products: list[dict], returned_ids: set[str] | None = None):
        returned_ids = returned_ids or set()
        self.queue_table.setRowCount(len(products))
        mono_font = QFont("JetBrains Mono", 9)
        yellow_bg = QColor("#fff2a8")

        for row, prod in enumerate(products):
            pid = str(prod.get("product_id", ""))
            is_returned = pid in returned_ids

            item0 = QTableWidgetItem(pid)
            item0.setFont(mono_font)
            item1 = QTableWidgetItem(str(prod.get("name", "")))
            item2 = QTableWidgetItem(str(prod.get("stock_qty", 0)))
            item3 = QTableWidgetItem(str(prod.get("created_at", "")))

            if is_returned:
                for itm in (item0, item1, item2, item3):
                    itm.setBackground(yellow_bg)

            self.queue_table.setItem(row, 0, item0)
            self.queue_table.setItem(row, 1, item1)
            self.queue_table.setItem(row, 2, item2)
            self.queue_table.setItem(row, 3, item3)

    def populate_catalog(self, catalog: list[dict]):
        self.catalog_table.setRowCount(len(catalog))
        mono_font = QFont("JetBrains Mono", 9)
        for row, item in enumerate(catalog):
            item0 = QTableWidgetItem(str(item.get("product_id", "")))
            item0.setFont(mono_font)
            item1 = QTableWidgetItem(str(item.get("name", "")))
            item2 = QTableWidgetItem(str(item.get("stock_qty", 0)))
            item3 = QTableWidgetItem(str(item.get("loc_id", "") or "—"))
            item3.setFont(mono_font)

            self.catalog_table.setItem(row, 0, item0)
            self.catalog_table.setItem(row, 1, item1)
            self.catalog_table.setItem(row, 2, item2)
            self.catalog_table.setItem(row, 3, item3)

    def populate_on_hand(self, on_hand: list[dict]):
        self.hand_table.setRowCount(len(on_hand))
        mono_font = QFont("JetBrains Mono", 9)
        for row, item in enumerate(on_hand):
            item0 = QTableWidgetItem(str(item.get("product_id", "")))
            item0.setFont(mono_font)
            item1 = QTableWidgetItem(str(item.get("name", "")))
            item2 = QTableWidgetItem(str(item.get("stock_qty", 1)))

            self.hand_table.setItem(row, 0, item0)
            self.hand_table.setItem(row, 1, item1)
            self.hand_table.setItem(row, 2, item2)

    def populate_slot_contents(self, slot_name: str | None, contents: list[dict]):
        if not slot_name:
            self.slot_header.setText("Slot: (None loaded)")
            self.slot_table.setRowCount(0)
            return

        self.slot_header.setText(f"Slot: {slot_name}")
        self.slot_table.setRowCount(len(contents))
        mono_font = QFont("JetBrains Mono", 9)
        for row, item in enumerate(contents):
            item0 = QTableWidgetItem(str(item.get("product_id", "")))
            item0.setFont(mono_font)
            item1 = QTableWidgetItem(str(item.get("name", "")))
            item2 = QTableWidgetItem(str(item.get("stock_qty", 1)))
            item3 = QTableWidgetItem(str(item.get("assigned_at", "")))

            self.slot_table.setItem(row, 0, item0)
            self.slot_table.setItem(row, 1, item1)
            self.slot_table.setItem(row, 2, item2)
            self.slot_table.setItem(row, 3, item3)

    def log_activity(self, message: str):
        self.activity_log.insertItem(0, message)
        if self.activity_log.count() > 100:
            self.activity_log.takeItem(self.activity_log.count() - 1)
