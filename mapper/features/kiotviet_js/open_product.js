// Open one product's edit form through KiotViet's own Angular controller.
const sku = String(arguments[0] || '').trim();
const sleepMs = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

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
    const url = 'https://api-man1.kiotviet.vn/api/products/suggest' +
        '?tearm=' + encodeURIComponent(skuValue) +
        '&IncludeCombo=true&ShowAllItem=false&IsShowOnHand=true' +
        '&ExcludeProductIds=&IsGetTotalOnhand=false';

    const response = await fetch(url, {
        method: 'GET',
        credentials: 'omit',
        headers: apiHeaders(auth)
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

    const wanted = skuValue.replace(/[- ]/g, '').toUpperCase();
    const matches = products.filter(item =>
        String(item && item.Code || '').trim().replace(/[- ]/g, '').toUpperCase() === wanted
    );

    if (matches.length !== 1) throw Error('Exact unique SKU not found: ' + skuValue);
    return matches[0];
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
