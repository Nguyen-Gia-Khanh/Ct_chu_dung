// Shared by the async KiotViet scripts: one callback result and the current login token.
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

// KiotViet API headers for the logged-in retailer; the JWT never leaves this tab.
const apiHeaders = auth => {
    const claims = auth.payload;
    const retailer = String(claims.kvrcode || location.hostname.split('.')[0] || '');
    return {
        authorization: 'Bearer ' + auth.token,
        branchid: String(claims.kvbid || ''),
        retailer,
        'x-group-id': String(claims.kvrgid || ''),
        'x-retailer-code': retailer
    };
};
