"""PyQt6 Tab 5: Two-shelf workspace for switching or combining cell contents."""

from __future__ import annotations

from typing import Callable
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mapper.common import clean_location_segment, make_slot_name, normalize_search
from mapper.database import Placement, SlotAddress, WarehouseDatabase
from .designer_view import ShelfVisualizerWidget
from utils.barcode_scanner import format_product_id


class CellTransferPane(QGroupBox):
    """One independently selectable shelf and cell view."""

    cell_selected = pyqtSignal(object)  # SlotAddress or None

    def __init__(self, title: str, database: WarehouseDatabase, parent: QWidget | None = None):
        super().__init__(title, parent)
        self.database = database
        self.shelves: list[tuple[int, str, str, str]] = []
        self.shelf_choices: dict[str, int] = {}
        self.current_shelf_id: int | None = None
        self.current_layout: list[int] = []
        self.current_contents: list[tuple[str, str, Placement]] = []
        self.selected_address: SlotAddress | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(6)

        # Selectors: Shelf, Row, Cell
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Shelf:"))
        self.shelf_combo = QComboBox()
        self.shelf_combo.currentIndexChanged.connect(self._on_shelf_changed)
        sel_row.addWidget(self.shelf_combo, stretch=2)

        sel_row.addWidget(QLabel("Row:"))
        self.row_combo = QComboBox()
        self.row_combo.setFixedWidth(50)
        self.row_combo.currentIndexChanged.connect(self._on_row_changed)
        sel_row.addWidget(self.row_combo)

        sel_row.addWidget(QLabel("Cell:"))
        self.cell_combo = QComboBox()
        self.cell_combo.setFixedWidth(50)
        self.cell_combo.currentIndexChanged.connect(self._on_cell_changed)
        sel_row.addWidget(self.cell_combo)

        layout.addLayout(sel_row)

        # Product Search Row
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Find product ID:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Scan barcode or enter product ID")
        self.search_input.returnPressed.connect(self._on_find_product)
        search_row.addWidget(self.search_input)

        self.find_btn = QPushButton("Find")
        self.find_btn.setFixedWidth(55)
        self.find_btn.clicked.connect(self._on_find_product)
        search_row.addWidget(self.find_btn)
        layout.addLayout(search_row)

        # Visualizer
        self.visualizer = ShelfVisualizerWidget()
        self.visualizer.slot_clicked.connect(self._on_slot_clicked)
        layout.addWidget(self.visualizer, stretch=3)

        # Cell details header
        self.slot_header = QLabel("Cell: (No cell selected)")
        self.slot_header.setStyleSheet("font-weight: 700; color: #1f2328; font-size: 12px; font-family: 'JetBrains Mono', monospace;")
        layout.addWidget(self.slot_header)

        # Cell contents table
        self.contents_table = QTableWidget(0, 3)
        self.contents_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock"])
        self.contents_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.contents_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.contents_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.contents_table.verticalHeader().setVisible(False)
        layout.addWidget(self.contents_table, stretch=2)

    @property
    def selected_product_count(self) -> int:
        return self.contents_table.rowCount()

    def refresh(self):
        self.shelves = self.database.list_shelves()
        self.shelf_choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in self.shelves
        }

        current_shelf = self.shelf_combo.currentData()
        self.shelf_combo.blockSignals(True)
        self.shelf_combo.clear()
        self.shelf_combo.addItem("— Select shelf —", None)
        for label, s_id in self.shelf_choices.items():
            self.shelf_combo.addItem(label, s_id)
        self.shelf_combo.blockSignals(False)

        if current_shelf:
            idx = self.shelf_combo.findData(current_shelf)
            if idx > 0:
                self.shelf_combo.setCurrentIndex(idx)
                self._load_shelf(current_shelf)

    def _on_shelf_changed(self, index: int):
        shelf_id = self.shelf_combo.itemData(index)
        if shelf_id:
            self._load_shelf(shelf_id)
        else:
            self.current_shelf_id = None
            self.visualizer.clear()
            self.contents_table.setRowCount(0)
            self.slot_header.setText("Cell: (No cell selected)")
            self.selected_address = None
            self.cell_selected.emit(None)

    def _load_shelf(self, shelf_id: int):
        self.current_shelf_id = shelf_id
        meta = self.database.get_shelf_metadata(shelf_id)
        if not meta:
            self.visualizer.clear()
            return

        floor, side, shelf_code = meta
        layout = self.database.get_shelf_layout(shelf_id)
        self.current_layout = layout
        self.current_contents = self.database.get_shelf_contents(shelf_id)

        # Populate row combo
        self.row_combo.blockSignals(True)
        self.row_combo.clear()
        for r in range(1, len(layout) + 1):
            self.row_combo.addItem(str(r), r)
        self.row_combo.blockSignals(False)

        # Slot counts
        slot_counts: dict[str, tuple[int, int]] = {}
        for _, _, placement in self.current_contents:
            s_name = placement.slot_name
            saved, staged = slot_counts.get(s_name, (0, 0))
            slot_counts[s_name] = (saved + 1, staged)

        target_slot = self.selected_address.slot_name if self.selected_address else None
        self.visualizer.render_shelf(
            floor=floor,
            side=side,
            shelf_code=shelf_code,
            layout=layout,
            slot_counts=slot_counts,
            selected_slot=target_slot,
        )

        self._update_cell_combo()

    def _update_cell_combo(self):
        row_num = self.row_combo.currentData()
        if row_num is None or not self.current_layout or row_num > len(self.current_layout):
            self.cell_combo.clear()
            return

        slot_count = self.current_layout[row_num - 1]
        self.cell_combo.blockSignals(True)
        self.cell_combo.clear()
        for c in range(1, slot_count + 1):
            self.cell_combo.addItem(str(c), c)
        self.cell_combo.blockSignals(False)

    def _on_row_changed(self, _index: int):
        self._update_cell_combo()
        self._sync_address_from_combos()

    def _on_cell_changed(self, _index: int):
        self._sync_address_from_combos()

    def _sync_address_from_combos(self):
        if not self.current_shelf_id:
            return
        row = self.row_combo.currentData()
        cell = self.cell_combo.currentData()
        if row is None or cell is None:
            return

        meta = self.database.get_shelf_metadata(self.current_shelf_id)
        if not meta:
            return
        floor, side, shelf_code = meta
        slot_name = make_slot_name(floor, shelf_code, row, cell, side=side)
        self._select_slot_by_name(slot_name)

    def _on_slot_clicked(self, slot_name: str):
        self._select_slot_by_name(slot_name)

    def _select_slot_by_name(self, slot_name: str):
        addr = self.database.get_slot_address(slot_name)
        if not addr:
            return
        self.selected_address = addr
        self.slot_header.setText(f"Cell: {slot_name}")

        # Sync combos
        if addr.shelf_id == self.current_shelf_id:
            self.row_combo.blockSignals(True)
            self.row_combo.setCurrentIndex(addr.row_number - 1)
            self.row_combo.blockSignals(False)

            self._update_cell_combo()
            self.cell_combo.blockSignals(True)
            self.cell_combo.setCurrentIndex(addr.slot_number - 1)
            self.cell_combo.blockSignals(False)

        # Populate contents
        items = [
            (pid, name, plc) for pid, name, plc in self.current_contents
            if plc.slot_name == slot_name
        ]
        self.contents_table.setRowCount(len(items))
        mono_font = QFont("JetBrains Mono", 9)
        for row, (pid, name, plc) in enumerate(items):
            item0 = QTableWidgetItem(pid)
            item0.setFont(mono_font)
            item1 = QTableWidgetItem(name)
            item2 = QTableWidgetItem(str(plc.stock_qty if plc.stock_qty is not None else 1))

            self.contents_table.setItem(row, 0, item0)
            self.contents_table.setItem(row, 1, item1)
            self.contents_table.setItem(row, 2, item2)

        self.cell_selected.emit(self.selected_address)

    def _on_find_product(self):
        raw = self.search_input.text().strip()
        pid = format_product_id(raw)
        if pid != raw:
            self.search_input.setText(pid)

        if not pid:
            return

        placements = self.database.get_placement_details()
        plc = placements.get(pid)
        if not plc:
            QMessageBox.information(self, "Product Not Found", f"Product '{pid}' has no assigned location.")
            return

        addr = self.database.get_slot_address(plc.slot_name)
        if not addr:
            return

        idx = self.shelf_combo.findData(addr.shelf_id)
        if idx > 0:
            self.shelf_combo.setCurrentIndex(idx)
            self._load_shelf(addr.shelf_id)
            self._select_slot_by_name(addr.slot_name)


class CellTransferView(QWidget):
    """Tab 5: Two-shelf workspace for switching or combining cell contents."""

    on_changed = pyqtSignal(str)

    def __init__(
        self,
        parent: QWidget | None,
        database: WarehouseDatabase,
        can_change_cells: Callable[[], bool],
    ):
        super().__init__(parent)
        self.database = database
        self.can_change = can_change_cells

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # Header Notice
        desc = QLabel(
            "Caution: Cell switch and combine operations update SQLite immediately.\n"
            "Finish or commit any pending Shelf Designer edits first."
        )
        desc.setStyleSheet("color: #b45309; font-weight: 500; font-size: 12px;")
        main_layout.addWidget(desc)

        # Splitter with Left Pane, Center Actions, Right Pane
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.left_pane = CellTransferPane("Left cell", database)
        splitter.addWidget(self.left_pane)

        # Action panel in center
        actions_box = QGroupBox("Cell actions")
        actions_box.setFixedWidth(200)
        act_layout = QVBoxLayout(actions_box)
        act_layout.setContentsMargins(10, 14, 10, 10)
        act_layout.setSpacing(8)

        self.swap_btn = QPushButton("Switch cells ↔")
        self.swap_btn.setProperty("primary", "true")
        self.swap_btn.setFixedHeight(32)
        self.swap_btn.clicked.connect(self.swap_cells)
        act_layout.addWidget(self.swap_btn)

        self.combine_lr_btn = QPushButton("Combine left → right")
        self.combine_lr_btn.clicked.connect(lambda: self.combine_cells(self.left_pane, self.right_pane))
        act_layout.addWidget(self.combine_lr_btn)

        self.combine_rl_btn = QPushButton("Combine right → left")
        self.combine_rl_btn.clicked.connect(lambda: self.combine_cells(self.right_pane, self.left_pane))
        act_layout.addWidget(self.combine_rl_btn)

        act_layout.addSpacing(10)

        refresh_btn = QPushButton("Refresh both")
        refresh_btn.clicked.connect(self.refresh)
        act_layout.addWidget(refresh_btn)

        act_layout.addSpacing(12)

        info = QLabel(
            "Switch exchanges both cells.\n\n"
            "Combine empties the source into the target and keeps the target's current products."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #6b7280; font-size: 11px;")
        act_layout.addWidget(info)

        act_layout.addSpacing(8)

        self.status_lbl = QLabel("Choose two cells.")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("font-weight: 600; color: #1f2328; font-size: 11px;")
        act_layout.addWidget(self.status_lbl)

        act_layout.addStretch()
        splitter.addWidget(actions_box)

        self.right_pane = CellTransferPane("Right cell", database)
        splitter.addWidget(self.right_pane)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        main_layout.addWidget(splitter)

    def refresh(self):
        self.left_pane.refresh()
        self.right_pane.refresh()

    def _selected_pair(self) -> tuple[SlotAddress, SlotAddress] | None:
        left = self.left_pane.selected_address
        right = self.right_pane.selected_address
        if left is None or right is None:
            QMessageBox.information(self, "Choose two cells", "Select one shelf cell on the left and one on the right first.")
            return None
        if left.slot_id == right.slot_id:
            QMessageBox.information(self, "Choose different cells", "The left and right selections point to the same shelf cell.")
            return None
        return left, right

    def swap_cells(self):
        if not self.can_change():
            return
        pair = self._selected_pair()
        if pair is None:
            return
        left, right = pair
        msg = (
            f"Exchange all products in {left.slot_name} and {right.slot_name}?\n\n"
            f"{left.slot_name}: {self.left_pane.selected_product_count} product(s)\n"
            f"{right.slot_name}: {self.right_pane.selected_product_count} product(s)"
        )
        reply = QMessageBox.question(self, "Switch complete cell contents?", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            left_count, right_count = self.database.swap_slot_contents(left.slot_id, right.slot_id)
        except Exception as error:
            QMessageBox.critical(self, "Error", f"Cells could not be switched: {error}")
            return

        message = f"Switched {left.slot_name} ({left_count}) with {right.slot_name} ({right_count})."
        self.on_changed.emit(message)
        self.refresh()
        self.status_lbl.setText(message)

    def combine_cells(self, source: CellTransferPane, target: CellTransferPane):
        if not self.can_change():
            return
        pair = self._selected_pair()
        if pair is None:
            return
        src_addr = source.selected_address
        tgt_addr = target.selected_address
        if src_addr is None or tgt_addr is None:
            return

        if source.selected_product_count == 0:
            self.status_lbl.setText(f"{src_addr.slot_name} is already empty.")
            return

        msg = (
            f"Move all {source.selected_product_count} product(s) from {src_addr.slot_name} into {tgt_addr.slot_name}?\n\n"
            f"The target's {target.selected_product_count} current product(s) will remain."
        )
        reply = QMessageBox.question(self, "Combine complete cell contents?", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            moved_count = self.database.combine_slot_contents(src_addr.slot_id, tgt_addr.slot_id)
        except Exception as error:
            QMessageBox.critical(self, "Error", f"Cells could not be combined: {error}")
            return

        message = f"Moved {moved_count} product(s) from {src_addr.slot_name} into {tgt_addr.slot_name}."
        self.on_changed.emit(message)
        self.refresh()
        self.status_lbl.setText(message)
