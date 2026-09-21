"""PyQt6 Tab 4: Shelf Browser view for inspecting committed shelves and slot contents."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mapper.database import Placement, WarehouseDatabase
from .designer_view import ShelfVisualizerWidget


class ShelfBrowserView(QWidget):
    """Tab 4: Read-only shelf browser with 2D interactive grid and slot inspector."""

    def __init__(self, parent: QWidget | None, database: WarehouseDatabase):
        super().__init__(parent)
        self.database = database
        self.shelf_choices: dict[str, int] = {}
        self.current_shelf_id: int | None = None
        self.current_contents: list[tuple[str, str, Placement]] = []
        self.selected_slot_name: str | None = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # Top Bar
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Existing shelf:"))
        self.shelf_combo = QComboBox()
        self.shelf_combo.setFixedWidth(300)
        self.shelf_combo.currentIndexChanged.connect(self._on_shelf_selected)
        top_bar.addWidget(self.shelf_combo)

        self.load_btn = QPushButton("Load shelf")
        self.load_btn.setProperty("primary", "true")
        self.load_btn.clicked.connect(self.load_selected)
        top_bar.addWidget(self.load_btn)

        self.refresh_btn = QPushButton("Refresh list")
        self.refresh_btn.clicked.connect(self.refresh)
        top_bar.addWidget(self.refresh_btn)

        top_bar.addStretch()

        mode_lbl = QLabel("Read-only view")
        mode_lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
        top_bar.addWidget(mode_lbl)

        main_layout.addLayout(top_bar)

        # Main Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Visualizer
        left_box = QGroupBox("Shelf Front View")
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(8, 14, 8, 8)
        self.visualizer = ShelfVisualizerWidget()
        self.visualizer.slot_clicked.connect(self.select_slot)
        left_layout.addWidget(self.visualizer)
        splitter.addWidget(left_box)

        # Right: Slot Contents Table
        right_box = QGroupBox("Slot Contents")
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(8, 14, 8, 8)
        right_layout.setSpacing(8)

        self.slot_header = QLabel("Slot: (No slot selected)")
        self.slot_header.setStyleSheet("font-weight: 700; color: #1f2328; font-size: 13px; font-family: 'JetBrains Mono', monospace;")
        right_layout.addWidget(self.slot_header)

        self.contents_table = QTableWidget(0, 4)
        self.contents_table.setHorizontalHeaderLabels(["Product ID", "Title", "Stock", "Assigned Date"])
        self.contents_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.contents_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.contents_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.contents_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.contents_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.contents_table)

        splitter.addWidget(right_box)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

    def refresh(self, select_shelf_id: int | None = None):
        choices = self.database.list_shelves()
        self.shelf_choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in choices
        }

        self.shelf_combo.blockSignals(True)
        self.shelf_combo.clear()
        self.shelf_combo.addItem("— Select a shelf —", None)
        for label, s_id in self.shelf_choices.items():
            self.shelf_combo.addItem(label, s_id)
        self.shelf_combo.blockSignals(False)

        target = select_shelf_id or self.current_shelf_id
        if target:
            idx = self.shelf_combo.findData(target)
            if idx > 0:
                self.shelf_combo.setCurrentIndex(idx)
                self.show_saved_shelf(target)
            else:
                self.current_shelf_id = None
                self.visualizer.clear()
        else:
            self.visualizer.clear()

    def _on_shelf_selected(self, index: int):
        shelf_id = self.shelf_combo.itemData(index)
        if shelf_id:
            self.show_saved_shelf(shelf_id)
        else:
            self.current_shelf_id = None
            self.visualizer.clear()
            self.contents_table.setRowCount(0)
            self.slot_header.setText("Slot: (No slot selected)")

    def load_selected(self):
        shelf_id = self.shelf_combo.currentData()
        if not shelf_id:
            QMessageBox.information(self, "Choose a shelf", "Select an existing shelf first.")
            return
        self.show_saved_shelf(shelf_id)

    def show_saved_shelf(self, shelf_id: int):
        try:
            floor, side, shelf_code, layout = self.database.get_shelf(shelf_id)
            contents = self.database.get_shelf_contents(shelf_id)
        except Exception as err:
            QMessageBox.warning(self, "Load Error", f"Failed to load shelf: {err}")
            return

        self.current_shelf_id = shelf_id
        self.current_contents = contents

        # Calculate slot counts
        slot_counts: dict[str, tuple[int, int]] = {}
        for _, _, placement in contents:
            s_name = placement.slot_name
            saved, staged = slot_counts.get(s_name, (0, 0))
            slot_counts[s_name] = (saved + 1, staged)

        self.visualizer.render_shelf(
            floor=floor,
            side=side,
            shelf_code=shelf_code,
            layout=layout,
            slot_counts=slot_counts,
            selected_slot=self.selected_slot_name,
        )

        if self.selected_slot_name:
            self.select_slot(self.selected_slot_name)
        else:
            self.slot_header.setText("Slot: (Click a cell to inspect)")
            self.contents_table.setRowCount(0)

    def select_slot(self, slot_name: str):
        self.selected_slot_name = slot_name
        self.slot_header.setText(f"Slot: {slot_name}")
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
            item3 = QTableWidgetItem(plc.assigned_at or "")

            self.contents_table.setItem(row, 0, item0)
            self.contents_table.setItem(row, 1, item1)
            self.contents_table.setItem(row, 2, item2)
            self.contents_table.setItem(row, 3, item3)
