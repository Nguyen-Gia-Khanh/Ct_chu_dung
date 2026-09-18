"""Upload ONE placement to the product page in an existing Chrome session.

Selenium is optional and imported only when Upload is clicked. This module never
opens SQLite, commits a shelf, logs in, or starts a product batch. The selected
SKU is looked up through the current KiotViet browser session, then the remaining
form fields are changed one step at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable


# Change these settings here if your Chrome port or website changes.
DEBUGGER_ADDRESS = "127.0.0.1:9222"
TAB_URL_CONTAINS = ""  # Optional URL fragment when several product tabs are open.
TIMEOUT_SECONDS = 20
STEP_DELAY_SECONDS = 2.0
SAVE_ON_UPLOAD = False  # Keep False while testing; set True only for production.
SET_LOCATION_ON_UPLOAD = True  # Set False to skip all location lookup/create/select work.

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


# This replaces the old search-box + fixed-result-row XPaths. It runs inside the
# already logged-in KiotViet tab, keeps the JWT inside that tab, waits for the API
# lookup, and asks KiotViet's own Angular controller to open the exact product.
OPEN_PRODUCT_SCRIPT = r"""
const sku = String(arguments[0] || '').trim();
const callback = arguments[arguments.length - 1];
let finished = false;

const finish = result => {
    if (finished) return;
    finished = true;
    callback(result);
};

const fail = message => finish({
    ok: false,
    error: String(message || 'Unknown browser error')
});

const sleepMs = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

const decodeJwt = token => {
    try {
        let part = token.split('.')[1];
        part = part.replace(/-/g, '+').replace(/_/g, '/');
        part += '='.repeat((4 - part.length % 4) % 4);
        const bytes = Uint8Array.from(atob(part), character => character.charCodeAt(0));
        return JSON.parse(new TextDecoder().decode(bytes));
    } catch (_error) {
        return null;
    }
};

const findCurrentAuth = () => {
    const candidates = [];

    for (const storageName of ['localStorage', 'sessionStorage']) {
        let storage;
        try {
            storage = window[storageName];
        } catch (_error) {
            continue;
        }

        for (let index = 0; index < storage.length; index += 1) {
            const key = storage.key(index);
            const value = storage.getItem(key) || '';
            const matches = value.match(
                /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g
            ) || [];

            for (const token of matches) {
                const payload = decodeJwt(token);
                if (payload) candidates.push({token, payload});
            }
        }
    }

    const cookieMatches = document.cookie.match(
        /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g
    ) || [];

    for (const token of cookieMatches) {
        const payload = decodeJwt(token);
        if (payload) candidates.push({token, payload});
    }

    const now = Date.now() / 1000;
    return candidates
        .filter(item => !item.payload.exp || item.payload.exp > now)
        .sort((left, right) => {
            const leftKiotViet = left.payload.kvrcode ? 1 : 0;
            const rightKiotViet = right.payload.kvrcode ? 1 : 0;
            if (leftKiotViet !== rightKiotViet) return rightKiotViet - leftKiotViet;
            return (right.payload.exp || 0) - (left.payload.exp || 0);
        })[0] || null;
};

const findUpdateProductScopeNow = () => {
    if (!window.angular) return null;

    const checkedScopes = new Set();
    const checkScopeChain = start => {
        let current = start;
        while (current) {
            const key = current.$id != null ? 'id:' + current.$id : current;
            if (checkedScopes.has(key)) break;
            checkedScopes.add(key);
            if (typeof current.UpdateProduct === 'function') return current;
            current = current.$parent;
        }
        return null;
    };

    const elements = [
        document.documentElement,
        document.body,
        ...document.querySelectorAll(
            '.ng-scope, [ng-controller], [data-ng-controller], [ng-view], [data-ng-view], [ui-view]'
        )
    ].filter(Boolean);

    for (const element of elements) {
        try {
            const wrapped = window.angular.element(element);
            const normal = typeof wrapped.scope === 'function' ? wrapped.scope() : null;
            const fromNormal = checkScopeChain(normal);
            if (fromNormal) return fromNormal;

            const isolated = typeof wrapped.isolateScope === 'function' ? wrapped.isolateScope() : null;
            const fromIsolated = checkScopeChain(isolated);
            if (fromIsolated) return fromIsolated;
        } catch (_error) {
            // Some nodes are outside Angular; ignore them.
        }
    }

    // Fallback: traverse Angular's scope tree directly. This catches controllers
    // whose scope exists even when the Edit button has not been rendered yet.
    let injector = null;
    for (const element of elements) {
        try {
            const candidate = window.angular.element(element).injector();
            if (candidate) {
                injector = candidate;
                break;
            }
        } catch (_error) {
            // Keep searching.
        }
    }

    if (!injector) return null;

    try {
        const root = injector.get('$rootScope');
        const stack = [root];
        const visited = new Set();

        while (stack.length) {
            const scope = stack.pop();
            if (!scope) continue;
            const key = scope.$id != null ? scope.$id : scope;
            if (visited.has(key)) continue;
            visited.add(key);

            if (typeof scope.UpdateProduct === 'function') return scope;

            for (let child = scope.$$childHead; child; child = child.$$nextSibling) {
                stack.push(child);
            }
        }
    } catch (_error) {
        return null;
    }

    return null;
};

const waitForUpdateProductScope = async timeoutMs => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        const scope = findUpdateProductScopeNow();
        if (scope) return scope;
        await sleepMs(200);
    }
    return null;
};

const lookupProduct = async (skuValue, auth) => {
    const claims = auth.payload;
    const retailer = String(claims.kvrcode || location.hostname.split('.')[0] || '');
    const branchId = String(claims.kvbid || '');
    const groupId = String(claims.kvrgid || '');

    const url = 'https://api-man1.kiotviet.vn/api/products/suggest' +
        '?tearm=' + encodeURIComponent(skuValue) +
        '&IncludeCombo=true&ShowAllItem=false&IsShowOnHand=true' +
        '&ExcludeProductIds=&IsGetTotalOnhand=false';

    const response = await fetch(url, {
        method: 'GET',
        credentials: 'omit',
        headers: {
            authorization: 'Bearer ' + auth.token,
            branchid: branchId,
            retailer,
            'x-group-id': groupId,
            'x-retailer-code': retailer
        }
    });

    if (!response.ok) {
        const details = (await response.text()).slice(0, 500);
        throw Error('Product lookup failed (' + response.status + '): ' + details);
    }

    const payload = await response.json();
    const products = Array.isArray(payload) ? payload :
        [payload && payload.Data, payload && payload.data,
         payload && payload.Products, payload && payload.products]
            .find(Array.isArray);

    if (!products) throw Error('KiotViet returned an unexpected product-search response.');

    const wanted = skuValue.toLowerCase();
    const product = products.find(item =>
        String(item && item.Code || '').trim().toLowerCase() === wanted
    );

    if (!product) throw Error('Exact SKU not found: ' + skuValue);
    return product;
};

(async () => {
    try {
        if (!sku) return fail('The product ID is empty.');
        if (!window.angular) return fail('KiotViet Angular is not available on this tab.');

        const auth = findCurrentAuth();
        if (!auth) return fail('Could not find the current KiotViet token in browser storage.');

        // Do the API lookup first; it does not depend on the detail/Edit UI being rendered.
        const product = await lookupProduct(sku, auth);

        // UpdateProduct belongs to the product-list Angular scope. Search the whole
        // scope tree instead of requiring the Chỉnh sửa button to already exist.
        const scope = await waitForUpdateProductScope(10000);
        if (!scope) {
            return fail(
                'KiotViet product controller is not loaded yet. ' +
                'Leave the Hàng hóa > Danh sách hàng hóa page open and wait for the list to finish loading.'
            );
        }

        const productForEdit = Object.assign({}, scope.dataItem || {}, product);
        scope.$applyAsync(() => {
            try {
                scope.UpdateProduct(productForEdit);
                finish({
                    ok: true,
                    product_id: String(product.Code || sku),
                    kiotviet_id: String(product.Id || '')
                });
            } catch (error) {
                fail(error && error.message ? error.message : error);
            }
        });
    } catch (error) {
        fail(error && error.message ? error.message : error);
    }
})();
"""


# Read KiotViet's current shelf/location master list directly from the same
# authenticated browser session. The JWT never leaves the KiotViet tab.
GET_SHELVES_SCRIPT = r"""
const callback = arguments[arguments.length - 1];
let finished = false;

const finish = result => {
    if (finished) return;
    finished = true;
    callback(result);
};
const fail = message => finish({ok: false, error: String(message || 'Unknown browser error')});

const decodeJwt = token => {
    try {
        let part = token.split('.')[1];
        part = part.replace(/-/g, '+').replace(/_/g, '/');
        part += '='.repeat((4 - part.length % 4) % 4);
        const bytes = Uint8Array.from(atob(part), character => character.charCodeAt(0));
        return JSON.parse(new TextDecoder().decode(bytes));
    } catch (_error) {
        return null;
    }
};

const findCurrentAuth = () => {
    const candidates = [];

    for (const storageName of ['localStorage', 'sessionStorage']) {
        let storage;
        try {
            storage = window[storageName];
        } catch (_error) {
            continue;
        }

        for (let index = 0; index < storage.length; index += 1) {
            const key = storage.key(index);
            const value = storage.getItem(key) || '';
            const matches = value.match(
                /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g
            ) || [];

            for (const token of matches) {
                const payload = decodeJwt(token);
                if (payload) candidates.push({token, payload});
            }
        }
    }

    const cookieMatches = document.cookie.match(
        /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g
    ) || [];
    for (const token of cookieMatches) {
        const payload = decodeJwt(token);
        if (payload) candidates.push({token, payload});
    }

    const now = Date.now() / 1000;
    return candidates
        .filter(item => !item.payload.exp || item.payload.exp > now)
        .sort((left, right) => {
            const leftKiotViet = left.payload.kvrcode ? 1 : 0;
            const rightKiotViet = right.payload.kvrcode ? 1 : 0;
            if (leftKiotViet !== rightKiotViet) return rightKiotViet - leftKiotViet;
            return (right.payload.exp || 0) - (left.payload.exp || 0);
        })[0] || null;
};

(async () => {
    try {
        const auth = findCurrentAuth();
        if (!auth) return fail('Could not find the current KiotViet token in browser storage.');

        const claims = auth.payload;
        const retailer = String(claims.kvrcode || location.hostname.split('.')[0] || '');
        const branchId = String(claims.kvbid || '');
        const groupId = String(claims.kvrgid || '');

        const response = await fetch(
            'https://api-man1.kiotviet.vn/api/shelves?%24inlinecount=allpages',
            {
                method: 'GET',
                credentials: 'omit',
                headers: {
                    authorization: 'Bearer ' + auth.token,
                    branchid: branchId,
                    retailer,
                    'x-group-id': groupId,
                    'x-retailer-code': retailer
                }
            }
        );

        if (!response.ok) {
            const details = (await response.text()).slice(0, 500);
            return fail('Shelf lookup failed (' + response.status + '): ' + details);
        }

        const payload = await response.json();
        const shelves = Array.isArray(payload) ? payload : payload && payload.Data;
        if (!Array.isArray(shelves)) return fail('KiotViet returned an unexpected shelves response.');

        finish({
            ok: true,
            shelves: shelves.map(item => ({
                id: String(item && item.Id || ''),
                name: String(item && item.Name || '').trim()
            })).filter(item => item.id && item.name)
        });
    } catch (error) {
        fail(error && error.message ? error.message : error);
    }
})();
"""


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

if (action === 'product_page') {
    const host = String(location.hostname || '').toLowerCase();
    const href = String(location.href || '');
    return !!window.angular && host.endsWith('.kiotviet.vn') && /\/man\/.*#\/Products/i.test(href);
}
if (action === 'product_controller') {
    if (!window.angular) return false;
    const elements = [document.documentElement, document.body,
        ...document.querySelectorAll('.ng-scope, [ng-controller], [data-ng-controller]')].filter(Boolean);
    const seen = new Set();
    for (const element of elements) {
        try {
            let scope = window.angular.element(element).scope();
            while (scope) {
                const key = scope.$id != null ? scope.$id : scope;
                if (seen.has(key)) break;
                seen.add(key);
                if (typeof scope.UpdateProduct === 'function') return true;
                scope = scope.$parent;
            }
        } catch (_error) {}
    }
    return false;
}
if (action === 'element') return one(paths);
if (action === 'present') return !!one(paths);
if (action === 'set') { const e = one(paths); if (!e) return false; setValue(e, value); return true; }
if (action === 'click') {
    const e = one(paths);
    if (!e || e.disabled || e.getAttribute('aria-disabled') === 'true' || e.classList.contains('disabled')) return false;
    e.scrollIntoView({block: 'center'}); e.click(); return true;
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
if (action === 'location_pick_id') {
    const root = one(paths);
    if (!root || !value) return false;

    const targetId = clean(value.id);
    const targetName = clean(value.name);
    if (!targetId || !targetName) return false;

    const select = root.querySelector('select[data-role="multiselect"]');
    const w = window.jQuery && select && window.jQuery(select).data('kendoMultiSelect');
    if (!w) return false;

    const current = Array.from(w.value() || []).map(String);
    if (!current.includes(targetId)) {
        w.value([...new Set([...current, targetId])]);
        w.trigger('change');
    }
    if (w.close) w.close();

    return selectedLocation(root, targetName);
}
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

    def __init__(
        self,
        driver=None,
        *,
        timeout: float = TIMEOUT_SECONDS,
        step_delay: float = STEP_DELAY_SECONDS,
    ):
        self.driver = driver  # Dependency injection for offline workflow tests.
        self.timeout = timeout
        self.step_delay = max(0.0, step_delay)

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

    def _pause(self) -> None:
        if self.step_delay:
            sleep(self.step_delay)

    def _choose_tab(self) -> None:
        original = self.driver.current_window_handle
        handles = list(self.driver.window_handles)
        eligible = []
        product_pages = []

        for handle in handles:
            try:
                self.driver.switch_to.window(handle)
                if TAB_URL_CONTAINS and TAB_URL_CONTAINS not in self.driver.current_url:
                    continue
                eligible.append(handle)
                if self._dom("product_page"):
                    product_pages.append(handle)
            except Exception:
                # Ignore internal/closing Chrome tabs that cannot run page JavaScript.
                continue

        if len(product_pages) == 1:
            selected = product_pages[0]
        elif len(eligible) == 1:
            selected = eligible[0]
        else:
            self.driver.switch_to.window(original)
            if not eligible:
                raise UploadError(
                    "Chrome is connected, but no accessible tab matches TAB_URL_CONTAINS. "
                    "Leave it blank or set it to part of your KiotViet product-page URL."
                )
            if len(product_pages) > 1:
                raise UploadError(
                    f"Chrome exposes {len(product_pages)} KiotViet product-list tabs. Close the extras or set "
                    "TAB_URL_CONTAINS to a unique part of the tab URL."
                )
            raise UploadError(
                f"Chrome exposes {len(eligible)} possible tabs but none is the KiotViet product-list page. "
                "Open Hàng hóa > Danh sách hàng hóa, or set TAB_URL_CONTAINS to that tab."
            )

        self.driver.switch_to.window(selected)
        if self._dom("present", FORM_XPATH) or self._dom("present", LOCATION_FORM_XPATH):
            raise UploadError("Finish or cancel the existing website edit dialog before uploading.")

        try:
            self._wait(
                "waiting for the KiotViet product page",
                lambda: self._dom("product_page"),
            )
        except WaitExpired as error:
            raise UploadError(
                "The connected tab is not ready on Hàng hóa > Danh sách hàng hóa. "
                "Open that page and wait for it to finish loading, then try again."
            ) from error

    def _fill_and_enter(self, path: str, value: str) -> None:
        element = self._wait("finding an input", lambda: self._dom("element", path))
        if not self._dom("set", path, value):
            raise UploadError("The input disappeared before it could be filled.")
        element.send_keys("\ue007")  # Selenium Keys.ENTER; no JS keyboard-event shortcut.

    def _click(self, path: str, description: str) -> None:
        self._wait(description, lambda: self._dom("click", path), check_errors=True)

    def _identity_matches(self, product: UploadProduct) -> bool:
        return self._dom("identity", {"form": FORM_XPATH, "id": PRODUCT_ID_XPATH}, product.product_id)

    def _stock_matches(self, product: UploadProduct) -> bool:
        quantity = self._dom("quantity", QUANTITY_XPATH)
        if type(quantity) is bool or quantity is None:
            return False
        return quantity == product.stock_qty or str(quantity).strip() == str(product.stock_qty)

    def _location_matches(self, product: UploadProduct) -> bool:
        return bool(self._dom("location_selected", LOCATION_FIELD_XPATH, product.location_id))

    def _all_values_match(self, product: UploadProduct) -> bool:
        return (
            self._identity_matches(product)
            and self._stock_matches(product)
            and (not SET_LOCATION_ON_UPLOAD or self._location_matches(product))
        )

    def _open_product(self, product: UploadProduct) -> None:
        result = self.driver.execute_async_script(OPEN_PRODUCT_SCRIPT, product.product_id)
        if not isinstance(result, dict) or not result.get("ok"):
            detail = result.get("error") if isinstance(result, dict) else repr(result)
            raise UploadError(f"Could not open product {product.product_id}: {detail}")

        self._wait("opening the edit form", lambda: self._dom("present", FORM_XPATH))
        self._wait(
            "checking the product ID (set PRODUCT_ID_XPATH if automatic detection fails)",
            lambda: self._identity_matches(product),
        )

    def _set_stock(self, product: UploadProduct) -> None:
        self._wait("finding the stock input", lambda: self._dom("present", QUANTITY_XPATH))
        if not self._dom("set", QUANTITY_XPATH, str(product.stock_qty)):
            raise UploadError("The stock input disappeared.")
        self._wait("checking the stock quantity", lambda: self._stock_matches(product), check_errors=True)

    def _get_shelves_by_name(self) -> tuple[set[str], dict[str, str]]:
        """Return ({location names}, {location name: KiotViet shelf ID}) from /api/shelves."""
        result = self.driver.execute_async_script(GET_SHELVES_SCRIPT)
        if not isinstance(result, dict) or not result.get("ok"):
            detail = result.get("error") if isinstance(result, dict) else repr(result)
            raise UploadError(f"Could not read KiotViet locations: {detail}")

        shelves = result.get("shelves")
        if not isinstance(shelves, list):
            raise UploadError("KiotViet returned an invalid location list.")

        names: set[str] = set()
        ids_by_name: dict[str, str] = {}

        for shelf in shelves:
            if not isinstance(shelf, dict):
                continue
            name = str(shelf.get("name") or "").strip()
            shelf_id = str(shelf.get("id") or "").strip()
            if not name or not shelf_id:
                continue
            if name in ids_by_name and ids_by_name[name] != shelf_id:
                raise UploadError(
                    f"KiotViet has duplicate location name {name!r} with multiple shelf IDs."
                )
            names.add(name)
            ids_by_name[name] = shelf_id

        return names, ids_by_name

    def _select_location_id(self, product: UploadProduct, shelf_id: str) -> None:
        selected = self._dom(
            "location_pick_id",
            LOCATION_FIELD_XPATH,
            {"id": str(shelf_id), "name": product.location_id},
        )
        if not selected:
            raise UploadError(
                f"Location {product.location_id} exists in KiotViet as shelf ID {shelf_id}, "
                "but the edit form could not select it."
            )
        self._wait(
            "checking the selected location",
            lambda: self._location_matches(product),
            check_errors=True,
        )

    def _set_location(self, product: UploadProduct, progress: Callable[[str], None]) -> None:
        target = product.location_id.strip()
        self._wait("finding the location field", lambda: self._dom("present", LOCATION_FIELD_XPATH))

        # The API response is the source of truth for whether this location already exists.
        location_names, ids_by_name = self._get_shelves_by_name()

        if target in location_names:
            progress(f"Selecting existing location {target}…")
            self._select_location_id(product, ids_by_name[target])
            return

        # The location is genuinely absent from KiotViet, so create it once through
        # the site's existing UI. Most warehouse slots are expected to take this path.
        progress(f"Creating location {target}…")
        self._click(CREATE_LOCATION_XPATH, "opening Add location")
        self._fill_and_enter(NEW_LOCATION_XPATH, target)

        try:
            self._wait(
                "saving the location",
                lambda: not self._dom("present", LOCATION_FORM_XPATH),
                check_errors=True,
            )
        except UploadError as error:
            raise UploadError(
                f"Could not create location {target}. The product Save button has not been pressed.\n\n"
                + str(error)
            ) from error

        # Re-read /api/shelves after creation so we use KiotViet's real new shelf ID,
        # rather than assuming what the UI generated.
        deadline = monotonic() + 5
        new_id = None
        while monotonic() < deadline:
            location_names, ids_by_name = self._get_shelves_by_name()
            if target in location_names:
                new_id = ids_by_name[target]
                break
            sleep(0.4)

        if not new_id:
            raise UploadError(
                f"KiotViet closed the Create location form, but {target!r} did not appear in /api/shelves."
            )

        progress(f"Selecting new location {target}…")
        self._select_location_id(product, new_id)

    def _save_product(self, product: UploadProduct, progress: Callable[[str], None]) -> str:
        """PRODUCTION STEP: press Lưu once, then reload and verify the saved values."""
        progress("Saving the product on the website…")

        try:
            # From this call onward a timeout has an uncertain outcome. Never retry Save.
            self._click(SAVE_XPATH, "pressing Save")
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

        progress("Reloading the saved product to verify quantity and location…")
        self.driver.refresh()
        self._wait("waiting for the product page after reload", lambda: self._dom("product_page"))
        self._pause()
        self._open_product(product)
        self._wait("verifying the saved values", lambda: self._all_values_match(product), check_errors=True)

        note = ""
        try:
            self.driver.refresh()  # Close the verification edit, ready for next product.
        except Exception:
            note = " Close the verification form in Chrome before the next upload."

        return (
            f"Uploaded and verified: {product.product_id} · qty {product.stock_qty} · "
            f"{product.location_id}.{note}"
        )

    def upload(self, product: UploadProduct, progress: Callable[[str], None] = lambda _message: None) -> str:
        try:
            progress("Connecting to Chrome…")
            self._connect()
            self._choose_tab()

            self._pause()
            progress(f"Finding product {product.product_id}…")
            self._open_product(product)

            progress(f"Setting stock to {product.stock_qty}…")
            self._set_stock(product)

            if SET_LOCATION_ON_UPLOAD:
                progress(f"Selecting location {product.location_id}…")
                self._set_location(product, progress)

            self._wait(
                "checking product fields before Save",
                lambda: self._all_values_match(product),
                check_errors=True,
            )

            # PRODUCTION ONLY. Keep SAVE_ON_UPLOAD = False while testing.
            if SAVE_ON_UPLOAD:
                return self._save_product(product, progress)

            return "Fields filled. Press Lưu manually in Chrome."

        except UploadError:
            raise
        except Exception as error:
            detail = str(error).split("Stacktrace:")[0][:1400]
            raise UploadError(
                "Upload stopped before the final Save step. "
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
