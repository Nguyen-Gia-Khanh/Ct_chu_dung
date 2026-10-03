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
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock
from time import monotonic, sleep
from typing import Callable

from .kiotviet_settings import validate_store_url, validate_tab_count


# Chrome connection and upload timings.
DEBUGGER_ADDRESS = "127.0.0.1:9222"
TIMEOUT_SECONDS = 20
STEP_DELAY_SECONDS = 2.0
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

# Usually detected from a Code/SKU/product-ID input in the edit form. If your
# site's input has no identifying attributes, put its exact XPath here.
PRODUCT_ID_XPATH = ""


class UploadError(RuntimeError):
    """An actionable error that can be shown without a browser stack trace."""


class WaitExpired(UploadError):
    pass


def _location_ids(value: str | tuple[str, ...]) -> tuple[str, ...]:
    parts = re.split(r"[,;\n]+", value) if isinstance(value, str) else value
    return tuple(dict.fromkeys(part.strip() for part in parts if part.strip()))


@dataclass(frozen=True)
class UploadProduct:
    product_id: str
    stock_qty: int
    location_id: str | tuple[str, ...]
    location_ids: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        ids = _location_ids(self.location_id)
        object.__setattr__(self, "location_ids", ids)
        object.__setattr__(self, "location_id", ", ".join(ids))
        if not self.product_id.strip() or not ids:
            raise ValueError("A product ID and a location ID are required.")
        if type(self.stock_qty) is not int or not 0 <= self.stock_qty <= 2**53 - 1:
            raise ValueError("Upload needs a known whole-number quantity from 0 to 9,007,199,254,740,991.")


@dataclass(frozen=True)
class LocationUpdate:
    product_id: str
    location_id: str | tuple[str, ...]
    location_ids: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        if isinstance(self.location_id, str) and self.location_id and not self.location_id.strip():
            raise ValueError("Use an empty location ID to clear the website location.")
        ids = _location_ids(self.location_id)
        object.__setattr__(self, "location_ids", ids)
        object.__setattr__(self, "location_id", ", ".join(ids))
        if not self.product_id.strip():
            raise ValueError("A product ID is required.")


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
# Browser arguments, never interpolated into executable JavaScript.
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
const targetClick = e => {
    if (!e || e.disabled || e.getAttribute('aria-disabled') === 'true' || e.classList.contains('disabled')) return false;
    const anchor = e.tagName === 'A' ? e : (e.closest ? e.closest('a') : null);
    if (anchor) {
        const href = anchor.getAttribute('href');
        if (!href || href === '#' || href.startsWith('javascript:')) {
            anchor.addEventListener('click', ev => ev.preventDefault(), {once: true});
        }
    }

    e.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
    return true;
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
const onlySelectedLocation = (root, target) => {
    if (!root) return false;
    const found = widget(root);
    if (found) {
        const w = found.w;
        const items = found.kind === 'kendoMultiSelect' ?
            Array.from(w.dataItems() || []) : [w.dataItem()].filter(Boolean);
        return items.length === 1 &&
            clean(field(items[0], w.options.dataTextField)) === target;
    }
    const selected = Array.from(root.querySelectorAll('select'))
        .flatMap(select => Array.from(select.selectedOptions))
        .map(option => clean(option.textContent))
        .filter(Boolean);
    if (selected.length) return selected.length === 1 && selected[0] === target;
    const labels = Array.from(root.querySelectorAll(
        '.ui-select-match, .select2-selection__rendered, .select2-chosen, .k-chip-content, .k-tag-text'
    )).filter(visible).filter(e => exactText(e, target));
    return labels.length === 1;
};
const onlySelectedLocations = (root, targets) => {
    if (!root || !Array.isArray(targets)) return false;
    const found = widget(root);
    if (!found || found.kind !== 'kendoMultiSelect') return false;
    const selected = Array.from(found.w.dataItems() || [])
        .map(item => clean(field(item, found.w.options.dataTextField)));
    return selected.length === targets.length &&
        new Set(selected).size === selected.length &&
        targets.every(target => selected.includes(target));
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
    if (choices.length === 1) targetClick(choices[0]);
    return selectedLocation(root, target);
};

const executeAction = () => {
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
    if (action === 'element') return !!one(paths);
    if (action === 'present') return !!one(paths);
    if (action === 'set') { const e = one(paths); if (!e) return false; setValue(e, value); return true; }
    if (action === 'click') {
        const e = one(paths);
        if (!e) return false;
        return targetClick(e);
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
    if (action === 'location_selected') {
        const root = one(paths);
        return value.length === 1 ? onlySelectedLocation(root, value[0]) :
            onlySelectedLocations(root, value);
    }
    if (action === 'location_clear') {
        const root = one(paths);
        if (!root) return false;
        const found = widget(root);
        if (!found || found.kind !== 'kendoMultiSelect') return false;
        const w = found.w;
        if (w.element && w.element[0] && !editable(w.element[0]))
            throw Error('The location selector is disabled or read-only.');
        w.value([]);
        w.trigger('change');
        return Array.from(w.value() || []).length === 0;
    }
    if (action === 'location_pick') return chooseLocation(one(paths), value);
    if (action === 'location_pick_ids') {
        const root = one(paths);
        if (!root || !value) return false;

        const targetIds = Array.isArray(value.ids) ? value.ids.map(clean) : [];
        const targetNames = Array.isArray(value.names) ? value.names.map(clean) : [];
        if (!targetIds.length || targetIds.length !== targetNames.length ||
            targetIds.some(id => !id) || targetNames.some(name => !name)) return false;

        const select = root.querySelector('select[data-role="multiselect"]');
        const w = window.jQuery && select && window.jQuery(select).data('kendoMultiSelect');
        if (!w) return false;

        if (targetIds.length === 1) {
            // Keep the established single-location update path.
            const current = Array.from(w.value() || []).map(String);
            if (current.length !== 1 || current[0] !== targetIds[0]) {
                w.value(targetIds);
                w.trigger('change');
            }
            return onlySelectedLocation(root, targetNames[0]);
        }

        // Several locations: clear the old selection, then add the full local set.
        // Every target shelf was resolved by the API before this action runs.
        w.value([]);
        w.trigger('change');
        if (Array.from(w.value() || []).length) return false;
        w.value(targetIds);
        w.trigger('change');

        const selectedIds = Array.from(w.value() || []).map(String);
        return selectedIds.length === targetIds.length &&
            targetIds.every(id => selectedIds.includes(id)) &&
            onlySelectedLocations(root, targetNames);
    }
    if (action === 'location_search') {
        const root = one(paths);
        if (!root) return false;
        const found = widget(root);
        if (found) {
            const w = found.w;
            if (w.element && w.element[0] && !editable(w.element[0]))
                throw Error('The location selector is disabled or read-only.');
            if (w.search) w.search(value);
            else if (w.options.dataTextField) w.dataSource.filter({field: w.options.dataTextField, operator: 'eq', value});
            return true;
        }
        const toggle = root.querySelector('.ui-select-toggle, .select2-choice, .select2-selection');
        if (toggle && visible(toggle)) targetClick(toggle);
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
};

return executeAction();
"""


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

    def is_connected(self) -> bool:
        return (self.page is not None and not self.page.is_closed()
                and (self.browser is None or self.browser.is_connected()))

    def connect(self, progress: Callable[[str], None] = lambda _message: None) -> str:
        """Attach and check the saved store's logged-in product page."""
        self.store_url = validate_store_url(self.store_url)
        progress("Connecting to Chrome...")
        self._connect()
        progress("Checking the KiotViet product tab...")
        self._choose_tab()
        return "Chrome connected. Ready to update the saved KiotViet store."

    def disconnect(self) -> None:
        """Disconnect the transport; never close the user's browser."""
        try:
            if self.playwright is not None:
                self.playwright.stop()
        finally:
            self.page = self.browser = self.playwright = None

    def _connect(self) -> None:
        if self.browser is not None or self.page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise UploadError(
                "Install Playwright in the same venv as this app:\n\n"
                "python -m pip install playwright"
            ) from error
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(
                f"http://{DEBUGGER_ADDRESS}", timeout=self.timeout * 1000
            )
        except Exception as error:
            self.disconnect()
            raise UploadError(
                f"Cannot attach to Chrome at {DEBUGGER_ADDRESS}. Open your debugging Chrome, "
                "log in to the saved store, and leave its Products page open.\n\n"
                + str(error)[:700]
            ) from error

    def _evaluate(self, script, *args):
        return self.page.evaluate("(args) => { const arguments = args; " + script + "\n}", list(args))

    def _evaluate_async(self, script, *args):
        # Existing callbacks resolve a Promise; timeouts never retry a website write.
        wrapper = """(input) => new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(Error('Browser operation timed out')), input.timeout);
            const arguments = [...input.args, result => { clearTimeout(timer); resolve(result); }];
        """ + script + "\n})"
        return self.page.evaluate(wrapper, {"args": list(args), "timeout": self.timeout * 1000})

    def _dom(self, action, paths=None, value=None):
        return self._evaluate(DOM_SCRIPT, action, paths, value)

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

    def _matches_store(self, page) -> bool:
        try:
            return validate_store_url(page.url) == self.store_url
        except ValueError:
            return False

    def _choose_tab(self) -> None:
        if self.page is None or self.page.is_closed():
            self.page = next(
                (page for context in self.browser.contexts for page in context.pages
                 if self._matches_store(page)), None
            )
        if self.page is None or not self._matches_store(self.page):
            raise UploadError(
                "Open the saved KiotViet Products URL in debugging Chrome and log in first: "
                + self.store_url
            )
        self.page.set_default_timeout(self.timeout * 1000)
        # Cache settings are applied to this page rather than the whole browser.
        session = self.page.context.new_cdp_session(self.page)
        try:
            session.send("Network.enable")
            session.send("Network.setCacheDisabled", {"cacheDisabled": True})
        finally:
            session.detach()
        if self._dom("present", FORM_XPATH) or self._dom("present", LOCATION_FORM_XPATH):
            raise UploadError("Finish or cancel the existing website edit dialog before uploading.")
        self._wait("waiting for the KiotViet product page", lambda: self._dom("product_page"))

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
        jobs = Queue()
        for product in products:
            jobs.put(product)
        stopped, state_lock = Event(), Lock()
        completed, errors, results = [], [], []
        workers = min(tab_count, len(products))

        def worker():
            uploader = WebsiteUploader(
                store_url=self.store_url, timeout=self.timeout,
                step_delay=self.step_delay, location_lock=self.location_lock,
            )
            product = None
            owned_page = None
            try:
                uploader.connect(progress)
                if workers > 1:
                    # Keep the source tab untouched. Every worker owns one new tab.
                    source_page = uploader.page
                    try:
                        uploader._new_upload_tab()
                    finally:
                        if uploader.page is not source_page:
                            owned_page = uploader.page
                while True:
                    with state_lock:
                        if stopped.is_set():
                            break
                        try:
                            product = jobs.get_nowait()
                        except Empty:
                            break
                    report = lambda text: progress(f"{product.product_id}: {text}")
                    action = uploader.modify_location if location_only else uploader.upload
                    result = action(product, report, save=save)
                    with state_lock:
                        completed.append(product.product_id)
                        results.append(result)
                        item_done(product.product_id)
                        progress(f"[{len(completed)}/{len(products)}] Finished {product.product_id}.")
                    product = None
            except Exception as error:
                with state_lock:
                    stopped.set()
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
            futures = [pool.submit(worker) for _ in range(workers)]
            for future in futures:
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
        result = self._evaluate_async(OPEN_PRODUCT_SCRIPT, product.product_id)
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
        result = self._evaluate_async(GET_SHELVES_SCRIPT)
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

    def _set_location(
        self,
        product: UploadProduct | LocationUpdate,
        progress: Callable[[str], None],
    ) -> None:
        self._wait("finding the location field", lambda: self._dom("present", LOCATION_FIELD_XPATH))
        if not product.location_ids:
            self._clear_location()
            return

        with self.location_lock:
            # The API response is the source of truth for whether each location exists.
            location_names, ids_by_name = self._get_shelves_by_name()
            for target in product.location_ids:
                if target in location_names:
                    continue
                progress(f"Creating location {target}…")
                self._click(CREATE_LOCATION_XPATH, "opening Add location")
                try:
                    self._fill_input(NEW_LOCATION_XPATH, target)
                    self._click(SAVE_LOCATION_XPATH, "saving the new location")
                    self._wait(
                        "waiting for the new location dialog to close",
                        lambda: not self._dom("present", LOCATION_FORM_XPATH),
                        check_errors=True,
                    )
                except UploadError as error:
                    raise UploadError(
                        f"Could not create location {target}. The product Save button has not been pressed.\n\n"
                        + str(error)
                    ) from error
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    location_names, ids_by_name = self._get_shelves_by_name()
                    if target in location_names:
                        break
                    sleep(0.4)
                if target not in location_names:
                    raise UploadError(
                        f"KiotViet closed the Create location form, but {target!r} did not appear in /api/shelves."
                    )

        progress(f"Selecting locations {product.location_id}…")
        self._select_location_ids(product, ids_by_name)

    def _clear_location(self) -> None:
        self._wait("finding the location field", lambda: self._dom("present", LOCATION_FIELD_XPATH))
        if not self._dom("location_clear", LOCATION_FIELD_XPATH):
            raise UploadError("The website location selector could not be cleared.")

    def _save_product(
        self,
        product: UploadProduct | LocationUpdate,
        progress: Callable[[str], None],
        *,
        location_only: bool = False,
    ) -> str:
        """PRODUCTION STEP: press Lưu once and wait for the edit form to close."""
        progress("Saving the location on the website…" if location_only else "Saving the product on the website…")

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

        # Keep the requested final-save pause. Read-back verification stays
        # available behind a separate switch because it visibly refreshes,
        # reopens the product, then refreshes once more to close the form.
        self._pause()

        if VERIFY_AFTER_SAVE:
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

            if location_only:
                if not product.location_id:
                    return f"Location cleared and verified: {product.product_id}.{note}"
                return f"Location updated and verified: {product.product_id} · {product.location_id}.{note}"
            return f"Uploaded and verified: {product.product_id} · qty {product.stock_qty} · {product.location_id}.{note}"

        if location_only:
            if not product.location_id:
                return f"Location cleared: {product.product_id}."
            return f"Location saved: {product.product_id} · {product.location_id}."
        return f"Uploaded: {product.product_id} · qty {product.stock_qty} · {product.location_id}."

    def upload(
        self,
        product: UploadProduct,
        progress: Callable[[str], None] = lambda _message: None,
        *,
        save: bool | None = None,
    ) -> str:
        """Fill stock/location for one product and optionally save the edit."""
        if not self.is_connected():
            raise UploadError(
                "Chrome is not connected. Press Connect Chrome on the main tab bar first."
            )
        should_save = SAVE_ON_UPLOAD if save is None else save
        try:
            progress("Checking the connected Chrome tab…")
            self._choose_tab()

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

            # A batch explicitly opts into Save so Chrome can advance to its
            # next product. Single-product calls keep the global safety switch.
            if should_save:
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

    def modify_location(
        self,
        product: LocationUpdate,
        progress: Callable[[str], None] = lambda _message: None,
        *,
        save: bool | None = None,
    ) -> str:
        """Change only the website location; never inspect or modify stock."""
        if not self.is_connected():
            raise UploadError(
                "Chrome is not connected. Press Connect Chrome on the main tab bar first."
            )
        should_save = SAVE_ON_UPLOAD if save is None else save
        try:
            progress("Checking the connected Chrome tab…")
            self._choose_tab()

            progress(f"Finding product {product.product_id}…")
            self._open_product(product)

            if product.location_id:
                progress(f"Selecting location {product.location_id}…")
                self._set_location(product, progress)
                self._wait(
                    "checking product and location before Save",
                    lambda: self._location_values_match(product),
                    check_errors=True,
                )
            else:
                progress("Clearing the website location…")
                self._set_location(product, progress)

            if should_save:
                return self._save_product(product, progress, location_only=True)

            if not product.location_id:
                return "Location cleared in the edit form. Press Lưu manually in Chrome."
            return "Location filled. Stock was untouched. Press Lưu manually in Chrome."

        except UploadError:
            raise
        except Exception as error:
            detail = str(error).split("Stacktrace:")[0][:1400]
            raise UploadError(
                "Location update stopped before the final Save step. "
                "Stock was not changed. Any new location already created may remain on the website.\n\n"
                + detail
            ) from error
