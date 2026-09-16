"""Upload ONE placement to the product page in an existing Chrome session.

Selenium is optional and imported only when Upload is clicked. This module never
opens SQLite, commits a shelf, logs in, or starts a product batch. Browser writes
use JavaScript plus input/change events; Enter uses a real WebDriver key event.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable


# Change these settings here if your Chrome port or website changes.
DEBUGGER_ADDRESS = "127.0.0.1:8000"
TAB_URL_CONTAINS = ""  # Optional URL fragment when several product tabs are open.
TIMEOUT_SECONDS = 20

SEARCH_XPATH = "/html/body/div[3]/div[2]/section/div[1]/article/div/div/input"
EDIT_XPATH = (
    "/html/body/div[3]/div[2]/section/div[2]/section[2]/section/article/div/div[2]"
    "/table/tbody/tr[3]/td[2]/div/div/div/div[1]/div/div[7]/div[2]/a[1]"
)
# The popup's div[47]/div[68] number changes between openings. Anchor to its form.
FORM_XPATH = "//kv-product-form/form"
PANE_XPATH = FORM_XPATH + "/section/kv-tabs/div/div[2]/kv-tab-pane[1]/div/div/div[2]"
QUANTITY_XPATH = PANE_XPATH + "/div[3]/div[2]/div/div[1]/div/div/input"
LOCATION_FIELD_XPATH = PANE_XPATH + "/div[4]/div[2]/div/div[1]"
CREATE_LOCATION_XPATH = LOCATION_FIELD_XPATH + "/div/div[1]/a"
LOCATION_FORM_XPATH = "//kv-shelves-add-or-edit"
NEW_LOCATION_XPATH = LOCATION_FORM_XPATH + "/div[1]/div/div/input"
SAVE_XPATH = FORM_XPATH + "/div/div[2]/a[4]"

# Usually detected from a Code/SKU/product-ID input in the edit form. If your
# site's input has no identifying attributes, put its exact XPath here.
PRODUCT_ID_XPATH = ""


class UploadError(RuntimeError):
    """An actionable error that can be shown without a Selenium stack trace."""


class WaitExpired(UploadError):
    pass


@dataclass(frozen=True)
class UploadProduct:
    product_id: str
    stock_qty: int
    location_id: str

    def __post_init__(self) -> None:
        if not self.product_id.strip() or not self.location_id.strip():
            raise ValueError("A product ID and a location ID are required.")
        if type(self.stock_qty) is not int or not 0 <= self.stock_qty <= 2**53 - 1:
            raise ValueError("Upload needs a known whole-number quantity from 0 to 9,007,199,254,740,991.")


# One small DOM adapter, kept here so selectors and website-specific behavior
# can be adjusted without changing the Tkinter application. Values are always
# WebDriver arguments, never interpolated into executable JavaScript.
DOM_SCRIPT = r"""
const [action, paths, value] = arguments;
const visible = e => !!e && e.getClientRects().length > 0 &&
    getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
const all = path => {
    const result = document.evaluate(path, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    return Array.from({length: result.snapshotLength}, (_, i) => result.snapshotItem(i));
};
const one = path => {
    const matches = all(path).filter(visible);
    if (matches.length > 1) throw Error('More than one visible control matches: ' + path);
    return matches[0] || null;
};
const clean = s => String(s == null ? '' : s).trim();
const fold = s => clean(s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').toLowerCase();
const exactText = (root, text) => !!root && [root, ...root.querySelectorAll('*')].some(e =>
    visible(e) && Array.from(e.childNodes).some(n => n.nodeType === 3 && clean(n.nodeValue) === text));
const editable = e => e && !e.disabled && !e.readOnly && e.getAttribute('aria-disabled') !== 'true';
const setValue = (e, text) => {
    if (!editable(e)) throw Error('The target input is disabled or read-only.');
    e.focus();
    const numeric = window.jQuery && window.jQuery(e).data('kendoNumericTextBox');
    if (numeric) {
        numeric.value(Number(text)); numeric.trigger('change');
    } else {
        const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, String(text));
    }
    e.dispatchEvent(new Event('input', {bubbles: true}));
    e.dispatchEvent(new Event('change', {bubbles: true}));
};
const widget = root => {
    if (!window.jQuery || !root) return null;
    const found = [];
    for (const e of root.querySelectorAll('input, select')) {
        for (const kind of ['kendoMultiSelect', 'kendoComboBox', 'kendoDropDownList']) {
            const w = window.jQuery(e).data(kind);
            if (w && visible(w.wrapper && w.wrapper[0]) && !found.some(x => x.w === w)) found.push({w, kind});
        }
    }
    if (found.length > 1) throw Error('Multiple location widgets found; refine LOCATION_FIELD_XPATH.');
    return found[0] || null;
};
const field = (item, name) => typeof item === 'string' ? item :
    String(name || '').split('.').reduce((o, key) => o == null ? null : o[key], item);
const selectedLocation = (root, target) => {
    if (!root) return false;
    const found = widget(root);
    if (found) {
        const w = found.w;
        const items = found.kind === 'kendoMultiSelect' ? w.dataItems() : [w.dataItem()];
        return Array.from(items || []).some(item => item != null && clean(field(item, w.options.dataTextField)) === target);
    }
    for (const select of root.querySelectorAll('select')) {
        if (Array.from(select.selectedOptions).some(o => clean(o.textContent) === target)) return true;
    }
    // Read selected tags/labels, not the search input or an unselected option.
    return Array.from(root.querySelectorAll(
        '.ui-select-match, .select2-selection__rendered, .select2-chosen, .k-chip-content, .k-tag-text'
    )).some(e => exactText(e, target));
};
const chooseLocation = (root, target) => {
    if (!root) return false;
    if (selectedLocation(root, target)) return true;
    const found = widget(root);
    if (found) {
        const w = found.w;
        if (w.element && w.element[0] && !editable(w.element[0]))
            throw Error('The location selector is disabled or read-only.');
        const items = Array.from(w.dataSource.data());
        const matches = items.filter(item => clean(field(item, w.options.dataTextField)) === target);
        if (matches.length > 1) throw Error('Duplicate exact location names exist on the website.');
        if (!matches.length) return false;
        const id = field(matches[0], w.options.dataValueField);
        if (id == null) throw Error('The location option has no value.');
        // Match the website's Add behavior: preserve other selected locations.
        w.value(found.kind === 'kendoMultiSelect' ? [...new Set([...w.value(), id])] : id);
        w.trigger('change');
        if (w.close) w.close();
        return selectedLocation(root, target);
    }
    for (const select of root.querySelectorAll('select')) {
        const matches = Array.from(select.options).filter(o => clean(o.textContent) === target);
        if (matches.length > 1) throw Error('Duplicate exact location names exist on the website.');
        if (!matches.length) continue;
        if (select.disabled) throw Error('The location selector is disabled.');
        if (select.multiple) matches[0].selected = true;
        else select.value = matches[0].value;
        select.dispatchEvent(new Event('input', {bubbles: true}));
        select.dispatchEvent(new Event('change', {bubbles: true}));
        return selectedLocation(root, target);
    }
    const choices = Array.from(document.querySelectorAll(
        '.ui-select-choices-row, .select2-results__option, .select2-result-selectable'
    )).filter(e => visible(e) && clean(e.textContent) === target);
    if (choices.length > 1) throw Error('More than one exact location option is visible.');
    if (choices.length === 1) choices[0].click();
    return selectedLocation(root, target);
};

if (action === 'element') return one(paths);
if (action === 'present') return !!one(paths);
if (action === 'set') { const e = one(paths); if (!e) return false; setValue(e, value); return true; }
if (action === 'click') {
    const e = one(paths);
    if (!e || e.disabled || e.getAttribute('aria-disabled') === 'true' || e.classList.contains('disabled')) return false;
    e.scrollIntoView({block: 'center'}); e.click(); return true;
}
if (action === 'row_matches') {
    const button = one(paths);
    const row = button && button.closest('tr');
    return !!button && (exactText(row, value) || exactText(row && row.previousElementSibling, value));
}
if (action === 'identity') {
    if (paths.id) { const e = one(paths.id); return !!e && clean(e.value || e.textContent) === value; }
    const form = one(paths.form);
    if (!form) return false;
    const candidates = Array.from(form.querySelectorAll('input')).filter(e => {
        const attrs = [e.id, e.name, e.getAttribute('ng-model'), e.getAttribute('data-ng-model'),
            e.getAttribute('placeholder'), e.getAttribute('aria-label')].join(' ');
        return visible(e) && /code|sku|product.?id|ma.?hang|ma.?san.?pham/.test(fold(attrs));
    });
    return candidates.some(e => clean(e.value) === value);
}
if (action === 'quantity') {
    const e = one(paths);
    if (!e) return null;
    const w = window.jQuery && window.jQuery(e).data('kendoNumericTextBox');
    return w ? w.value() : e.value;
}
if (action === 'location_selected') return selectedLocation(one(paths), value);
if (action === 'location_pick') return chooseLocation(one(paths), value);
if (action === 'location_search') {
    const root = one(paths);
    if (!root) return false;
    const found = widget(root);
    if (found) {
        const w = found.w;
        if (w.element && w.element[0] && !editable(w.element[0]))
            throw Error('The location selector is disabled or read-only.');
        w.open();
        if (w.search) w.search(value);
        else if (w.options.dataTextField) w.dataSource.filter({field: w.options.dataTextField, operator: 'eq', value});
        return true;
    }
    const toggle = root.querySelector('.ui-select-toggle, .select2-choice, .select2-selection');
    if (toggle && visible(toggle)) toggle.click();
    const input = Array.from(root.querySelectorAll('input')).find(e => visible(e) && editable(e)) ||
        (toggle && Array.from(document.querySelectorAll('.select2-container--open .select2-search__field'))
            .find(e => visible(e) && editable(e)));
    if (input) { setValue(input, value); return true; }
    return !!toggle && visible(toggle);
}
if (action === 'errors') {
    return [...new Set(Array.from(document.querySelectorAll(
        '.validation-summary-errors, .field-validation-error, .k-notification-error, .toast-error, .alert-danger, [class*="validation-error"]'
    )).filter(visible).map(e => clean(e.textContent)).filter(Boolean))].slice(0, 3).join('\n').slice(0, 700);
}
throw Error('Unknown DOM operation: ' + action);
"""


class WebsiteUploader:
    """One invocation owns one ChromeDriver connection, never the Chrome window."""

    def __init__(self, driver=None, *, timeout: float = TIMEOUT_SECONDS):
        self.driver = driver  # Dependency injection for offline workflow tests.
        self.timeout = timeout

    def _connect(self) -> None:
        if self.driver is not None:
            return
        try:
            from selenium import webdriver
        except ImportError as error:
            raise UploadError(
                "Install Selenium in the same venv as this app:\n\npython -m pip install -U selenium"
            ) from error
        options = webdriver.ChromeOptions()
        options.debugger_address = DEBUGGER_ADDRESS
        options.add_experimental_option("detach", True)
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(self.timeout)
            self.driver.set_script_timeout(self.timeout)
            # Also bound individual HTTP commands, not only polling waits.
            self.driver.command_executor.client_config.timeout = self.timeout
        except Exception as error:
            raise UploadError(
                f"Cannot attach to Chrome at {DEBUGGER_ADDRESS}. Open your debugging Chrome, "
                "log in, and leave the product list open. Selenium may need internet access "
                "on its first run to obtain the matching ChromeDriver.\n\n"
                + str(error).split("Stacktrace:")[0][:700]
            ) from error

    def _dom(self, action, paths=None, value=None):
        return self.driver.execute_script(DOM_SCRIPT, action, paths, value)

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

    def _choose_tab(self) -> None:
        original = self.driver.current_window_handle
        candidates = []
        for handle in self.driver.window_handles:
            self.driver.switch_to.window(handle)
            if TAB_URL_CONTAINS and TAB_URL_CONTAINS not in self.driver.current_url:
                continue
            if self._dom("present", SEARCH_XPATH):
                candidates.append(handle)
        if len(candidates) != 1:
            self.driver.switch_to.window(original)
            raise UploadError(
                "Keep exactly one matching product-list tab open in debugging Chrome. "
                "If needed, set TAB_URL_CONTAINS in mapper/web_upload.py."
            )
        self.driver.switch_to.window(candidates[0])
        if self._dom("present", FORM_XPATH) or self._dom("present", LOCATION_FORM_XPATH):
            raise UploadError("Finish or cancel the existing website edit dialog before uploading.")

    def _fill_and_enter(self, path: str, value: str) -> None:
        element = self._wait("finding an input", lambda: self._dom("element", path))
        if not self._dom("set", path, value):
            raise UploadError("The input disappeared before it could be filled.")
        element.send_keys("\ue007")  # Selenium Keys.ENTER; no JS keyboard-event shortcut.

    def _click(self, path: str, description: str) -> None:
        self._wait(description, lambda: self._dom("click", path), check_errors=True)

    def _identity_matches(self, product: UploadProduct) -> bool:
        return self._dom("identity", {"form": FORM_XPATH, "id": PRODUCT_ID_XPATH}, product.product_id)

    def _open_product(self, product: UploadProduct) -> None:
        self._fill_and_enter(SEARCH_XPATH, product.product_id)
        self._wait(
            f"finding the exact result for {product.product_id}",
            lambda: self._dom("row_matches", EDIT_XPATH, product.product_id),
            check_errors=True,
        )
        self._click(EDIT_XPATH, "opening the product edit form")
        self._wait("opening the edit form", lambda: self._dom("present", FORM_XPATH))
        self._wait(
            "checking the product ID (set PRODUCT_ID_XPATH if automatic detection fails)",
            lambda: self._identity_matches(product),
        )

    def _set_location(self, product: UploadProduct, progress: Callable[[str], None]) -> None:
        target = product.location_id
        self._wait("finding the location field", lambda: self._dom("present", LOCATION_FIELD_XPATH))
        if self._dom("location_pick", LOCATION_FIELD_XPATH, target):
            return
        if self._dom("location_search", LOCATION_FIELD_XPATH, target):
            try:
                self._wait("looking for an existing location", lambda: self._dom(
                    "location_pick", LOCATION_FIELD_XPATH, target
                ), timeout=5, check_errors=True)
                return
            except WaitExpired:
                pass
        progress(f"Creating location {target}…")
        self._click(CREATE_LOCATION_XPATH, "opening Add location")
        self._fill_and_enter(NEW_LOCATION_XPATH, target)
        try:
            self._wait("saving the location", lambda: not self._dom("present", LOCATION_FORM_XPATH), check_errors=True)
        except UploadError as error:
            raise UploadError(
                f"Could not create/select location {target}. If it already exists, select it in Chrome. "
                "The product Save button has not been pressed.\n\n" + str(error)
            ) from error
        self._wait("checking the selected location", lambda: self._dom(
            "location_pick", LOCATION_FIELD_XPATH, target
        ), check_errors=True)

    def _values_match(self, product: UploadProduct) -> bool:
        quantity = self._dom("quantity", QUANTITY_XPATH)
        # Avoid guessing whether commas/dots are decimal or grouping separators.
        matches_quantity = (type(quantity) is not bool and quantity is not None and
                            (quantity == product.stock_qty or str(quantity).strip() == str(product.stock_qty)))
        return (self._identity_matches(product) and matches_quantity and
                self._dom("location_selected", LOCATION_FIELD_XPATH, product.location_id))

    def upload(self, product: UploadProduct, progress: Callable[[str], None] = lambda _message: None) -> str:
        save_attempted = False
        try:
            progress("Connecting to Chrome…")
            self._connect()
            self._choose_tab()
            progress(f"Finding product {product.product_id}…")
            self._open_product(product)
            progress(f"Setting stock to {product.stock_qty}…")
            self._wait("finding the stock input", lambda: self._dom("present", QUANTITY_XPATH))
            if not self._dom("set", QUANTITY_XPATH, str(product.stock_qty)):
                raise UploadError("The stock input disappeared.")
            progress(f"Selecting location {product.location_id}…")
            self._set_location(product, progress)
            self._wait("checking quantity, product ID, and location before Save", lambda: self._values_match(product), check_errors=True)
            progress("Saving the product on the website…")
            # From here onward a timeout has an uncertain outcome. Never retry Save.
            save_attempted = True
            self._click(SAVE_XPATH, "pressing Save")
            self._wait("waiting for Save to finish", lambda: not self._dom("present", FORM_XPATH), check_errors=True)
            progress("Reloading the saved product to verify quantity and location…")
            self.driver.refresh()
            self._open_product(product)
            self._wait("verifying the saved values", lambda: self._values_match(product), check_errors=True)
            note = ""
            try:
                self.driver.refresh()  # Close the read-only verification edit, ready for next product.
            except Exception:
                note = " Close the verification form in Chrome before the next upload."
            return f"Uploaded and verified: {product.product_id} · qty {product.stock_qty} · {product.location_id}.{note}"
        except Exception as error:
            detail = str(error).split("Stacktrace:")[0][:1400]
            if save_attempted:
                raise UploadError(
                    "Save may have reached the website, but the result was not verified. "
                    "Check this product in Chrome before trying again. No automatic retry was made.\n\n" + detail
                ) from error
            raise UploadError(
                "Upload stopped before pressing the product Save button. "
                "Any new location already created may remain on the website.\n\n" + detail
            ) from error
        finally:
            if self.driver is not None:
                # Do NOT quit(): this is the user's existing logged-in browser.
                try:
                    self.driver.service.stop()
                except Exception:
                    pass
                self.driver = None
