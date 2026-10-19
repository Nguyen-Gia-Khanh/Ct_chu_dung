// Read KiotViet's location (shelf) master list from the logged-in tab.
(async () => {
    try {
        const auth = findCurrentAuth();
        if (!auth) return fail('Could not find the current KiotViet token in browser storage.');

        const response = await fetch(
            'https://api-man1.kiotviet.vn/api/shelves?%24inlinecount=allpages',
            {
                method: 'GET',
                credentials: 'omit',
                headers: apiHeaders(auth)
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
