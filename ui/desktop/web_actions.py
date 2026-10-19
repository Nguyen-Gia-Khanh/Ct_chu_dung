"""Tkinter actions for optional KiotViet browser uploads."""

from __future__ import annotations

from queue import Empty, Queue
from threading import Thread
from tkinter import messagebox

from mapper.persistence.database import Placement
from mapper.features.web_upload import LocationUpdate, UploadProduct
from mapper.services.uploads import location_updates, upload_products


class WebActions:
    def on_kiotviet_url_changed(self, url: str) -> None:
        self.website_uploader.store_url = url
        self.chrome_connected = False
        self.notebook.tab(self.chrome_tab, text="Connect Chrome")

    def _capture_browser_settings(self) -> bool:
        if not self.location_comparison.save_browser_settings():
            return False
        self.website_uploader.store_url = self.location_comparison.store_url.get()
        return True

    def connect_chrome(self) -> None:
        if self.chrome_connect_busy:
            return
        if self.web_upload_busy:
            messagebox.showinfo(
                "Upload in progress",
                "Wait for the current upload before reconnecting Chrome.",
                parent=self.root,
            )
            return

        if not self._capture_browser_settings():
            return
        self.location_comparison.set_busy(True)
        self.chrome_connect_busy = True
        self.notebook.tab(self.chrome_tab, text="Connecting…", state="disabled")
        self.status_text.set("Connecting to the debugging Chrome session on port 9222…")
        self.chrome_connect_events = Queue()
        Thread(
            target=self._run_chrome_connect,
            args=(self.chrome_connect_events,),
            daemon=True,
        ).start()
        self.chrome_connect_after_id = self.root.after(100, self._poll_chrome_connect)

    def _run_chrome_connect(self, events: Queue) -> None:
        # This worker never calls Tkinter.
        try:
            result = self.website_uploader.connect(
                lambda text: events.put(("progress", text))
            )
        except Exception as error:
            event = ("error", str(error))
        else:
            event = ("done", result)
        finally:
            self.website_uploader.disconnect()
        events.put(event)

    def _poll_chrome_connect(self) -> None:
        self.chrome_connect_after_id = None
        while True:
            try:
                event, text = self.chrome_connect_events.get_nowait()
            except Empty:
                break
            if event == "progress":
                self.status_text.set(text)
                continue

            self.chrome_connect_busy = False
            self.location_comparison.set_busy(False)
            self.notebook.tab(self.chrome_tab, state="normal")
            if event == "error":
                self.chrome_connected = False
                self.notebook.tab(self.chrome_tab, text="Connect Chrome")
                self.status_text.set("Chrome connection needs attention.")
                messagebox.showerror("Connect Chrome", text, parent=self.root)
            else:
                self.chrome_connected = True
                self.notebook.tab(self.chrome_tab, text="Reconnect Chrome")
                self.assignments.upload_status_text.set(text)
                self.status_text.set(text)
            return
        if self.chrome_connect_busy:
            self.chrome_connect_after_id = self.root.after(
                100, self._poll_chrome_connect
            )

    def _selected_web_placement(self, action_name: str) -> tuple[str, Placement]:
        selected = self.assignments.contents_tree.selection()
        if len(selected) != 1 or not selected[0].startswith("saved::") or self.selected_address is None:
            raise ValueError(f"Select exactly one product in the loaded address contents, then press {action_name}.")
        product_id = selected[0].removeprefix("saved::")
        placement = next((placement for saved_id, _name, placement
                          in self.database.get_slot_contents(self.selected_address.slot_id) if saved_id == product_id), None)
        if placement is None:
            raise ValueError("That selection changed. Reload the address and select it again.")
        return product_id, placement

    def _web_batch_mode_enabled(self) -> bool:
        mode = getattr(self.assignments, "web_batch_mode_var", None)
        return bool(mode is not None and mode.get())

    def _web_placements(self, action_name: str) -> list[tuple[str, Placement]]:
        """Capture either the selected row or every row in the loaded address."""
        if not self._web_batch_mode_enabled():
            return [self._selected_web_placement(action_name)]

        address = self.selected_address
        if address is None:
            raise ValueError(
                "Load a shelf address first. All-products mode uses every product "
                "currently saved in that loaded address."
            )
        contents = self.database.get_slot_contents(address.slot_id)
        if not contents:
            raise ValueError(f"{address.slot_name} does not contain any products.")
        return [(product_id, placement) for product_id, _name, placement in contents]

    def _upload_products(self) -> list[UploadProduct]:
        return upload_products(self.database, self._web_placements("Upload to web"))

    def _location_updates(self) -> list[LocationUpdate]:
        return location_updates(self.database, (pid for pid, _placement in self._web_placements("Modify location")))

    def _can_start_web_update(self) -> bool:
        if self.web_upload_busy or self.chrome_connect_busy:
            return False
        if not self._capture_browser_settings():
            return False
        if self.chrome_connected:
            return True
        messagebox.showinfo(
            "Connect Chrome first",
            "Save your KiotViet URL in Tab 7, then press Connect Chrome on the main tab bar.",
            parent=self.root,
        )
        return False

    def upload_selected_product(self) -> None:
        if not self._can_start_web_update():
            return
        try:
            products = self._upload_products()
        except ValueError as error:
            messagebox.showinfo(
                "Choose products to upload", str(error), parent=self.root
            )
            return
        self._start_web_update(products, location_only=False)

    def modify_selected_location(self) -> None:
        if not self._can_start_web_update():
            return
        try:
            products = self._location_updates()
        except ValueError as error:
            messagebox.showinfo("Choose products", str(error), parent=self.root)
            return
        self._start_web_update(products, location_only=True)

    def modify_cell_transfer_locations(self, updates: list[LocationUpdate]) -> None:
        if not self._can_start_web_update():
            return
        if not updates:
            messagebox.showinfo(
                "No changed products",
                "No recent cell changes to modify on web. Please switch or combine cells first.",
                parent=self.root,
            )
            return
        self._start_web_update(location_updates(self.database, (item.product_id for item in updates)),
                               location_only=True)

    def resync_web_locations(self, updates: list[LocationUpdate]) -> None:
        """Upload only mismatches from the imported KiotViet snapshot."""
        if not self._can_start_web_update():
            return
        if not updates:
            return
        self._start_web_update(
            updates, location_only=True, force_save_each_product=True, source="comparison"
        )

    def _start_web_update(
        self,
        products: list[UploadProduct] | list[LocationUpdate],
        *,
        location_only: bool,
        force_save_each_product: bool = False,
        source: str = "other",
    ) -> None:
        # The complete product list was captured before starting this worker.
        # Later row selections and address changes cannot alter the running task.
        products = list(products)
        if not products:
            return
        save_each_product = force_save_each_product or self._web_batch_mode_enabled()
        self.web_upload_busy = True
        self.web_upload_action = "location" if location_only else "upload"
        self.web_upload_source = source
        self.assignments.upload_button.configure(state="disabled")
        self.assignments.modify_location_button.configure(state="disabled")
        self.assignments.web_batch_mode_check.configure(state="disabled")
        if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "modify_location_button"):
            self.cell_transfer.modify_location_button.configure(state="disabled")
        if hasattr(self, "location_comparison"):
            self.location_comparison.set_busy(True)
        if len(products) == 1:
            product = products[0]
            if location_only and not product.location_id:
                status = f"Clearing web location for {product.product_id}…"
            else:
                action = "Updating location" if location_only else "Uploading"
                status = f"{action} {product.product_id} → {product.location_id}…"
        else:
            if location_only and all(not product.location_id for product in products):
                status = f"Clearing web locations for {len(products)} products…"
            elif location_only and any(not product.location_id for product in products):
                status = f"Resyncing web locations for {len(products)} products…"
            else:
                action = "Updating locations for" if location_only else "Uploading"
                location_note = (
                    f" → {products[0].location_id}"
                    if len({item.location_id for item in products}) == 1 else ""
                )
                status = f"{action} {len(products)} products{location_note}…"
        self.assignments.upload_status_text.set(status)
        if hasattr(self, "location_comparison") and source == "comparison":
            self.location_comparison.set_progress(status)
        if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
            self.cell_transfer.status_text.set(status)
        self.status_text.set(
            f"{status} You can switch Chrome tabs while it runs."
        )
        self.web_upload_events = Queue()
        Thread(
            target=self._run_web_upload,
            args=(
                products,
                self.web_upload_events,
                location_only,
                save_each_product,
                int(self.location_comparison.tab_count.get()) if source == "comparison" else 1,
            ),
            daemon=True,
        ).start()
        self.web_upload_after_id = self.root.after(100, self._poll_web_upload)

    def _run_web_upload(
        self,
        products: list[UploadProduct] | list[LocationUpdate],
        events: Queue,
        location_only: bool,
        save_each_product: bool = False,
        tab_count: int = 1,
    ) -> None:
        # Playwright objects are created and released on their owning threads.
        try:
            result = self.website_uploader.run_batch(
                products,
                lambda text: events.put(("progress", text)),
                lambda product_id: events.put(("item_done", product_id)),
                location_only=location_only,
                save=True if save_each_product else None,
                tab_count=tab_count,
            )
        except Exception as error:
            # The third field says whether Chrome is still reachable for the next task.
            events.put(("error", str(error), "Cannot attach to Chrome" not in str(error)))
        else:
            events.put(("done", result))

    def _poll_web_upload(self) -> None:
        self.web_upload_after_id = None
        while True:
            try:
                event_data = self.web_upload_events.get_nowait()
            except Empty:
                break
            event, text, *metadata = event_data
            if event == "item_done":
                if (getattr(self, "web_upload_source", "other") == "comparison"
                        and hasattr(self, "location_comparison")):
                    self.location_comparison.mark_resynced(text)
                continue
            if event == "progress":
                self.assignments.upload_status_text.set(text)
                if (getattr(self, "web_upload_source", "other") == "comparison"
                        and hasattr(self, "location_comparison")):
                    self.location_comparison.set_progress(text)
                if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
                    self.cell_transfer.status_text.set(text)
                continue
            self.web_upload_busy = False
            self.assignments.upload_button.configure(state="normal")
            self.assignments.modify_location_button.configure(state="normal")
            self.assignments.web_batch_mode_check.configure(state="normal")
            if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "modify_location_button"):
                self.cell_transfer.modify_location_button.configure(state="normal")
            if hasattr(self, "location_comparison"):
                self.location_comparison.set_busy(False)
            action_title = (
                "Modify location"
                if self.web_upload_action == "location"
                else "Upload to web"
            )
            if event == "error":
                if (getattr(self, "web_upload_source", "other") == "comparison"
                        and hasattr(self, "location_comparison")):
                    self.location_comparison.set_progress("Web resync stopped. See the error message.")
                if metadata and not metadata[0]:
                    self.chrome_connected = False
                    self.notebook.tab(self.chrome_tab, text="Connect Chrome")
                self.assignments.upload_status_text.set(
                    f"{action_title} needs attention. See the message and check Chrome."
                )
                if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
                    self.cell_transfer.status_text.set(f"{action_title} failed: {text}")
                self.status_text.set(
                    f"{action_title} was not verified. Local SQLite data is unchanged."
                )
                messagebox.showerror(action_title, text, parent=self.root)
            else:
                self.assignments.upload_status_text.set(text)
                if (getattr(self, "web_upload_source", "other") == "comparison"
                        and hasattr(self, "location_comparison")):
                    self.location_comparison.set_progress(text)
                if hasattr(self, "cell_transfer") and hasattr(self.cell_transfer, "status_text"):
                    self.cell_transfer.status_text.set(text)
                self.status_text.set(text)
            return
        if self.web_upload_busy:
            self.web_upload_after_id = self.root.after(100, self._poll_web_upload)
