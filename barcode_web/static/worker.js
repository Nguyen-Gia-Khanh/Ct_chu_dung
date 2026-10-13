importScripts("/vendor/reader.js", "/processing.js");

const ready = ZXingWASM.prepareZXingModule({
  overrides: { locateFile: path => path.endsWith(".wasm") ? "/vendor/zxing_reader.wasm" : path },
  fireImmediately: true,
});
ready.then(() => postMessage({ type: "ready" }))
  .catch(error => postMessage({ type: "error", message: error.message }));

onmessage = async ({ data: frame }) => {
  const started = performance.now();
  try {
    await ready;
    const image = preparePixels(new Uint8ClampedArray(frame.buffer), frame.width, frame.height, frame.sharpen);
    const results = await ZXingWASM.readBarcodes(image, {
      formats: ["AllLinear", "QRCode", "DataMatrix"],
      tryHarder: false, tryRotate: true, tryInvert: true, tryDownscale: true,
      maxNumberOfSymbols: 1, returnErrors: false, textMode: "Plain",
    });
    postMessage({ type: "result", results: results.map(result => ({ text: result.text, format: result.format })),
                  milliseconds: performance.now() - started });
  } catch (error) {
    postMessage({ type: "error", message: error.message });
  }
};
