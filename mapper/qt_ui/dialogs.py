"""PyQt6 dialogs for stock quantity inputs and CSV column mappings."""

from __future__ import annotations

import re
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mapper.database import validate_stock_quantity


class StockQuantityDialog(QDialog):
    """Collect a separate manual quantity for every selected product."""

    def __init__(
        self,
        parent: QWidget | None,
        slot_name: str,
        products: list[tuple[str, str]],
        initial_quantities: dict[str, int | None] | None = None,
        *,
        title_text: str | None = None,
        destination_label: str | None = None,
        button_text: str = "Assign products",
        footer_text: str = "Press Commit on the main window to save staged changes.",
    ):
        super().__init__(parent)
        self.result: dict[str, int] | None = None
        self.products = products
        self.spinboxes: dict[str, QSpinBox] = {}

        self.setWindowTitle(title_text or f"Assign products to {slot_name}")
        self.resize(650, min(500, 200 + 40 * len(products)))
        self.setMinimumSize(540, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        dest_lbl = QLabel(destination_label or f"Destination: {slot_name}")
        dest_lbl.setStyleSheet("font-weight: 600; font-size: 14px; color: #1f2328;")
        layout.addWidget(dest_lbl)

        desc_lbl = QLabel("Enter each product's stock quantity (whole units, 0 or more).")
        desc_lbl.setStyleSheet("color: #4b5563;")
        layout.addWidget(desc_lbl)

        self.table = QTableWidget(len(products), 3)
        self.table.setHorizontalHeaderLabels(["Product ID", "Product Name", "Stock Qty"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)

        initial = initial_quantities or {}
        for row, (prod_id, prod_name) in enumerate(products):
            id_item = QTableWidgetItem(prod_id)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, id_item)

            name_item = QTableWidgetItem(prod_name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 1, name_item)

            spin = QSpinBox()
            spin.setRange(0, 999999)
            default_qty = initial.get(prod_id)
            spin.setValue(default_qty if default_qty is not None else 1)
            self.spinboxes[prod_id] = spin
            self.table.setCellWidget(row, 2, spin)

        layout.addWidget(self.table)

        footer_lbl = QLabel(footer_text)
        footer_lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(footer_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        confirm_btn = QPushButton(button_text)
        confirm_btn.setProperty("primary", "true")
        confirm_btn.clicked.connect(self.confirm)
        btn_box.addWidget(confirm_btn)

        layout.addLayout(btn_box)

    def confirm(self) -> None:
        result: dict[str, int] = {}
        for prod_id, spin in self.spinboxes.items():
            qty = spin.value()
            if qty < 0:
                QMessageBox.warning(self, "Invalid Quantity", f"Stock for {prod_id} must be 0 or more.")
                return
            result[prod_id] = qty
        self.result = result
        self.accept()


class ColumnMappingDialog(QDialog):
    """PyQt6 dialog for selecting CSV columns during import."""

    def __init__(self, parent: QWidget | None, headers: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Choose CSV Columns")
        self.setFixedSize(480, 260)
        self.result: tuple[int, int, int] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        desc = QLabel("Choose the three product columns to import. Other columns will be ignored.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #4b5563;")
        layout.addWidget(desc)

        # Form rows
        form = QVBoxLayout()
        form.setSpacing(8)

        # Product ID
        row1 = QHBoxLayout()
        lbl1 = QLabel("Product ID column:")
        lbl1.setFixedWidth(160)
        self.id_combo = QComboBox()
        self.id_combo.addItems(headers)
        row1.addWidget(lbl1)
        row1.addWidget(self.id_combo)
        form.addLayout(row1)

        # Product Name
        row2 = QHBoxLayout()
        lbl2 = QLabel("Product name column:")
        lbl2.setFixedWidth(160)
        self.name_combo = QComboBox()
        self.name_combo.addItems(headers)
        row2.addWidget(lbl2)
        row2.addWidget(self.name_combo)
        form.addLayout(row2)

        # Shortened Name
        row3 = QHBoxLayout()
        lbl3 = QLabel("Shortened name column:")
        lbl3.setFixedWidth(160)
        self.short_combo = QComboBox()
        self.short_combo.addItems(headers)
        row3.addWidget(lbl3)
        row3.addWidget(self.short_combo)
        form.addLayout(row3)

        layout.addLayout(form)

        # Pre-select matching headers
        normalized = [re.sub(r"[^a-z0-9]", "", h.casefold()) for h in headers]
        id_candidates = ("productid", "productcode", "sku", "itemid", "itemcode", "id", "code")
        name_candidates = ("productname", "itemname", "name", "description", "productdescription")
        short_name_candidates = (
            "shortenedname", "shortname", "labelname", "displayname", "abbreviatedname", "abbreviation"
        )

        id_idx = next((normalized.index(c) for c in id_candidates if c in normalized), 0)
        name_idx = next(
            (normalized.index(c) for c in name_candidates if c in normalized),
            1 if len(headers) > 1 else 0,
        )
        short_idx = next(
            (normalized.index(c) for c in short_name_candidates if c in normalized),
            2 if len(headers) > 2 else name_idx,
        )

        self.id_combo.setCurrentIndex(id_idx)
        self.name_combo.setCurrentIndex(name_idx)
        self.short_combo.setCurrentIndex(short_idx)

        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        import_btn = QPushButton("Import")
        import_btn.setProperty("primary", "true")
        import_btn.clicked.connect(self.confirm)
        btn_box.addWidget(import_btn)

        layout.addLayout(btn_box)

    def confirm(self) -> None:
        id_i = self.id_combo.currentIndex()
        name_i = self.name_combo.currentIndex()
        short_i = self.short_combo.currentIndex()

        if id_i < 0 or name_i < 0 or short_i < 0:
            QMessageBox.warning(self, "Columns Missing", "Please select all three columns.")
            return

        if len({id_i, name_i, short_i}) != 3:
            QMessageBox.warning(
                self,
                "Columns Duplicated",
                "Product ID, full name, and shortened name must use different columns.",
            )
            return

        self.result = (id_i, name_i, short_i)
        self.accept()
