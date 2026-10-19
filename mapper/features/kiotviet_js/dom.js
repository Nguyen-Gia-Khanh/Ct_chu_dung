// DOM adapter: selectors and site behaviour; values always arrive as arguments.
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
    if (action === 'edit_ready') {
        const form = one(paths);
        if (!form || !Array.from(form.querySelectorAll('input')).some(visible)) return false;
        // Hidden templates can contain braces; only rendered text must be bound.
        const nodes = document.createTreeWalker(form, NodeFilter.SHOW_TEXT);
        while (nodes.nextNode()) {
            if (visible(nodes.currentNode.parentElement) && /\{\{/.test(nodes.currentNode.nodeValue)) return false;
        }
        return true;
    }
    if (action === 'set') { const e = one(paths); if (!e) return false; setValue(e, value); return true; }
    if (action === 'click') {
        const e = one(paths);
        if (!e) return false;
        return targetClick(e);
    }
    if (action === 'identity') {
        if (paths.id) { const e = one(paths.id); return !!e && clean(e.value || e.textContent).replace(/[- ]/g, '').toUpperCase() === value; }
        const form = one(paths.form);
        if (!form) return false;
        const candidates = Array.from(form.querySelectorAll('input')).filter(e => {
            const attrs = [e.id, e.name, e.getAttribute('ng-model'), e.getAttribute('data-ng-model'),
                e.getAttribute('placeholder'), e.getAttribute('aria-label')].join(' ');
            return visible(e) && /code|sku|product.?id|ma.?hang|ma.?san.?pham/.test(fold(attrs));
        });
        return candidates.some(e => clean(e.value).replace(/[- ]/g, '').toUpperCase() === value);
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
