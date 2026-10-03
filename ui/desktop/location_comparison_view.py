"""Tab 7: inspect KiotViet export differences and resync saved locations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mapper.persistence.database import WarehouseDatabase
from mapper.core.common import data_directory
from mapper.features.location_comparison import (
    LocationDifference,
    compare_locations,
    export_comparison,
    location_parts,
    read_web_locations,
    suggested_columns,
)
from mapper.features.web_upload import LocationUpdate
from mapper.features.kiotviet_settings import MAX_UPLOAD_TABS, load_settings, save_settings


class WorkbookColumnDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, workbook):
        super().__init__(parent)
        self.workbook = workbook
        self.result: tuple[str, int, int, int] | None = None
        self.title("Choose KiotViet Excel columns")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text="Choose the worksheet, header row, and two columns from the export.").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 10)
        )
        ttk.Label(self, text="Worksheet").grid(row=1, column=0, sticky="w", padx=14, pady=5)
        self.sheet = ttk.Combobox(self, values=workbook.sheetnames, state="readonly", width=42)
        self.sheet.grid(row=1, column=1, padx=(0, 14), pady=5)
        self.sheet.current(0)
        self.sheet.bind("<<ComboboxSelected>>", self._update_columns)

        ttk.Label(self, text="Header row").grid(row=2, column=0, sticky="w", padx=14, pady=5)
        self.header_row = tk.IntVar(self, value=1)
        row_input = ttk.Spinbox(self, from_=1, to=100, width=7, textvariable=self.header_row)
        row_input.grid(row=2, column=1, sticky="w", pady=5)
        row_input.bind("<FocusOut>", self._update_columns)
        row_input.bind("<Return>", self._update_columns)

        ttk.Label(self, text="Product ID column").grid(row=3, column=0, sticky="w", padx=14, pady=5)
        self.product_column = ttk.Combobox(self, state="readonly", width=42)
        self.product_column.grid(row=3, column=1, padx=(0, 14), pady=5)
        ttk.Label(self, text="Website location column").grid(row=4, column=0, sticky="w", padx=14, pady=5)
        self.location_column = ttk.Combobox(self, state="readonly", width=42)
        self.location_column.grid(row=4, column=1, padx=(0, 14), pady=5)

        buttons = ttk.Frame(self)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", padx=14, pady=14)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Import", command=self._confirm).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._suggest_header_row()
        self._update_columns()
        self.wait_visibility()
        self.focus_set()

    def _suggest_header_row(self) -> None:
        for sheet_name in self.workbook.sheetnames:
            worksheet = self.workbook[sheet_name]
            for row_number, row in enumerate(worksheet.iter_rows(max_row=15, values_only=True), 1):
                product, location = suggested_columns(list(row))
                if product != location and row[product] and row[location]:
                    from mapper.features.location_comparison import _plain_header, ID_HEADERS, LOCATION_HEADERS
                    if (_plain_header(row[product]) in ID_HEADERS
                            and _plain_header(row[location]) in LOCATION_HEADERS):
                        self.sheet.set(sheet_name)
                        self.header_row.set(row_number)
                        return

    def _update_columns(self, _event=None) -> None:
        try:
            row_number = self.header_row.get()
            if row_number < 1:
                return
            worksheet = self.workbook[self.sheet.get()]
            row = next(worksheet.iter_rows(min_row=row_number, max_row=row_number, values_only=True))
        except (ValueError, KeyError, StopIteration, tk.TclError):
            return
        labels = [f"{index + 1}: {str(value).strip() if value is not None else '(blank)'}"
                  for index, value in enumerate(row)]
        self.product_column.configure(values=labels)
        self.location_column.configure(values=labels)
        if labels:
            product, location = suggested_columns(list(row))
            self.product_column.current(product)
            self.location_column.current(location)

    def _confirm(self) -> None:
        try:
            header_row = self.header_row.get()
        except tk.TclError:
            header_row = 0
        product = self.product_column.current()
        location = self.location_column.current()
        if header_row < 1 or product < 0 or location < 0 or product == location:
            messagebox.showerror(
                "Choose columns", "Choose a valid header row and two different columns.", parent=self
            )
            return
        self.result = (self.sheet.get(), header_row, product, location)
        self.destroy()


class LocationComparisonView(ttk.Frame):
    def __init__(self, parent: tk.Misc, database: WarehouseDatabase, on_resync, on_settings_changed=None):
        super().__init__(parent, padding=10)
        self.database = database
        self.on_resync = on_resync
        self.on_settings_changed = on_settings_changed
        self.web_locations: dict[str, str] | None = None
        self.imported_path: Path | None = None
        self.differences: list[LocationDifference] = []
        self.missing_ids: list[str] = []
        self.resynced: dict[str, str] = {}
        self.busy = False
        self._comparison_busy = False
        self._web_busy = False
        self._comparison_events: Queue = Queue()
        self._comparison_action = ""
        self._loading_after_id: str | None = None
        self._loading_position = 0
        self._loading_direction = 1
        self.summary = tk.StringVar(self, value="Import a KiotViet Excel export to compare locations.")
        self.file_label = tk.StringVar(self, value="No web data imported")
        self.progress = tk.StringVar(self, value="")
        try:
            url, tabs = load_settings()
        except ValueError as error:
            url, tabs = "", 1
            self.progress.set(str(error))
        self.store_url = tk.StringVar(self, value=url)
        self.tab_count = tk.StringVar(self, value=str(tabs))
        self._saved_settings = (url, tabs)
        self._build_ui()

    def _build_ui(self) -> None:
        ttk.Label(self, text="Web Location Comparison", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            self,
            text="Compare KiotViet locations with saved local shelf locations. Local locations are the true values.",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 10))
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(0, 8))
        actions.columnconfigure(1, weight=1)
        ttk.Label(actions, text="KiotViet URL").grid(row=0, column=0)
        self.url_entry = ttk.Entry(actions, textvariable=self.store_url)
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        ttk.Label(actions, text="Upload tabs").grid(row=0, column=2)
        self.tabs_input = ttk.Spinbox(
            actions, from_=1, to=MAX_UPLOAD_TABS, width=4, textvariable=self.tab_count,
            command=self._autosave_settings,
        )
        self.tabs_input.grid(row=0, column=3, padx=(6, 8))
        self.save_settings_button = ttk.Button(actions, text="Save settings", command=self.save_browser_settings)
        self.save_settings_button.grid(row=0, column=4)
        for widget in (self.url_entry, self.tabs_input):
            widget.bind("<FocusOut>", self._autosave_settings)
            widget.bind("<Return>", lambda _event: self.save_browser_settings())
        self.import_button = ttk.Button(actions, text="Import Web's Data", command=self.import_excel)
        self.import_button.grid(row=0, column=5, padx=(8, 0))
        self.resync_button = ttk.Button(actions, text="Web resync", command=self.resync, state="disabled")
        self.resync_button.grid(row=0, column=6, padx=(8, 0))
        self.export_button = ttk.Button(
            actions, text="Export comparison excel", command=self.export_excel, state="disabled"
        )
        self.export_button.grid(row=0, column=7, padx=(8, 0))
        self.refresh_button = ttk.Button(actions, text="Refresh comparison", command=self.refresh)
        self.refresh_button.grid(row=0, column=8, padx=(8, 0))
        loading_strip = ttk.Frame(self, height=4)
        loading_strip.pack(fill="x", pady=(0, 8))
        self.loading_bar = tk.Canvas(
            loading_strip, width=170, height=4, bd=0, highlightthickness=0, background="#e4e9ef"
        )
        self.loading_segment = self.loading_bar.create_rectangle(
            0, 0, 44, 4, fill="#0969da", outline=""
        )
        ttk.Label(self, textvariable=self.file_label, foreground="#555555").pack(anchor="w")
        ttk.Label(self, textvariable=self.summary).pack(anchor="w", pady=(4, 8))
        ttk.Label(self, textvariable=self.progress, foreground="#0969da").pack(
            anchor="w", pady=(0, 6)
        )

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            frame,
            columns=("product_id", "wrong_location", "true_location", "status"),
            show="headings",
        )
        for column, heading, width in (
            ("product_id", "Product ID", 190),
            ("wrong_location", "Website location", 260),
            ("true_location", "Local location", 260),
            ("status", "Status", 230),
        ):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, minwidth=100, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.tag_configure("missing", foreground="#777777")
        self.tree.tag_configure("resynced", foreground="#217046")
        ttk.Label(
            self,
            text="Web resync replaces each website location set with all saved local locations. Missing export IDs cannot be compared; an empty local set clears the website locations.",
            foreground="#555555",
            wraplength=900,
        ).pack(anchor="w", pady=(8, 0))

    def save_browser_settings(self, *, quiet=False) -> bool:
        if self._web_busy:
            return False
        try:
            settings = save_settings(self.store_url.get(), self.tab_count.get())
        except (ValueError, OSError) as error:
            self.progress.set(str(error))
            if not quiet:
                messagebox.showerror("KiotViet settings", str(error), parent=self)
            return False
        self.store_url.set(settings[0])
        self.tab_count.set(str(settings[1]))
        previous_url = self._saved_settings[0]
        self._saved_settings = settings
        if self.on_settings_changed and previous_url != settings[0]:
            self.on_settings_changed(settings[0])
        if not quiet:
            self.progress.set("KiotViet URL and upload tab count saved.")
        return True

    def _autosave_settings(self, _event=None) -> None:
        if self.store_url.get().strip() and not self._web_busy:
            self.save_browser_settings(quiet=True)

    def _local_locations(self) -> dict[str, list[str]]:
        local: dict[str, list[str]] = {}
        registered_ids = {row[0] for row in self.database.get_product_records()}
        registered_ids.update(row[0] for row in self.database.get_catalog_products())
        for product_id, slot_name, _stock, _assigned_at in self.database.get_all_placement_items():
            if product_id not in registered_ids:
                continue
            slots = local.setdefault(product_id, [])
            if slot_name not in slots:
                slots.append(slot_name)
        return local

    def import_excel(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Import KiotViet product locations",
            filetypes=(("Excel workbooks", "*.xlsx"),),
        )
        if not path:
            return
        try:
            from openpyxl import load_workbook
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                dialog = WorkbookColumnDialog(self, workbook)
                self.wait_window(dialog)
                if dialog.result is None:
                    return
                columns = dialog.result
            finally:
                workbook.close()
        except Exception as error:
            messagebox.showerror("Excel import failed", str(error), parent=self)
            return
        self._start_comparison("import", path=Path(path), columns=columns)

    def refresh(self) -> None:
        if self.busy or self.web_locations is None:
            return
        self._start_comparison("refresh")

    def _start_comparison(
        self, action: str, *, path: Path | None = None,
        columns: tuple[str, int, int, int] | None = None,
    ) -> None:
        if self.busy:
            return
        self._comparison_action = action
        self._comparison_path = path
        self._comparison_busy = True
        self.progress.set({
            "import": "Importing and comparing locations…",
            "refresh": "Refreshing comparison…",
            "resync": "Checking current local locations…",
            "export": "Preparing comparison Excel…",
        }[action])
        self._set_busy_state()
        Thread(
            target=self._run_comparison,
            args=(action, path, columns,
                  None if action == "import" else dict(self.web_locations or {}),
                  dict(self.resynced)),
            daemon=True,
        ).start()
        self.after(50, self._poll_comparison)

    def _run_comparison(
        self, action: str, path: Path | None, columns: tuple[str, int, int, int] | None,
        web_snapshot: dict[str, str] | None, resynced_snapshot: dict[str, str],
    ) -> None:
        # This worker only reads data and queues a result; all Tk updates stay on the UI thread.
        try:
            web_locations = read_web_locations(path, *columns) if columns is not None else web_snapshot
            if web_locations is None:
                raise ValueError("Import website data before comparing locations.")
            local_locations = self._local_locations()
            differences, missing_ids = compare_locations(local_locations, web_locations)
            export_path = None
            export_count = 0
            if action == "export":
                remaining = [row for row in differences
                             if resynced_snapshot.get(row.product_id) != row.true_location]
                export_count = len(remaining)
                if remaining:
                    result_dir = data_directory() / "exports" / "location_comparison"
                    result_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    export_path = result_dir / f"kiotviet_location_comparison_{timestamp}.xlsx"
                    counter = 2
                    while export_path.exists():
                        export_path = result_dir / f"kiotviet_location_comparison_{timestamp}_{counter}.xlsx"
                        counter += 1
                    export_comparison(export_path, remaining)
            self._comparison_events.put((
                "done", web_locations, local_locations, differences, missing_ids,
                export_path, export_count,
            ))
        except Exception as error:
            self._comparison_events.put(("error", str(error)))

    def _poll_comparison(self) -> None:
        try:
            event, *payload = self._comparison_events.get_nowait()
        except Empty:
            self.after(50, self._poll_comparison)
            return
        if event == "error":
            self._comparison_busy = False
            self._set_busy_state()
            self.progress.set("")
            messagebox.showerror(f"{self._comparison_action.title()} failed", payload[0], parent=self)
            return

        (web_locations, local_locations, self.differences, self.missing_ids,
         self._export_path, self._export_count) = payload
        self.web_locations = web_locations
        if self._comparison_action == "import":
            self.imported_path = self._comparison_path
            self.file_label.set(
                f"Imported {self.imported_path.name}: {len(web_locations):,} website product IDs"
            )
            self.resynced.clear()
        self.tree.delete(*self.tree.get_children())
        self._render_local_locations = local_locations
        self._render_rows = ([('difference', row) for row in self.differences]
                             + [('missing', product_id) for product_id in self.missing_ids])
        self._render_index = 0
        self._render_comparison_rows()

    def _render_comparison_rows(self) -> None:
        # Large exports paint incrementally so the loading animation keeps moving.
        next_index = min(self._render_index + 200, len(self._render_rows))
        for kind, item in self._render_rows[self._render_index:next_index]:
            if kind == "missing":
                product_id = item
                self.tree.insert(
                    "", "end", iid=f"missing::{product_id}",
                    values=(product_id, "(not in export)",
                            ", ".join(self._render_local_locations[product_id]), "Cannot compare"),
                    tags=("missing",),
                )
                continue
            difference = item
            if self.resynced.get(difference.product_id) == difference.true_location:
                status, tag = "Saved; re-export to verify", "resynced"
            elif not difference.true_location:
                status, tag = "Ready to clear web location", ""
            elif len(location_parts(difference.true_location)) > 1:
                count = len(location_parts(difference.true_location))
                status, tag = f"Ready to sync {count} locations", ""
            else:
                status, tag = "Unsynced", ""
            self.tree.insert(
                "", "end", iid=f"difference::{difference.product_id}",
                values=(difference.product_id, difference.wrong_location,
                        difference.true_location or "(none)", status),
                tags=(tag,) if tag else (),
            )
        self._render_index = next_index
        if next_index < len(self._render_rows):
            self.after(1, self._render_comparison_rows)
            return
        self._comparison_busy = False
        self._set_busy_state()
        self.progress.set("")
        if self._comparison_action == "resync":
            self._resync_ready()
        elif self._comparison_action == "export":
            if self._export_path is None:
                messagebox.showinfo("No differences", "There are no different locations to export.", parent=self)
            else:
                self.summary.set(
                    f"Exported {self._export_count:,} unsynced location(s) to {self._export_path}."
                )

    def _set_busy_state(self) -> None:
        self.busy = self._comparison_busy or self._web_busy
        state = "disabled" if self.busy else "normal"
        self.import_button.configure(state=state)
        self.refresh_button.configure(state=state)
        if self.web_locations is None:
            self.resync_button.configure(state="disabled")
            self.export_button.configure(state="disabled")
        else:
            self._update_summary()
        if self.busy and self._loading_after_id is None:
            self.loading_bar.place(relx=1.0, rely=0.5, anchor="e")
            self._animate_loading()
        elif not self.busy and self._loading_after_id is not None:
            self.after_cancel(self._loading_after_id)
            self._loading_after_id = None
            self.loading_bar.place_forget()

    def _animate_loading(self) -> None:
        if not self.busy:
            self._loading_after_id = None
            return
        self._loading_position += self._loading_direction * 5
        if self._loading_position >= 126:
            self._loading_position = 126
            self._loading_direction = -1
        elif self._loading_position <= 0:
            self._loading_position = 0
            self._loading_direction = 1
        self.loading_bar.coords(
            self.loading_segment, self._loading_position, 0, self._loading_position + 44, 4
        )
        self._loading_after_id = self.after(30, self._animate_loading)

    def _update_summary(self) -> None:
        unsynced = self.exportable_differences()
        ready = sum(row.can_resync for row in unsynced)
        self.summary.set(
            f"{len(unsynced):,} unsynced · {ready:,} ready for web resync · "
            f"{len(self.missing_ids):,} local IDs absent from export"
        )
        self.resync_button.configure(state="normal" if ready and not self.busy else "disabled")
        self.export_button.configure(state="normal" if unsynced and not self.busy else "disabled")

    def exportable_differences(self) -> list[LocationDifference]:
        return [row for row in self.differences
                if self.resynced.get(row.product_id) != row.true_location]

    def pending_updates(self) -> list[LocationUpdate]:
        return [
            LocationUpdate(row.product_id, location_parts(row.true_location))
            for row in self.differences
            if row.can_resync and self.resynced.get(row.product_id) != row.true_location
        ]

    def resync(self) -> None:
        if self.busy or self.web_locations is None:
            return
        self._start_comparison("resync")

    def _resync_ready(self) -> None:
        updates = self.pending_updates()
        if not updates:
            messagebox.showinfo("No unsynced locations", "There are no comparable unsynced products to upload.", parent=self)
            return
        self.on_resync(updates)

    def mark_resynced(self, product_id: str) -> None:
        row = next((item for item in self.differences if item.product_id == product_id), None)
        if row is not None:
            self.resynced[product_id] = row.true_location
            iid = f"difference::{product_id}"
            if self.tree.exists(iid):
                self.tree.item(
                    iid,
                    values=(row.product_id, row.wrong_location, row.true_location or "(none)",
                            "Saved; re-export to verify"),
                    tags=("resynced",),
                )
            self._update_summary()

    def set_busy(self, busy: bool) -> None:
        self._web_busy = busy
        for widget in (self.url_entry, self.tabs_input, self.save_settings_button):
            widget.configure(state="disabled" if busy else "normal")
        self._set_busy_state()

    def set_progress(self, message: str) -> None:
        self.progress.set(message)

    def export_excel(self) -> None:
        if self.busy or self.web_locations is None:
            return
        self._start_comparison("export")
