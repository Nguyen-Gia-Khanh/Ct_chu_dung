/* Phone-side pixel preparation, also exercised by the Node smoke test. */
function preparePixels(data, width, height, sharpen) {
  const gray = new Uint8ClampedArray(width * height);
  for (let i = 0, p = 0; i < gray.length; i++, p += 4) {
    gray[i] = (77 * data[p] + 150 * data[p + 1] + 29 * data[p + 2]) >> 8;
  }
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      let value = gray[i];
      if (sharpen && x > 0 && y > 0 && x < width - 1 && y < height - 1) {
        // Gentle convolution: [0,-.25,0; -.25,2,-.25; 0,-.25,0].
        value = 2 * value - .25 * (gray[i - 1] + gray[i + 1] + gray[i - width] + gray[i + width]);
      }
      const p = i * 4;
      data[p] = data[p + 1] = data[p + 2] = value;
      data[p + 3] = 255;
    }
  }
  return { data, width, height };
}

if (typeof module !== "undefined") module.exports = { preparePixels };
