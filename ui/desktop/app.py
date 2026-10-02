"""Application controller for shelf design, persistent queues, and web updates.

Layout lists remain ordered from the ground upward; views alone translate them
to screen coordinates. Address assignments are committed immediately, while
shelf-structure edits still use the explicit Commit action on tab 1.
"""

from __future__ import annotations

from collections import Counter
import tkinter as tk
from pathlib import Path
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any

from mapper.core.common import APP_TITLE, default_database_path
from mapper.features.web_upload import WebsiteUploader
from mapper.persistence.database import (
    OnHandProduct,
    Placement,
    ReturnedQueueProduct,
    SlotAddress,
    WarehouseDatabase,
)
from utils.barcode_scanner import BarcodeScanner

from .assignment_actions import AssignmentActions
from .catalog_actions import CatalogActions
from .cell_transfer_view import CellTransferView
from .designer import ShelfDesigner
from .exceptions_view import ExceptionsView
from .location_assignment_view import LocationAssignmentView
from .location_comparison_view import LocationComparisonView
from .primal_queue_view import PrimalQueueView
from .shelf_actions import ShelfActions
from .shelf_browser import ShelfBrowserView
from .state_actions import StateActions
from .web_actions import WebActions


class WarehouseMapperApp(
    ShelfActions, AssignmentActions, CatalogActions, WebActions, StateActions
):
    def __init__(self, root: tk.Tk, database_path: Path | None = None):
        self.root = root
        self.database = WarehouseDatabase(database_path or default_database_path())
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
        # Presence means the product is intentionally back in the working
        # queue. None preserves that intent for legacy products with unknown stock.
        self.transferred_stock: dict[str, int | None] = {}
        self.current_layout: list[int] = []
        self.preview_key: tuple[str, str, str] | None = None
        self.current_shelf_id: int | None = None
        self.selected_slot: str | None = None
        self.shelf_choices: dict[str, int] = {}
        self.search_after_id: str | None = None
        self.website_uploader = WebsiteUploader()
        self.chrome_connected = False
        self.chrome_connect_busy = False
        self.chrome_connect_after_id: str | None = None
        self.chrome_connect_events: Queue = Queue()
        self.web_upload_busy = False
        self.web_upload_action = "upload"
        self.web_upload_after_id: str | None = None
        self.web_upload_events: Queue = Queue()
        self.last_shift_transfer: dict[str, Any] | None = None
        self.queue_shift_clicks: int = 0
        self.queue_shift_timer: str | None = None
        self._preview_dirty = False

        self._configure_window()
        self._build_ui()
        self.reload_database_state(reload_catalog=True, reload_shelves=True)
        self.refresh_all_views()
        self.saved_editor_state = self._editor_state()

    def _configure_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("1320x820")
        self.root.minsize(1050, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")

            def fixed_map(option: str) -> list:
                return [
                    elm
                    for elm in style.map("Treeview", query_opt=option)
                    if elm[:2] != ("!disabled", "!selected")
                ]

            style.map(
                "Treeview",
                foreground=fixed_map("foreground"),
                background=fixed_map("background"),
            )
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure(
            "Commit.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 7)
        )
        style.configure(
            "WholeMode.Commit.TButton",
            font=("Segoe UI", 10, "bold italic"),
            foreground="#b45309",
            padding=(14, 7),
        )
        style.map(
            "WholeMode.Commit.TButton",
            foreground=[
                ("disabled", "#a0a0a0"),
                ("active", "#92400e"),
                ("!disabled", "#b45309"),
            ],
        )
        style.configure(
            "WholeMode.TButton",
            font=("Segoe UI", 9, "bold italic"),
            foreground="#b45309",
        )
        style.map(
            "WholeMode.TButton",
            foreground=[
                ("disabled", "#a0a0a0"),
                ("active", "#92400e"),
                ("!disabled", "#b45309"),
            ],
        )

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(8, 8))

        self.designer_tab = ttk.Frame(self.notebook)
        designer_controls = ttk.Frame(self.designer_tab, padding=(12, 8))
        designer_controls.pack(fill="x")
        ttk.Button(
            designer_controls,
            text="Import working products CSV",
            command=self.import_csv,
        ).pack(side="left")
        ttk.Button(
            designer_controls,
            text="Import full catalog CSV",
            command=self.import_catalog_csv,
        ).pack(side="left", padx=(6, 14))
        ttk.Button(designer_controls, text="New shelf", command=self.new_shelf).pack(
            side="left"
        )
        shelf_controls = ttk.Frame(self.designer_tab, padding=(12, 0, 12, 8))
        shelf_controls.pack(fill="x")
        ttk.Label(shelf_controls, text="Edit existing shelf:").pack(
            side="left", padx=(0, 5)
        )
        self.shelf_selector = ttk.Combobox(
            shelf_controls,
            state="readonly",
            width=30,
        )
        self.shelf_selector.pack(side="left")
        ttk.Button(
            shelf_controls,
            text="Load for editing",
            command=self.load_selected_shelf,
        ).pack(side="left", padx=(5, 0))
        self.delete_shelf_button = ttk.Button(
            shelf_controls,
            text="Delete shelf",
            command=self.delete_selected_shelf,
        )
        self.delete_shelf_button.pack(side="left", padx=(5, 0))
        ttk.Button(
            designer_controls,
            text="Commit shelf design",
            style="Commit.TButton",
            command=self.commit_changes,
        ).pack(side="right")

        self.barcode_scanner = BarcodeScanner(self.root, self.on_global_barcode_scan)

        self.designer = ShelfDesigner(
            self.designer_tab,
            self.build_shelf_preview,
            self.can_resize_rows,
            self.on_rows_changed,
        )
        self.designer.pack(fill="both", expand=True)
        self.assignments = LocationAssignmentView(
            self.notebook,
            on_search=self.schedule_queue_refresh,
            on_queue_to_hand=self.move_selected_to_on_hand,
            on_catalog_to_queue=self.transfer_catalog_selection_to_queue,
            on_catalog_activate=self.activate_catalog_product,
            on_load_address=self.load_assignment_address,
            on_assign_address=self.assign_on_hand_to_address,
            on_dequeue_hand=self.dequeue_selected_on_hand,
            on_selected_to_hand=self.move_selected_address_to_on_hand,
            on_slot_to_hand=self.move_address_to_on_hand,
            on_modify_hand_stock=self.modify_on_hand_stock,
            on_modify_stock=self.modify_selected_stock,
            on_upload=self.upload_selected_product,
            on_modify_location=self.modify_selected_location,
            on_preview_shelf=self.preview_assignment_shelf,
            on_revert_shift=self.revert_latest_shift_transfer,
            on_whole_mode_change=self._on_whole_mode_change,
            barcode_scanner=self.barcode_scanner,
        )
        self.revert_button = self.assignments.revert_button
        self.notebook.add(self.designer_tab, text="1. Shelf Designer")
        self.notebook.add(self.assignments, text="2. Assign Locations")
        self.chrome_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.chrome_tab, text="Connect Chrome")
        self.primal_view = PrimalQueueView(
            self.notebook, self.database, barcode_scanner=self.barcode_scanner
        )
        self.lookup = self.primal_view
        self.notebook.add(self.primal_view, text="3. Primal Queue / Shelves")
        self.shelf_browser = ShelfBrowserView(self.notebook, self.database)
        self.notebook.add(self.shelf_browser, text="4. Browse Shelves")
        self.cell_transfer = CellTransferView(
            self.notebook,
            self.database,
            self.on_cell_transfer_changed,
            self.can_change_cells,
            on_modify_web=self.modify_cell_transfer_locations,
            barcode_scanner=self.barcode_scanner,
        )
        self.notebook.add(self.cell_transfer, text="5. Switch / Combine Cells")

        self.exceptions_view = ExceptionsView(
            self.notebook,
            self.database,
            status_text=getattr(self, "status_text", None),
            on_refresh_callback=self.on_exception_data_changed,
            barcode_scanner=self.barcode_scanner,
        )
        self.notebook.add(self.exceptions_view, text="6. Special Exceptions")

        self.location_comparison = LocationComparisonView(
            self.notebook, self.database, self.resync_web_locations
        )
        self.notebook.add(self.location_comparison, text="7. Web Location Sync")
        self._last_content_tab = str(self.designer_tab)

        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self.root.bind(
            "<FocusOut>",
            lambda _e: (
                hasattr(self, "assignments") and self.assignments.set_whole_mode(False)
            ),
            add="+",
        )

        self.status_text = tk.StringVar(value="Ready")
        self.exceptions_view.status_text = self.status_text
        ttk.Label(
            self.root,
            textvariable=self.status_text,
            relief="sunken",
            anchor="w",
            padding=(8, 3),
        ).pack(fill="x", side="bottom")

    def on_global_barcode_scan(self, barcode: str) -> None:
        """Route scanned barcode to the currently active tab."""
        current_tab = self.notebook.select()
        if not current_tab:
            return
        try:
            current_widget = self.notebook.nametowidget(current_tab)
        except Exception:
            return

        if hasattr(current_widget, "on_barcode_scan"):
            current_widget.on_barcode_scan(barcode)
        elif hasattr(current_widget, "_on_barcode_scan"):
            current_widget._on_barcode_scan(barcode)
        else:
            self.assignments.on_barcode_scan(barcode)

    def on_tab_changed(self, _event=None) -> None:
        if hasattr(self, "assignments"):
            self.assignments.set_whole_mode(False)
        current_tab = self.notebook.select()
        if current_tab == str(self.chrome_tab):
            self.notebook.select(self._last_content_tab)
            self.connect_chrome()
            return
        self._last_content_tab = current_tab
        if current_tab == str(self.assignments):
            self.refresh_address_contents()
            self.refresh_assignment_shelf_preview()
            self.assignments.focus_search()
        elif hasattr(self, "primal_view") and current_tab == str(self.primal_view):
            self.primal_view.refresh()
            self.primal_view.focus_search()
        elif current_tab == str(self.shelf_browser):
            if self.shelf_browser.current_shelf_id is not None:
                self.shelf_browser.refresh_loaded_contents()
            elif self._preview_dirty and self.preview_key:
                self.render_shelf()
                self._preview_dirty = False
        elif current_tab == str(self.cell_transfer):
            self.cell_transfer.refresh()
            self.cell_transfer.focus_search()
        elif hasattr(self, "exceptions_view") and current_tab == str(
            self.exceptions_view
        ):
            self.exceptions_view.refresh()
            self.exceptions_view.focus_search()
        elif hasattr(self, "location_comparison") and current_tab == str(
            self.location_comparison
        ):
            self.location_comparison.refresh()

    def refresh_assignment_shelf_preview(self) -> None:
        if self.assignments.hand_view.get() != "shelf":
            return
        key = getattr(self.assignments, "_shelf_preview_key", None)
        if key is None:
            return
        floor, side, shelf_code = key
        shelf_id = self.database.get_shelf_id(floor, shelf_code, side=side)
        if shelf_id is None:
            self.assignments.clear_shelf_preview("That shelf changed. Select it again.")
            return
        contents = self.database.get_shelf_contents(shelf_id)
        counts = Counter(item[2].slot_name for item in contents)
        for slot_name in self.assignments.shelf_slot_names:
            self.assignments.refresh_shelf_cell(slot_name, counts.get(slot_name, 0))

    def on_cell_transfer_changed(self, message: str, updates, slot_names) -> None:
        """Apply known location changes and refresh the two visible cells."""
        product_ids = set()
        for update in updates:
            product_ids.add(update.product_id)
        for slot_name in slot_names:
            address = self.database.get_slot_by_name(slot_name)
            if address is not None:
                product_ids.update(
                    pid for pid, _name, _placement
                    in self.database.get_slot_contents(address.slot_id)
                )
        self.reconcile_inventory_products(
            product_ids,
            affected_slots=slot_names,
            queue_changed=False,
            hand_changed=False,
        )
        self.status_text.set(message)

    def on_close(self) -> None:
        if getattr(self, "web_upload_busy", False) or getattr(
            self, "chrome_connect_busy", False
        ):
            messagebox.showinfo(
                "Browser task in progress",
                "Wait for the current Chrome connection or upload task before closing the mapper.",
                parent=self.root,
            )
            return
        if self.has_pending_changes():
            choice = messagebox.askyesnocancel(
                "Uncommitted changes",
                "Commit shelf and product changes before closing?",
            )
            if choice is None or (choice and not self.commit_changes()):
                return
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
        if getattr(self, "chrome_connect_after_id", None):
            self.root.after_cancel(self.chrome_connect_after_id)
        if getattr(self, "web_upload_after_id", None):
            self.root.after_cancel(self.web_upload_after_id)
        if hasattr(self, "website_uploader"):
            self.website_uploader.disconnect()
        self.root.destroy()
