"""Main Application Controller for the 100% Offline PyQt6 Desktop UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mapper.common import (
    APP_TITLE,
    MAX_VISIBLE_PRODUCTS,
    application_directory,
    clean_location_segment,
    make_slot_name,
    normalize_search,
)
from mapper.csv_import import read_csv
from mapper.database import (
    LayoutConflictError,
    OnHandProduct,
    Placement,
    ReturnedQueueProduct,
    SlotAddress,
    WarehouseDatabase,
)
from .assignment_view import LocationAssignmentView
from .cell_transfer_view import CellTransferView
from .designer_view import ShelfDesignerView
from .dialogs import ColumnMappingDialog, StockQuantityDialog
from .primal_queue_view import PrimalQueueView
from .shelf_browser_view import ShelfBrowserView
from .theme import INTELLI_J_STYLESHEET


class WarehouseMapperQtApp(QMainWindow):
    """Main desktop application window with 5 tabs and offline SQLite integration."""

    def __init__(self, database_path: Path | None = None):
        super().__init__()
        self.database = WarehouseDatabase(
            database_path or application_directory() / "warehouse_locations.db"
        )

        # In-memory caches
        self.products: dict[str, str] = {}
        self.product_shortened_names: dict[str, str] = {}
        self.product_search: dict[str, str] = {}
        self.catalog_products: dict[str, tuple[str, str]] = {}
        self.catalog_search: dict[str, str] = {}
        self.committed_locations: dict[str, str] = {}
        self.committed_placements: dict[str, Placement] = {}
        self.on_hand_products: dict[str, OnHandProduct] = {}
        self.returned_queue_products: dict[str, ReturnedQueueProduct] = {}
        self.selected_address: SlotAddress | None = None
        self.staged_assignments: dict[str, Placement] = {}
        self.pending_unassignments: set[str] = set()
        self.transferred_stock: dict[str, int | None] = {}
        self.current_layout: list[int] = []
        self.preview_key: tuple[str, str, str] | None = None
        self.current_shelf_id: int | None = None
        self.selected_slot: str | None = None
        self.shelf_choices: dict[str, int] = {}

        self._configure_window()
        self._build_ui()
        self.reload_database_state(reload_catalog=True)

    def _configure_window(self):
        self.setWindowTitle(APP_TITLE)
        self.resize(1380, 860)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(INTELLI_J_STYLESHEET)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 4)
        layout.setSpacing(6)

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # 1. Shelf Designer
        self.designer_view = ShelfDesignerView(
            self,
            on_build=self.build_shelf_preview,
            can_resize=self.can_resize_rows,
            on_commit=self.commit_changes,
            on_new_shelf=self.new_shelf,
            on_load_shelf=self.load_selected_shelf,
            on_import_csv=self.import_csv,
            on_import_catalog_csv=self.import_catalog_csv,
        )
        self.tabs.addTab(self.designer_view, "1. Shelf Designer")

        # 2. Location Assignment
        self.assignments_view = LocationAssignmentView(self)
        self.assignments_view.search_changed.connect(self._on_search_filter)
        self.assignments_view.queue_to_hand_requested.connect(self.move_selected_to_on_hand)
        self.assignments_view.catalog_to_queue_requested.connect(self.transfer_catalog_to_queue)
        self.assignments_view.load_address_requested.connect(self.load_assignment_address)
        self.assignments_view.assign_address_requested.connect(self.assign_on_hand_to_address)
        self.assignments_view.dequeue_hand_requested.connect(self.dequeue_selected_on_hand)
        self.assignments_view.slot_to_hand_requested.connect(self.move_selected_address_to_on_hand)
        self.assignments_view.remove_from_slot_requested.connect(self.remove_from_slot)
        self.tabs.addTab(self.assignments_view, "2. Assign Locations")

        # 3. Primal Queue / Shelves
        self.primal_view = PrimalQueueView(self, self.database)
        self.tabs.addTab(self.primal_view, "3. Primal Queue / Shelves")

        # 4. Shelf Browser
        self.shelf_browser = ShelfBrowserView(self, self.database)
        self.tabs.addTab(self.shelf_browser, "4. Browse Shelves")

        # 5. Cell Transfer
        self.cell_transfer = CellTransferView(
            self,
            self.database,
            can_change_cells=self.can_change_cells,
        )
        self.cell_transfer.on_changed.connect(self._on_cell_transfer_changed)
        self.tabs.addTab(self.cell_transfer, "5. Switch / Combine Cells")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_msg = QLabel("Ready")
        self.status_bar.addWidget(self.status_msg, stretch=1)

        self.db_chip = QLabel("warehouse_locations.db")
        self.db_chip.setProperty("chip", "true")
        self.status_bar.addPermanentWidget(self.db_chip)

        self.catalog_count_chip = QLabel("Catalog: 0")
        self.catalog_count_chip.setProperty("chip", "true")
        self.status_bar.addPermanentWidget(self.catalog_count_chip)

        self.queue_count_chip = QLabel("Queue: 0")
        self.queue_count_chip.setProperty("chip-warning", "true")
        self.status_bar.addPermanentWidget(self.queue_count_chip)

        self.engine_chip = QLabel("Qt 6 Native (Offline)")
        self.engine_chip.setProperty("chip-primary", "true")
        self.status_bar.addPermanentWidget(self.engine_chip)

    def set_status(self, message: str):
        self.status_msg.setText(message)

    def _on_tab_changed(self, index: int):
        if index == 2:
            self.primal_view.refresh()
        elif index == 3:
            if self.shelf_browser.current_shelf_id is None:
                self.shelf_browser.refresh()
            else:
                self.shelf_browser.show_saved_shelf(self.shelf_browser.current_shelf_id)
        elif index == 4:
            self.cell_transfer.refresh()

    def _on_cell_transfer_changed(self, message: str):
        self.reload_database_state()
        self.set_status(message)

    def can_change_cells(self) -> bool:
        if not self.has_pending_changes():
            return True
        QMessageBox.information(
            self,
            "Pending Changes",
            "Commit or discard the pending Shelf Designer changes before switching or combining saved cells.",
        )
        return False

    def has_pending_changes(self) -> bool:
        return bool(self.staged_assignments or self.pending_unassignments)

    def can_resize_rows(self, target_row_count: int) -> bool:
        return True

    def reload_database_state(self, reload_catalog: bool = False):
        product_rows = self.database.get_product_records()
        self.products = {pid: name for pid, name, _ in product_rows}
        self.product_shortened_names = {pid: sname for pid, _, sname in product_rows}
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

        self.committed_placements = self.database.get_placement_details()
        self.committed_locations = {pid: plc.slot_name for pid, plc in self.committed_placements.items()}
        self.on_hand_products = self.database.get_on_hand_products()
        self.returned_queue_products = self.database.get_returned_queue_products()

        self._refresh_shelf_selector()
        self.refresh_all_views()

        # Update status chips
        self.catalog_count_chip.setText(f"Catalog: {len(self.catalog_products):,}")
        self.queue_count_chip.setText(f"Queue: {len(self.products):,}")

    def _refresh_shelf_selector(self):
        choices = self.database.list_shelves()
        self.shelf_choices = {
            f"Floor {floor} — Side {side} — Shelf {shelf_code}": shelf_id
            for shelf_id, floor, side, shelf_code in choices
        }

        self.designer_view.shelf_selector.blockSignals(True)
        self.designer_view.shelf_selector.clear()
        self.designer_view.shelf_selector.addItem("— Select shelf —", None)
        for label, s_id in self.shelf_choices.items():
            self.designer_view.shelf_selector.addItem(label, s_id)
        self.designer_view.shelf_selector.blockSignals(False)

        if hasattr(self, "shelf_browser"):
            self.shelf_browser.refresh()

    def refresh_all_views(self):
        self._refresh_queue_table()
        self._refresh_catalog_table()
        self._refresh_on_hand_table()
        self._refresh_address_contents()

    def _on_search_filter(self, _text: str):
        self._refresh_queue_table()
        self._refresh_catalog_table()

    def _refresh_queue_table(self):
        raw = self.assignments_view.queue_search.text().strip()
        query = normalize_search(raw)

        queue_items = []
        for pid in self.products:
            if not query or query in self.product_search[pid]:
                ret = self.returned_queue_products.get(pid)
                created_at = ret.returned_at if ret else ""
                stock_qty = ret.stock_qty if ret and ret.stock_qty is not None else 1
                queue_items.append({
                    "product_id": pid,
                    "name": self.products[pid],
                    "stock_qty": stock_qty,
                    "created_at": created_at,
                })

        queue_items.sort(key=lambda p: (
            p["product_id"].casefold() != raw.casefold(),
            p["product_id"] not in self.returned_queue_products,
            p["product_id"].casefold(),
        ))

        ret_ids = set(self.returned_queue_products.keys())
        self.assignments_view.populate_queue(queue_items[:MAX_VISIBLE_PRODUCTS], returned_ids=ret_ids)

    def _refresh_catalog_table(self):
        raw = self.assignments_view.queue_search.text().strip()
        query = normalize_search(raw)

        catalog_items = []
        for pid, (name, _) in self.catalog_products.items():
            if not query or query in self.catalog_search[pid]:
                plc = self.committed_placements.get(pid)
                loc = plc.slot_name if plc else ""
                qty = plc.stock_qty if plc and plc.stock_qty is not None else 1
                catalog_items.append({
                    "product_id": pid,
                    "name": name,
                    "stock_qty": qty,
                    "loc_id": loc,
                })

        catalog_items.sort(key=lambda p: (
            p["product_id"].casefold() != raw.casefold(),
            p["loc_id"] == "",
            p["product_id"].casefold(),
        ))

        self.assignments_view.populate_catalog(catalog_items[:MAX_VISIBLE_PRODUCTS])

    def _refresh_on_hand_table(self):
        hand_items = []
        for pid, item in self.on_hand_products.items():
            hand_items.append({
                "product_id": pid,
                "name": self.products.get(pid, self.catalog_products.get(pid, ("", ""))[0]),
                "stock_qty": item.stock_qty if item.stock_qty is not None else 1,
            })
        self.assignments_view.populate_on_hand(hand_items)

    def _refresh_address_contents(self):
        if not self.selected_address:
            self.assignments_view.populate_slot_contents(None, [])
            return

        contents = self.database.get_slot_contents(self.selected_address.slot_id)
        slot_items = []
        for pid, name, plc in contents:
            slot_items.append({
                "product_id": pid,
                "name": name,
                "stock_qty": plc.stock_qty if plc.stock_qty is not None else 1,
                "assigned_at": plc.assigned_at or "",
            })
        self.assignments_view.populate_slot_contents(self.selected_address.slot_name, slot_items)

    # Actions: Assign & Queues
    def move_selected_to_on_hand(self, product_ids: list[str]):
        if not product_ids:
            return

        dialog = StockQuantityDialog(
            self,
            "On-hand queue",
            [(pid, self.products.get(pid, "")) for pid in product_ids],
            initial_quantities={
                pid: self.returned_queue_products[pid].stock_qty
                for pid in product_ids
                if pid in self.returned_queue_products
            },
            title_text="Move products to on-hand",
            destination_label="Persistent on-hand batch",
            button_text="Move to on-hand",
            footer_text="This move is saved to SQLite immediately.",
        )
        if dialog.exec() != StockQuantityDialog.DialogCode.Accepted or not dialog.result:
            return

        queued_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            self.database.add_to_on_hand(dialog.result, queued_at)
        except Exception as err:
            QMessageBox.critical(self, "Error", f"Could not update on-hand: {err}")
            return

        self.reload_database_state()
        self.assignments_view.log_activity(f"Moved {len(dialog.result)} product(s) to on-hand.")
        self.set_status(f"Moved {len(dialog.result)} product(s) to on-hand.")

    def transfer_catalog_to_queue(self, product_ids: list[str]):
        if not product_ids:
            return

        records = {}
        for pid in product_ids:
            if pid in self.catalog_products and pid not in self.products:
                name, shortened = self.catalog_products[pid]
                records[pid] = (name, shortened)

        if records:
            self.database.import_products(records)

        self.reload_database_state()
        self.assignments_view.log_activity(f"Transferred {len(product_ids)} product(s) from catalog to queue.")
        self.set_status(f"Transferred {len(product_ids)} product(s) to queue.")

    def load_assignment_address(self, floor: str, side: str, shelf: str, row: int, slot: int):
        address = self.database.get_slot_address(floor, side, shelf, row, slot)
        if not address:
            self.selected_address = None
            self.assignments_view.target_badge.setText(f"Target: Floor {floor} / Side {side} / {shelf} / R{row}-S{slot} (NOT FOUND)")
            self.assignments_view.target_badge.setStyleSheet("font-weight: 700; color: #dc2626; background-color: #fee2e2; padding: 4px 8px; border-radius: 3px;")
            self.assignments_view.populate_slot_contents(None, [])
            QMessageBox.warning(self, "Address Not Found", f"No shelf slot at Floor {floor} / Side {side} / Shelf {shelf} / Row {row} / Slot {slot}.")
            return

        self.selected_address = address
        self.assignments_view.target_badge.setText(f"Target: {address.slot_name}")
        self.assignments_view.target_badge.setStyleSheet("font-weight: 700; color: #1d4ed8; background-color: #dbeafe; padding: 4px 8px; border-radius: 3px;")
        self._refresh_address_contents()
        self.set_status(f"Loaded {address.slot_name}.")

    def assign_on_hand_to_address(self):
        if not self.selected_address:
            QMessageBox.information(self, "No Address Loaded", "Enter and Load a valid shelf address first.")
            return

        selected_rows = self.assignments_view.hand_table.selectionModel().selectedRows()
        if not selected_rows:
            product_ids = list(self.on_hand_products.keys())
        else:
            product_ids = [self.assignments_view.hand_table.item(r.row(), 0).text() for r in selected_rows]

        if not product_ids:
            QMessageBox.information(self, "Empty Queue", "No products selected or available in on-hand queue.")
            return

        address = self.selected_address
        assigned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            moved = self.database.assign_on_hand_to_slot(address.slot_id, assigned_at, product_ids)
        except Exception as err:
            QMessageBox.critical(self, "Assignment Failed", f"Failed to assign: {err}")
            return

        self.reload_database_state()
        self.assignments_view.log_activity(f"Assigned {moved} product(s) to {address.slot_name}.")
        self.set_status(f"Assigned {moved} product(s) to {address.slot_name}.")

    def dequeue_selected_on_hand(self, product_ids: list[str]):
        if not product_ids:
            return
        try:
            self.database.remove_from_on_hand(product_ids)
        except Exception as err:
            QMessageBox.critical(self, "Error", f"Failed to clear on-hand: {err}")
            return

        self.reload_database_state()
        self.assignments_view.log_activity(f"Cleared {len(product_ids)} product(s) from on-hand.")
        self.set_status(f"Cleared {len(product_ids)} product(s) from on-hand.")

    def move_selected_address_to_on_hand(self, product_ids: list[str]):
        if not self.selected_address or not product_ids:
            return

        queued_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            moved = self.database.move_slot_to_on_hand(self.selected_address.slot_id, queued_at, product_ids)
        except Exception as err:
            QMessageBox.critical(self, "Error", f"Transfer failed: {err}")
            return

        self.reload_database_state()
        self.assignments_view.log_activity(f"Moved {moved} product(s) from {self.selected_address.slot_name} to on-hand.")
        self.set_status(f"Moved {moved} product(s) from {self.selected_address.slot_name} to on-hand.")

    def remove_from_slot(self, product_ids: list[str]):
        if not self.selected_address or not product_ids:
            return

        reply = QMessageBox.question(
            self,
            "Remove Products",
            f"Remove {len(product_ids)} product(s) from {self.selected_address.slot_name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self.database.remove_placements(product_ids)
        except Exception as err:
            QMessageBox.critical(self, "Error", f"Failed to remove products: {err}")
            return

        self.reload_database_state()
        self.assignments_view.log_activity(f"Removed {len(product_ids)} product(s) from {self.selected_address.slot_name}.")
        self.set_status(f"Removed {len(product_ids)} product(s) from {self.selected_address.slot_name}.")

    # Tab 1: Shelf Designer Operations
    def build_shelf_preview(self) -> bool:
        validated = self.designer_view.validated_layout()
        if not validated:
            return False

        floor, side, shelf_code, layout = validated
        self.current_layout = layout
        self.preview_key = (floor, side, shelf_code)

        self.designer_view.visualizer.render_shelf(
            floor=floor,
            side=side,
            shelf_code=shelf_code,
            layout=layout,
            slot_counts={},
            selected_slot=None,
        )
        self.set_status("Shelf preview updated. Click 'Commit shelf design' to save to SQLite.")
        return True

    def new_shelf(self):
        self.current_shelf_id = None
        self.preview_key = None
        self.designer_view.set_metadata("1", "1", "A", [10, 10, 10])
        self.designer_view.visualizer.clear()
        self.set_status("Started new shelf design.")

    def load_selected_shelf(self):
        shelf_id = self.designer_view.shelf_selector.currentData()
        if not shelf_id:
            QMessageBox.information(self, "Choose Shelf", "Select an existing shelf to load.")
            return

        try:
            floor, side, shelf_code, layout = self.database.get_shelf(shelf_id)
            contents = self.database.get_shelf_contents(shelf_id)
        except Exception as err:
            QMessageBox.critical(self, "Error", f"Failed to load shelf: {err}")
            return

        self.current_shelf_id = shelf_id
        self.preview_key = (floor, side, shelf_code)
        self.current_layout = layout
        self.designer_view.set_metadata(floor, side, shelf_code, layout)

        slot_counts: dict[str, tuple[int, int]] = {}
        for _, _, plc in contents:
            saved, staged = slot_counts.get(plc.slot_name, (0, 0))
            slot_counts[plc.slot_name] = (saved + 1, staged)

        self.designer_view.visualizer.render_shelf(
            floor=floor,
            side=side,
            shelf_code=shelf_code,
            layout=layout,
            slot_counts=slot_counts,
        )
        self.set_status(f"Loaded shelf {shelf_code} for editing.")

    def commit_changes(self):
        validated = self.designer_view.validated_layout()
        if not validated:
            return

        floor, side, shelf_code, layout = validated
        try:
            shelf_id = self.database.commit_shelf(
                floor=floor,
                shelf_code=shelf_code,
                layout=layout,
                staged_assignments=self.staged_assignments,
                pending_unassignments=self.pending_unassignments,
                side=side,
                shelf_id=self.current_shelf_id,
            )
        except LayoutConflictError as err:
            QMessageBox.warning(self, "Layout Conflict", str(err))
            return
        except Exception as err:
            QMessageBox.critical(self, "Save Error", f"Could not commit shelf layout: {err}")
            return

        self.current_shelf_id = shelf_id
        self.reload_database_state()
        self.load_selected_shelf()
        QMessageBox.information(self, "Shelf Committed", f"Successfully saved Floor {floor} / Side {side} / Shelf {shelf_code} to SQLite.")
        self.set_status("Shelf design committed successfully.")

    # CSV Import Handling
    def import_csv(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Import Working Products CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not filepath:
            return

        try:
            headers, rows = read_csv(Path(filepath))
        except Exception as err:
            QMessageBox.critical(self, "Import Failed", f"Could not read CSV file:\n{err}")
            return

        dialog = ColumnMappingDialog(self, headers)
        if dialog.exec() != ColumnMappingDialog.DialogCode.Accepted or not dialog.result:
            return

        id_col, name_col, short_col = dialog.result
        records: dict[str, tuple[str, str]] = {}
        for row in rows:
            if len(row) > max(id_col, name_col, short_col):
                pid = row[id_col].strip()
                name = row[name_col].strip()
                short = row[short_col].strip()
                if pid and name:
                    records[pid] = (name, short)

        if records:
            inserted, updated = self.database.import_products(records)
            self.reload_database_state()
            QMessageBox.information(self, "Import Complete", f"Imported {len(records):,} products ({inserted} new, {updated} updated).")
            self.set_status(f"Imported {len(records):,} products from CSV.")

    def import_catalog_csv(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Import Full Catalog CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not filepath:
            return

        try:
            headers, rows = read_csv(Path(filepath))
        except Exception as err:
            QMessageBox.critical(self, "Import Failed", f"Could not read CSV file:\n{err}")
            return

        dialog = ColumnMappingDialog(self, headers)
        if dialog.exec() != ColumnMappingDialog.DialogCode.Accepted or not dialog.result:
            return

        id_col, name_col, short_col = dialog.result
        records: dict[str, tuple[str, str]] = {}
        for row in rows:
            if len(row) > max(id_col, name_col, short_col):
                pid = row[id_col].strip()
                name = row[name_col].strip()
                short = row[short_col].strip()
                if pid and name:
                    records[pid] = (name, short)

        if records:
            inserted, updated = self.database.import_catalog_products(records)
            self.reload_database_state(reload_catalog=True)
            QMessageBox.information(self, "Import Complete", f"Imported {len(records):,} catalog products ({inserted} new, {updated} updated).")
            self.set_status(f"Imported {len(records):,} catalog products.")


def run_qt_app(database_path: Path | None = None) -> None:
    """Launch the 100% offline PyQt6 desktop application."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = WarehouseMapperQtApp(database_path)
    window.show()
    sys.exit(app.exec())
