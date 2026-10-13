These are unmodified reader assets from **zxing-wasm 3.1.5**:

- `reader.js`: npm `dist/iife/reader/index.js`.
- `zxing_reader.wasm`: npm `dist/reader/zxing_reader.wasm`.
- `LICENSE.zxing-wasm`: package MIT license.
- `LICENSE.zxing-cpp`: bundled C++ decoder's Apache 2.0 license.

Source: https://github.com/Sec-ant/zxing-wasm

ZXing-C++ revision: `2ecec3f5be0ee803f6e14a5a2c7028c0cfe525b4`
(https://github.com/zxing-cpp/zxing-cpp).

The npm archive was checked against registry integrity before extracting:

```
https://registry.npmjs.org/zxing-wasm/-/zxing-wasm-3.1.5.tgz
sha512-jmxXvTCR/qZxMz2XwR6V+nL2BlDTD1aux7ZWSH9BV77TG9u4k0VyHba/NCCHBHJ60Wg6VV0QL/SMlJczKhJI4w==
```

WASM SHA-256: `aecc1876de036c62c8419f67a5e1a16b1698a325bcd190aa84810d516e263931`.

Serve both reader files from the same version. `worker.js` explicitly locates
the WASM at `/vendor/zxing_reader.wasm`; the upstream CDN default is unused.
