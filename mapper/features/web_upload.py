"""Update placements in an existing Chrome session with optional Playwright.

Playwright is imported only when a browser action is requested. This module never
opens SQLite, commits a shelf, or logs in. The selected
SKU is looked up through the current KiotViet browser session, then the remaining
form fields are changed one step at a time. The app controller can safely call
these operations sequentially or on separate tabs for a batch. Location-only updates
deliberately leave the website quantity untouched.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from typing import Callable
from urllib.parse import urlsplit

from mapper.core.common import normalize_sku, split_locations

from .kiotviet_settings import validate_store_url, validate_tab_count


# Chrome connection and upload timings.
DEBUGGER_ADDRESS = "127.0.0.1:9222"
TIMEOUT_SECONDS = 20
STEP_DELAY_SECONDS = 1.0
# Controls only the final product Save. A newly created location must always
# save its own dialog before it can be assigned to the product.
SAVE_ON_UPLOAD = True  # Keep False while testing; set True only for production.
VERIFY_AFTER_SAVE = False  # Set True to reopen the product and verify saved values.
SET_LOCATION_ON_UPLOAD = True  # Set False to skip all location lookup/create/select work.

# The popup's div[47]/div[68] number changes between openings. Anchor to its form.
FORM_XPATH = "//kv-product-form/form"
PANE_XPATH = FORM_XPATH + "/section/kv-tabs/div/div[2]/kv-tab-pane[1]/div/div/div[2]"
QUANTITY_XPATH = PANE_XPATH + "/div[3]/div[2]/div/div[1]/div/div/input"
LOCATION_FIELD_XPATH = PANE_XPATH + "/div[4]/div[2]/div/div[1]"
CREATE_LOCATION_XPATH = LOCATION_FIELD_XPATH + "/div/div[1]/a"
LOCATION_FORM_XPATH = "//kv-shelves-add-or-edit"
NEW_LOCATION_XPATH = LOCATION_FORM_XPATH + "/div[1]/div/div/input"
SAVE_LOCATION_XPATH = LOCATION_FORM_XPATH + '//a[normalize-space()="Lưu"]'
SAVE_XPATH = FORM_XPATH + "/div/div[2]/a[4]"

# Browser numbers are doubles; larger quantities would be silently rounded on the website.
MAX_WEB_STOCK = 2**53 - 1

# Usually detected from a Code/SKU/product-ID input in the edit form. If your
# site's input has no identifying attributes, put its exact XPath here.
PRODUCT_ID_XPATH = ""


class UploadError(RuntimeError):
    """An actionable error that can be shown without a browser stack trace."""


class WaitExpired(UploadError):
    pass


@dataclass(frozen=True)
class UploadProduct:
    product_id: str
    stock_qty: int
    location_id: str | tuple[str, ...]
    location_ids: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'product_id', normalize_sku(self.product_id))
        ids = split_locations(self.location_id)
        object.__setattr__(self, "location_ids", ids)
        object.__setattr__(self, "location_id", ", ".join(ids))
        if not self.product_id or not ids:
            raise ValueError("A product ID and a location ID are required.")
        if type(self.stock_qty) is not int or not 0 <= self.stock_qty <= MAX_WEB_STOCK:
            raise ValueError(f"Upload needs a known whole-number quantity from 0 to {MAX_WEB_STOCK:,}.")


@dataclass(frozen=True)
class LocationUpdate:
    product_id: str
    location_id: str | tuple[str, ...]
    location_ids: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'product_id', normalize_sku(self.product_id))
        if isinstance(self.location_id, str) and self.location_id and not self.location_id.strip():
            raise ValueError("Use an empty location ID to clear the website location.")
        ids = split_locations(self.location_id)
        object.__setattr__(self, "location_ids", ids)
        object.__setattr__(self, "location_id", ", ".join(ids))
        if not self.product_id:
            raise ValueError("A product ID is required.")


# Browser scripts live in kiotviet_js/. session.js (callback + current login token) is
# shared by the async scripts; arguments are always passed as values, never interpolated.
_SCRIPTS = Path(__file__).with_name("kiotviet_js")


def _script(*names: str) -> str:
    return "\n".join((_SCRIPTS / f"{name}.js").read_text(encoding="utf-8") for name in names)


OPEN_PRODUCT_SCRIPT = _script("session", "open_product")
GET_SHELVES_SCRIPT = _script("session", "get_shelves")
DOM_SCRIPT = _script("dom")
# Installed once per page load, so each 0.2 s poll sends a few bytes instead of the adapter.
_DOM_CALL = "(a) => typeof window.__kvDom === 'function' ? [window.__kvDom(...a)] : null"
_DOM_INSTALL = "(a) => { window.__kvDom = function () {\n" + DOM_SCRIPT + "\n}; return [window.__kvDom(...a)]; }"


class WebsiteUploader:
    """Own a Playwright attachment on the calling worker thread.

    Disconnecting releases automation without closing the user's Chrome.
    """

    def __init__(
        self,
        page=None,
        *,
        store_url: str = "",
        timeout: float = TIMEOUT_SECONDS,
        step_delay: float = STEP_DELAY_SECONDS,
        location_lock=None,
    ):
        self.page = page
        self.browser = None
        self.playwright = None
        self.store_url = store_url
        self.timeout = timeout
        self.step_delay = max(0.0, step_delay)
        self.location_lock = location_lock or Lock()
        self._page_session = None
        self._session_page = None
        self._kiotviet_id = None

    def is_connected(self) -> bool:
        if self.browser is not None:
            return self.browser.is_connected()
        return self.page is not None and not self.page.is_closed()

    def connect(self, progress: Callable[[str], None] = lambda _message: None) -> str:
        """Attach to Chrome independently of the open tabs and store login."""
        self.store_url = validate_store_url(self.store_url)
        progress("Connecting to Chrome...")
        self._connect()
        return "Chrome connected. KiotViet opens automatically when you start a web action."

    def disconnect(self) -> None:
        """Disconnect the transport; never close the user's browser."""
        try:
            if self.playwright is not None:
                self.playwright.stop()
            elif self._page_session is not None and not self._session_page.is_closed():
                self._page_session.detach()
        finally:
            self.page = self.browser = self.playwright = None
            self._page_session = self._session_page = None

    def _connect(self) -> None:
        if self.browser is not None or self.page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise UploadError(
                "Install Playwright in the same venv as this app:\n\n"
                ".venv\\Scripts\\python.exe -m pip install playwright"
            ) from error
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(
                f"http://{DEBUGGER_ADDRESS}", timeout=self.timeout * 1000
            )
        except Exception as error:
            self.disconnect()
            raise UploadError(
                f"Cannot attach to Chrome at {DEBUGGER_ADDRESS}. "
                "Open your debugging Chrome with remote debugging enabled.\n\n"
                + str(error)[:700]
            ) from error

    def _evaluate_async(self, script, *args):
        # Existing callbacks resolve a Promise; timeouts never retry a website write.
        wrapper = """(input) => new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(Error('Browser operation timed out')), input.timeout);
            const arguments = [...input.args, result => { clearTimeout(timer); resolve(result); }];
        """ + script + "\n})"
        return self.page.evaluate(wrapper, {"args": list(args), "timeout": self.timeout * 1000})

    def _dom(self, action, paths=None, value=None):
        args = [action, paths, value]
        result = self.page.evaluate(_DOM_CALL, args)
        if result is None:  # first call after a page load
            result = self.page.evaluate(_DOM_INSTALL, args)
        return result[0]

    def _wait(self, description, condition, *, timeout=None, check_errors=False):
        deadline = monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            if check_errors:
                error = self._dom("errors")
                if error:
                    raise UploadError(f"Website message while {description}:\n{error}")
            result = condition()
            if result:
                return result
            if monotonic() >= deadline:
                raise WaitExpired(f"Timed out while {description}. Inspect the open Chrome tab.")
            sleep(0.2)

    @contextmanager
    def _watch_responses(self, predicate):
        """Collect this tab's matching responses into a list.

        Used instead of page.expect_response: leaving that block with an error
        cancels its waiter, which breaks the next Playwright call (even stop())
        with "This event loop is already running" and hides the real error.
        """
        seen = []

        def listen(response):
            if predicate(response):
                seen.append(response)

        page = self.page
        page.on("response", listen)
        try:
            yield seen
        finally:
            page.remove_listener("response", listen)

    def _first_response(self, seen, description):
        deadline = monotonic() + self.timeout
        while not seen:
            if monotonic() >= deadline:
                raise WaitExpired(f"Timed out while {description}. Inspect the open Chrome tab.")
            self.page.wait_for_timeout(100)  # lets Playwright deliver response events
        return seen[0]

    def _pause(self) -> None:
        if self.step_delay:
            sleep(self.step_delay)

    def _matches_store(self, page) -> bool:
        try:
            return validate_store_url(page.url) == self.store_url
        except ValueError:
            return False

    def _choose_tab(self, *, wait_ready: bool = True) -> None:
        if self.page is None or self.page.is_closed():
            # A previous failed edit may leave an empty modal in another tab.
            # Prefer a clean Products tab, and open one when none is available.
            self.page = next(
                (page for context in self.browser.contexts for page in context.pages
                 if self._matches_store(page)
                 and not page.locator('.k-window-addProduct:visible').count()), None
            )
        if self.page is None:
            if not self.browser.contexts:
                raise UploadError("Chrome has no available browser context. Reconnect Chrome.")
            self.page = self.browser.contexts[0].new_page()
            self.page.goto(self.store_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
        if not wait_ready:
            return
        if not self._matches_store(self.page):
            raise UploadError(
                "KiotViet is waiting for login. Log in on the opened tab, then try the web action again: "
                + self.store_url
            )
        self.page.set_default_timeout(self.timeout * 1000)
        self._prepare_page()
        if self._dom("present", FORM_XPATH) or self._dom("present", LOCATION_FORM_XPATH):
            raise UploadError("Finish or cancel the existing website edit dialog before uploading.")
        self._wait("waiting for the KiotViet product page", lambda: self._dom("product_page") and self._dom("product_controller"))

    def _prepare_page(self) -> None:
        """Keep this tab active without selecting it in the Chrome window."""
        if self._session_page is self.page:
            return
        if self._page_session is not None and not self._session_page.is_closed():
            self._page_session.detach()
        self._page_session = self.page.context.new_cdp_session(self.page)
        self._session_page = self.page
        self._page_session.send("Network.enable")
        self._page_session.send("Network.setCacheDisabled", {"cacheDisabled": True})
        # Keep the CDP session attached: detaching removes focus emulation.
        self._page_session.send("Emulation.setFocusEmulationEnabled", {"enabled": True})

    def _new_upload_tab(self) -> None:
        """Use the logged-in context, including auth kept in sessionStorage."""
        source = self.page
        storage = source.evaluate("Object.fromEntries(Object.entries(sessionStorage))")
        self.page = source.context.new_page()
        # Install storage before the app starts, and only for this store's origin.
        origin = self.store_url.split("/man/")[0]
        self.page.add_init_script(
            "if (location.origin === " + json.dumps(origin) + ") {"
            "for (const [key, value] of Object.entries(" + json.dumps(storage) + ")) "
            "sessionStorage.setItem(key, value); }"
        )
        self._prepare_page()
        self.page.goto(self.store_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
        self._choose_tab()

    def run_batch(self, products, progress, item_done, *, location_only, save, tab_count=1) -> str:
        """Each thread owns its runtime and tab; stop taking new SKUs on error."""
        tab_count = validate_tab_count(tab_count)
        save = SAVE_ON_UPLOAD if save is None else save
        if not products:
            return "No products to update."
        if len({product.product_id for product in products}) != len(products):
            raise UploadError("A browser batch must contain each product ID only once.")
        if tab_count > 1 and not save:
            raise UploadError("Concurrent uploads require saving each product.")
        state_lock = Lock()
        pending = iter(products)
        completed, errors, results = [], [], []
        workers = min(tab_count, len(products))

        def next_product():
            with state_lock:
                return None if errors else next(pending, None)

        def worker():
            uploader = WebsiteUploader(
                store_url=self.store_url, timeout=self.timeout,
                step_delay=0, location_lock=self.location_lock,
            )
            product = None
            owned_page = None
            try:
                uploader.connect(progress)
                if workers > 1:
                    # Keep the source tab untouched. Every worker owns one new tab.
                    uploader._choose_tab(wait_ready=False)
                    source_page = uploader.page
                    try:
                        uploader._new_upload_tab()
                    finally:
                        if uploader.page is not source_page:
                            owned_page = uploader.page
                while (product := next_product()) is not None:
                    report = lambda text, pid=product.product_id: progress(f"{pid}: {text}")
                    report("Starting web task...")
                    action = uploader.modify_location if location_only else uploader.upload
                    result = action(product, report, save=save)
                    with state_lock:
                        completed.append(product.product_id)
                        results.append(result)
                        item_done(product.product_id)
                        progress(f"[{len(completed)}/{len(products)}] Finished {product.product_id}.")
            except Exception as error:
                with state_lock:
                    failed = product.product_id if product is not None else "connecting an upload tab"
                    errors.append(f"Failed at {failed}: {error}")
            finally:
                try:
                    # Leave a failed or unsaved form open for inspection.
                    if owned_page is not None and product is None and save and not errors:
                        owned_page.close()
                finally:
                    uploader.disconnect()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in [pool.submit(worker) for _ in range(workers)]:
                future.result()
        if errors:
            raise UploadError(
                f"Batch stopped after {len(completed)}/{len(products)} product(s). "
                "Already-running products were allowed to finish. Check the open tabs before retrying.\n\n"
                + "\n\n".join(errors)
            )
        if len(products) == 1:
            return results[0]
        return f"Updated web locations for {len(completed)} products." if location_only else (
            f"Uploaded stock and web locations for {len(completed)} products."
        )

    def _fill_input(self, path: str, value: str) -> None:
        self._wait("finding an input", lambda: self._dom("element", path))
        if not self._dom("set", path, value):
            raise UploadError("The input disappeared before it could be filled.")

    def _click(self, path: str, description: str) -> None:
        self._wait(description, lambda: self._dom("click", path), check_errors=True)

    def _identity_matches(self, product: UploadProduct | LocationUpdate) -> bool:
        return self._dom("identity", {"form": FORM_XPATH, "id": PRODUCT_ID_XPATH}, product.product_id)

    def _stock_matches(self, product: UploadProduct) -> bool:
        quantity = self._dom("quantity", QUANTITY_XPATH)
        if type(quantity) is bool or quantity is None:
            return False
        return quantity == product.stock_qty or str(quantity).strip() == str(product.stock_qty)

    def _location_matches(self, product: UploadProduct | LocationUpdate) -> bool:
        return bool(self._dom("location_selected", LOCATION_FIELD_XPATH, list(product.location_ids)))

    def _location_values_match(self, product: UploadProduct | LocationUpdate) -> bool:
        return self._identity_matches(product) and self._location_matches(product)

    def _all_values_match(self, product: UploadProduct) -> bool:
        return (
            self._identity_matches(product)
            and self._stock_matches(product)
            and (not SET_LOCATION_ON_UPLOAD or self._location_matches(product))
        )

    def _open_product(self, product: UploadProduct | LocationUpdate) -> None:
        from playwright.sync_api import TimeoutError as BrowserTimeout

        self._kiotviet_id = None
        for attempt in range(2):
            try:
                # Listen before injecting; the controller's callback only
                # starts loading the editor. Await this tab's edit-data response.
                with self._watch_responses(
                    lambda response: response.request.method == "GET"
                    and re.fullmatch(r"/api/products/\d+/initialdata", urlsplit(response.url).path) is not None
                ) as edit_responses:
                    result = self._evaluate_async(OPEN_PRODUCT_SCRIPT, product.product_id)
                    if not isinstance(result, dict) or not result.get("ok"):
                        detail = result.get("error") if isinstance(result, dict) else repr(result)
                        raise UploadError(f"Could not open product {product.product_id}: {detail}")
                    response = self._first_response(edit_responses, "loading the product edit data")
                response.body()  # the response event alone only means headers arrived.
                self._kiotviet_id = str(result.get("kiotviet_id") or "")
                if (not response.ok
                        or urlsplit(response.url).path != f"/api/products/{self._kiotviet_id}/initialdata"):
                    raise UploadError(f"Could not load edit data for {product.product_id} (HTTP {response.status}).")
                self._wait("loading the edit form", lambda: self._dom("edit_ready", FORM_XPATH), check_errors=True)
                self._wait(
                    "checking the product ID (set PRODUCT_ID_XPATH if automatic detection fails)",
                    lambda: self._identity_matches(product),
                    check_errors=True,
                )
                return
            except (WaitExpired, BrowserTimeout) as error:
                if attempt:
                    raise UploadError(
                        f"KiotViet did not load a usable edit form for {product.product_id}. "
                        "Check the open tab. No product was saved."
                    ) from error
                # Opening an edit is read-only. A refresh clears a partially
                # compiled popup before one safe retry; Save is never retried.
                self.page.reload(wait_until="domcontentloaded", timeout=self.timeout * 1000)
                self._wait(
                    "waiting for KiotViet after the incomplete form",
                    lambda: self._dom("product_page") and self._dom("product_controller"),
                )

    def _set_stock(self, product: UploadProduct) -> None:
        self._wait("finding the stock input", lambda: self._dom("present", QUANTITY_XPATH))
        if not self._dom("set", QUANTITY_XPATH, str(product.stock_qty)):
            raise UploadError("The stock input disappeared.")
        self._wait("checking the stock quantity", lambda: self._stock_matches(product), check_errors=True)

    def _shelf_ids_by_name(self) -> dict[str, str]:
        """{location name: KiotViet shelf ID} from /api/shelves."""
        result = self._evaluate_async(GET_SHELVES_SCRIPT)
        if not isinstance(result, dict) or not result.get("ok"):
            detail = result.get("error") if isinstance(result, dict) else repr(result)
            raise UploadError(f"Could not read KiotViet locations: {detail}")
        shelves = result.get("shelves")
        if not isinstance(shelves, list):
            raise UploadError("KiotViet returned an invalid location list.")
        ids_by_name: dict[str, str] = {}
        for shelf in shelves:
            if not isinstance(shelf, dict):
                continue
            name = str(shelf.get("name") or "").strip()
            shelf_id = str(shelf.get("id") or "").strip()
            if not name or not shelf_id:
                continue
            if ids_by_name.setdefault(name, shelf_id) != shelf_id:
                raise UploadError(f"KiotViet has duplicate location name {name!r} with multiple shelf IDs.")
        return ids_by_name

    def _select_location_ids(
        self, product: UploadProduct | LocationUpdate, ids_by_name: dict[str, str]
    ) -> None:
        selected = self._dom(
            "location_pick_ids",
            LOCATION_FIELD_XPATH,
            {
                "ids": [ids_by_name[name] for name in product.location_ids],
                "names": list(product.location_ids),
            },
        )
        if not selected:
            raise UploadError(
                f"Locations {product.location_id} exist in KiotViet, "
                "but the edit form could not select the complete set."
            )
        self._wait(
            "checking the selected location",
            lambda: self._location_matches(product),
            check_errors=True,
        )

    def _create_location(self, name: str, progress: Callable[[str], None]) -> None:
        progress(f"Creating location {name}…")
        self._click(CREATE_LOCATION_XPATH, "opening Add location")
        try:
            self._fill_input(NEW_LOCATION_XPATH, name)
            self._click(SAVE_LOCATION_XPATH, "saving the new location")
            self._wait(
                "waiting for the new location dialog to close",
                lambda: not self._dom("present", LOCATION_FORM_XPATH),
                check_errors=True,
            )
        except UploadError as error:
            raise UploadError(
                f"Could not create location {name}. The product Save button has not been pressed.\n\n" + str(error)
            ) from error

    def _set_location(
        self,
        product: UploadProduct | LocationUpdate,
        progress: Callable[[str], None],
    ) -> None:
        if not product.location_ids:
            self._clear_location()
            return
        self._wait("finding the location field", lambda: self._dom("present", LOCATION_FIELD_XPATH))
        # Existing shelves can be read and selected concurrently. Only creation
        # needs coordination, including a recheck after acquiring the lock.
        ids_by_name = self._shelf_ids_by_name()
        if not ids_by_name.keys() >= set(product.location_ids):
            with self.location_lock:
                ids_by_name = self._shelf_ids_by_name()
                missing = [name for name in product.location_ids if name not in ids_by_name]
                for name in missing:
                    self._create_location(name, progress)
                if missing:
                    ids_by_name = self._await_locations(missing)
        progress(f"Selecting locations {product.location_id}…")
        self._select_location_ids(product, ids_by_name)

    def _await_locations(self, names: list[str]) -> dict[str, str]:
        """New locations reach /api/shelves shortly after their dialog closes."""
        deadline = monotonic() + 5
        while True:
            ids_by_name = self._shelf_ids_by_name()
            if ids_by_name.keys() >= set(names):
                return ids_by_name
            if monotonic() >= deadline:
                absent = ", ".join(repr(name) for name in names if name not in ids_by_name)
                raise UploadError(f"KiotViet closed the Create location form, but {absent} did not appear in /api/shelves.")
            sleep(0.4)

    def _clear_location(self) -> None:
        self._wait("finding the location field", lambda: self._dom("present", LOCATION_FIELD_XPATH))
        if not self._dom("location_clear", LOCATION_FIELD_XPATH):
            raise UploadError("The website location selector could not be cleared.")

    @staticmethod
    def _result_message(product, *, location_only: bool, verified: bool = False, note: str = "") -> str:
        checked = " and verified" if verified else ""
        if not location_only:
            prefix = "Uploaded and verified" if verified else "Uploaded"
            return f"{prefix}: {product.product_id} · qty {product.stock_qty} · {product.location_id}.{note}"
        if not product.location_id:
            return f"Location cleared{checked}: {product.product_id}.{note}"
        return f"Location {'updated and verified' if verified else 'saved'}: {product.product_id} · {product.location_id}.{note}"

    def _save_product(
        self,
        product: UploadProduct | LocationUpdate,
        progress: Callable[[str], None],
        *,
        location_only: bool = False,
    ) -> str:
        """Press Save once; await its complete response and editor close."""
        progress("Saving the location on the website…" if location_only else "Saving the product on the website…")

        try:
            # From this call onward a timeout has an uncertain outcome. Never retry Save.
            with self._watch_responses(
                lambda response: response.request.method == "POST"
                and urlsplit(response.url).path == "/api/products/photo"
            ) as save_responses:
                self._click(SAVE_XPATH, "pressing Save")
                response = self._first_response(save_responses, "waiting for the Save response")
            if not response.ok:
                raise UploadError(f"KiotViet Save returned HTTP {response.status}.")
            # Download the response body, not just the headers or a UI toast.
            payload = response.json()
            saved = payload.get("Data") if isinstance(payload, dict) else None
            if (not isinstance(saved, dict) or not self._kiotviet_id
                    or str(saved.get("Id")) != self._kiotviet_id
                    or (saved.get("Code") is not None and
                        normalize_sku(saved["Code"]) != product.product_id)):
                raise UploadError("KiotViet Save did not confirm the expected product ID and SKU.")
            self._wait(
                "waiting for Save to finish",
                lambda: not self._dom("present", FORM_XPATH),
                check_errors=True,
            )
        except Exception as error:
            detail = str(error).split("Stacktrace:")[0][:1400]
            raise UploadError(
                "Save may have reached the website, but the result was not verified. "
                "Check this product in Chrome before trying again. No automatic retry was made.\n\n" + detail
            ) from error

        # Keep the requested final-save pause. Read-back verification stays
        # available behind a separate switch because it visibly refreshes,
        # reopens the product, then refreshes once more to close the form.
        self._pause()
        if not VERIFY_AFTER_SAVE:
            return self._result_message(product, location_only=location_only)

        progress(
            "Reloading the saved product to verify its location…"
            if location_only else
            "Reloading the saved product to verify quantity and location…"
        )
        self.page.reload()
        self._wait("waiting for the product page after reload", lambda: self._dom("product_page"))
        self._open_product(product)
        self._wait(
            "verifying the saved location" if location_only else "verifying the saved values",
            lambda: self._location_values_match(product)
            if location_only else self._all_values_match(product),
            check_errors=True,
        )
        note = ""
        try:
            self.page.reload()  # Close the verification edit, ready for next product.
        except Exception:
            note = " Close the verification form in Chrome before the next upload."
        return self._result_message(product, location_only=location_only, verified=True, note=note)

    def upload(
        self,
        product: UploadProduct,
        progress: Callable[[str], None] = lambda _message: None,
        *,
        save: bool | None = None,
    ) -> str:
        """Fill stock/location for one product and optionally save the edit."""
        return self._edit(product, progress, save=save, location_only=False)

    def modify_location(
        self,
        product: LocationUpdate,
        progress: Callable[[str], None] = lambda _message: None,
        *,
        save: bool | None = None,
    ) -> str:
        """Change only the website location; never inspect or modify stock."""
        return self._edit(product, progress, save=save, location_only=True)

    def _edit(self, product, progress, *, save: bool | None, location_only: bool) -> str:
        if not self.is_connected():
            raise UploadError(
                "Chrome is not connected. Press Connect Chrome on the main tab bar first."
            )
        try:
            progress("Checking the connected Chrome tab…")
            self._choose_tab()

            progress(f"Finding product {product.product_id}…")
            self._open_product(product)

            if not location_only:
                progress(f"Setting stock to {product.stock_qty}…")
                self._set_stock(product)

            if not product.location_ids:
                progress("Clearing the website location…")
                self._clear_location()
            else:
                if location_only or SET_LOCATION_ON_UPLOAD:
                    progress(f"Selecting location {product.location_id}…")
                    self._set_location(product, progress)
                self._wait(
                    "checking product fields before Save",
                    lambda: self._location_values_match(product) if location_only else self._all_values_match(product),
                    check_errors=True,
                )

            # A batch explicitly opts into Save so Chrome can advance to its
            # next product. Single-product calls keep the global safety switch.
            if SAVE_ON_UPLOAD if save is None else save:
                return self._save_product(product, progress, location_only=location_only)
            if not location_only:
                return "Fields filled. Press Lưu manually in Chrome."
            if not product.location_id:
                return "Location cleared in the edit form. Press Lưu manually in Chrome."
            return "Location filled. Stock was untouched. Press Lưu manually in Chrome."

        except UploadError:
            raise
        except Exception as error:
            detail = str(error).split("Stacktrace:")[0][:1400]
            stage = ("Location update stopped before the final Save step. Stock was not changed."
                     if location_only else "Upload stopped before the final Save step.")
            raise UploadError(
                f"{stage} Any new location already created may remain on the website.\n\n" + detail
            ) from error
