"use strict";
const $ = selector => document.querySelector(selector);
const video = $("#video");
const startButton = $("#start");
const stopButton = $("#stop");
const status = $("#status");
const delivery = $("#delivery");
const retry = $("#retry");
const filter = $("#filter");
const lookupPanel = $("#lookup");
const product = $("#product");
const locations = $("#locations");
const cellData = $("#cell-data");
const cells = $("#cells");
const scanWindow = $("#window");
const mask = $("#mask");
const barcodeBox = $("#barcode-box");
const result = $("#result");
const badge = $("#badge");
const empty = $("#empty");
const hint = $("#hint");
const linkState = $("#link-state");
const torchButton = $("#torch");
const soundButton = $("#sound");
const zoomControl = $("#zoom-control");
const zoom = $("#zoom");
const search = $("#search");
const manual = $("#manual");
// Phone frames are decoded on this phone; the laptop canvas is only for fallback/mask uploads.
const phoneCanvas = document.createElement("canvas");
const phoneContext = phoneCanvas.getContext("2d", { willReadFrequently: true });
const laptopCanvas = document.createElement("canvas");
const laptopContext = laptopCanvas.getContext("2d");
const MAX_PHONE_WIDTH = 1920, MAX_UPLOAD_WIDTH = 1280;
// Decoding every camera frame heats the phone; ~8 reads/s is still instant. The preview keeps camera fps.
const DECODE_INTERVAL = 1000 / 8;

function stored(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function store(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* Private mode: the setting lasts this visit. */ }
}

const fragment = location.hash.slice(1);
// Restored phone tabs can lose sessionStorage after the browser is suspended.
const token = fragment || stored("scanner-token") || sessionStorage.getItem("scanner-token");
if (token) store("scanner-token", token);
sessionStorage.removeItem("scanner-token");
if (fragment) history.replaceState(null, "", location.pathname);
addEventListener("hashchange", () => {
  if (location.hash.slice(1)) location.reload();
});

let stream, track, frameHandle, active = false, starting = false, generation = 0;
let lastText = null, lastSeen = 0, pending = null, sending = false;
let processed = 0, elapsed = 0, sampleAt = 0;
let lastPresent = 0, lastRead = 0, scanningSince = 0;
let audio = null, sound = stored("scanner-sound") !== "off";

// ---------- Phone-side decoder ----------
const decoder = { worker: null, ready: false, busy: false, failed: false, errors: 0, id: 0, native: false, since: 0, next: 0 };
const laptop = { request: null, busy: false, previous: 0 };
let resolving = false;
const askedPatterns = new Map();

function startDecoder() {
  decoder.since = performance.now();
  try {
    decoder.worker = new Worker("/decoder-worker.js");
  } catch (_) {
    decoder.failed = true;
    return;
  }
  decoder.worker.onmessage = ({ data }) => {
    if (data.type === "ready") { decoder.ready = true; decoder.native = data.native; showMode(); return; }
    if (data.id !== undefined && data.id !== decoder.id) return;
    decoder.busy = false;
    if (data.type === "error") {
      // A broken WASM/worker on this phone: decode on the laptop instead, as before.
      if (data.id === undefined || ++decoder.errors >= 5) { decoder.failed = true; showMode(); }
      return;
    }
    decoder.errors = 0;
    if (!active) return;
    receive(data, "phone");
    if (data.partial) void resolvePartial(data.partial);
  };
  decoder.worker.onerror = () => { decoder.failed = true; decoder.busy = false; showMode(); };
}

function phoneDecoding() {
  return decoder.ready && !decoder.failed;
}

/** The worker failed, or is still not ready after 4 s: decode on the laptop meanwhile. */
function laptopDecoding(now) {
  return decoder.failed || (!decoder.ready && now - decoder.since > 4000);
}

function showMode() {
  if (!active) return;
  if (phoneDecoding()) setLink("phone", "Đang quét trên điện thoại");
  else if (laptopDecoding(performance.now())) setLink("laptop", "Đang quét trên máy tính");
  else setLink("off", "Đang chuẩn bị bộ giải mã…");
}

function setLink(state, text) {
  linkState.dataset.state = state;
  linkState.textContent = text;
}

function message(text, error = false) {
  status.textContent = text;
  status.className = error ? "error" : "";
  status.hidden = !error;
}

function clearOverlay() {
  mask.hidden = true;
  mask.removeAttribute("src");
  barcodeBox.hidden = true;
}

/** The scan window's pixels in video coordinates, matching object-fit: cover exactly. */
function windowCrop() {
  const width = video.videoWidth, height = video.videoHeight;
  const view = video.getBoundingClientRect(), frame = scanWindow.getBoundingClientRect();
  if (!width || !height || !view.width || !view.height) return null;
  const scale = Math.max(view.width / width, view.height / height);
  const offsetX = (view.width - width * scale) / 2, offsetY = (view.height - height * scale) / 2;
  const x = Math.max(0, (frame.left - view.left - offsetX) / scale);
  const y = Math.max(0, (frame.top - view.top - offsetY) / scale);
  return { x, y, width: Math.min(width - x, frame.width / scale), height: Math.min(height - y, frame.height / scale) };
}

function draw(canvas, context, crop, maxWidth) {
  const scale = Math.min(1, maxWidth / crop.width);
  const targetWidth = Math.max(16, Math.round(crop.width * scale));
  const targetHeight = Math.max(16, Math.round(crop.height * scale));
  if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
    canvas.width = targetWidth;
    canvas.height = targetHeight;
  }
  context.drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, targetWidth, targetHeight);
}

function sendToPhoneDecoder(crop, now) {
  draw(phoneCanvas, phoneContext, crop, MAX_PHONE_WIDTH);
  const image = phoneContext.getImageData(0, 0, phoneCanvas.width, phoneCanvas.height);
  decoder.busy = true;
  decoder.id++;
  decoder.worker.postMessage({ type: "frame", id: decoder.id, buffer: image.data.buffer,
                               width: image.width, height: image.height, time: now }, [image.data.buffer]);
}

/** Laptop uploads: the whole decode if the phone cannot, the mask preview, or a second opinion
 *  when the phone sees a barcode but has not read it for a while. */
function laptopDue(now) {
  if (laptop.busy || now < laptop.previous) return false;
  if (laptopDecoding(now) || filter.checked) return true;
  if (!phoneDecoding()) return false;
  return now - lastPresent < 300 && now - Math.max(lastRead, scanningSince) > 1200 && now - laptop.previous > 350;
}

async function sendToLaptop(crop, current) {
  draw(laptopCanvas, laptopContext, crop, MAX_UPLOAD_WIDTH);
  laptop.busy = true;
  const request = new AbortController();
  laptop.request = request;
  let timer;
  try {
    const jpeg = await new Promise(resolve => laptopCanvas.toBlob(resolve, "image/jpeg", .92));
    if (!active || generation !== current) return;
    if (!jpeg) throw new Error("Không chụp được khung hình camera.");
    timer = setTimeout(() => request.abort(), 5000);
    const response = await fetch("/api/frames", {
      method: "POST", headers: { "Content-Type": "image/jpeg", Authorization: `Bearer ${token}`,
        "X-Enhance": "1", "X-Mask": filter.checked ? "1" : "0" }, body: jpeg, signal: request.signal,
    });
    if (!active || generation !== current) return;
    const answer = await response.json();
    if (!active || generation !== current || response.status === 429) return;
    if (!response.ok || !answer.ok) throw new Error(answer.error || "Máy tính không xử lý được khung hình.");
    if (status.hidden === false && status.textContent.startsWith("Chưa xử lý được ảnh")) message("");
    showMode();
    receive(answer, "laptop");
  } catch (error) {
    if (active && generation === current) {
      if (!phoneDecoding()) {
        clearOverlay();
        setLink("offline", "Máy tính mất kết nối");
        message(`Chưa xử lý được ảnh: ${error.name === "AbortError" ? "Máy tính phản hồi quá lâu." : error.message} Đang thử lại…`, true);
      }
      laptop.previous = performance.now() + 1000;
    }
  } finally {
    clearTimeout(timer);
    if (generation === current) {
      laptop.busy = false;
      laptop.request = null;
    }
  }
}

function receive(answer, source) {
  const now = performance.now();
  if (source === "laptop" || !filter.checked) {
    if (source === "laptop") {
      mask.hidden = !filter.checked || !answer.mask;
      if (!mask.hidden) mask.src = answer.mask;
    }
    barcodeBox.hidden = !answer.box;
    if (answer.box) {
      const [x, y, width, height] = answer.box;
      Object.assign(barcodeBox.style, {
        left: `${x * 100}%`, top: `${y * 100}%`, width: `${width * 100}%`, height: `${height * 100}%`,
      });
    }
  }
  if (answer.present || answer.results?.length) lastPresent = now;
  if (source === (phoneDecoding() ? "phone" : "laptop")) {
    processed++;
    elapsed += answer.milliseconds;
    if (now - sampleAt >= 1000) {
      $("#rate").textContent = `${(processed * 1000 / (now - sampleAt)).toFixed(1)} khung hình/giây · `
        + `${(elapsed / processed).toFixed(0)} ms trên ${source === "phone" ? "điện thoại" : "máy tính"}${decoder.native ? " (bộ đọc tích hợp)" : ""} · ${answer.stage}`;
      processed = 0;
      elapsed = 0;
      sampleAt = now;
    }
    // Struggling: tell the person what usually helps, without blocking anything.
    hint.hidden = !(now - lastPresent < 400 && now - Math.max(lastRead, scanningSince) > 2500);
    hint.textContent = "Giữ máy ổn định. Đưa lại gần hoặc phóng to để mã vạch vừa khung.";
  }
  const found = answer.results?.[0];
  if (found) accept(found);
}

async function resolvePartial(pattern) {
  const now = performance.now();
  if (resolving || pending || now - (askedPatterns.get(pattern) || -1e9) < 3000) return;
  askedPatterns.set(pattern, now);
  resolving = true;
  try {
    const response = await fetch("/api/resolve", {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ pattern }), signal: AbortSignal.timeout(3000),
    });
    const answer = await response.json();
    // Only a single catalog ID that fits every read character completes the code.
    if (active && response.ok && answer.status === "unique") {
      accept({ text: answer.product_id, format: "Code 39 · catalog", source: "catalog" });
    }
  } catch (_) {
    /* Keep scanning; completion is only a shortcut. */
  } finally {
    resolving = false;
  }
}

function accept(found) {
  const now = performance.now();
  const repeated = found.text === lastText && now - lastSeen < 1200;
  lastText = found.text;
  lastSeen = now;
  lastRead = now;
  if (repeated || pending) return;
  decoder.worker?.postMessage({ type: "reset" });
  feedback();
  lookUp(found);
}

function lookUp(found) {
  result.textContent = found.text;
  empty.hidden = true;
  showBadge(found.source === "catalog" ? "Bổ sung từ danh mục" : "Đang tìm…",
            found.source === "catalog" ? "catalog" : "");
  lookupPanel.hidden = false;
  product.textContent = "";
  locations.replaceChildren("Đang tìm vị trí…");
  locations.className = "message";
  cells.replaceChildren();
  cells.hidden = true;
  pending = { id: crypto.randomUUID(), text: found.text, format: found.format };
  sessionStorage.setItem("pending-scan", JSON.stringify(pending));
  void sendPending();
}

function feedback() {
  scanWindow.classList.remove("read");
  void scanWindow.offsetWidth;
  scanWindow.classList.add("read");
  navigator.vibrate?.(60);
  if (!sound || !audio) return;
  try {
    const tone = audio.createOscillator(), level = audio.createGain();
    tone.frequency.value = 1760;
    level.gain.setValueAtTime(.18, audio.currentTime);
    level.gain.exponentialRampToValueAtTime(.001, audio.currentTime + .09);
    tone.connect(level).connect(audio.destination);
    tone.start();
    tone.stop(audio.currentTime + .1);
  } catch (_) { /* Sound is optional. */ }
}

function showBadge(text, tone) {
  badge.hidden = !text;
  badge.textContent = text;
  badge.dataset.tone = tone;
}

async function sendPending() {
  if (!pending || sending) return;
  sending = true;
  retry.hidden = true;
  delivery.className = "";
  delivery.hidden = true;
  delivery.textContent = "Đang gửi đến máy tính…";
  try {
    const response = await fetch("/api/scans", {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ ...pending, include_cell_contents: cellData.checked }), signal: AbortSignal.timeout(5000),
    });
    const answer = await response.json();
    if (!response.ok || !answer.ok) throw new Error(answer.error || "Máy tính từ chối mã vừa quét.");
    const completed = pending.format.endsWith("catalog");
    showLookup(answer.lookup, completed);
    pending = null;
    sessionStorage.removeItem("pending-scan");
    delivery.textContent = "Máy tính đã nhận.";
    delivery.className = "success";
    if (active) showMode();
  } catch (error) {
    delivery.textContent = `Chưa gửi được: ${error.message} Mã vạch được giữ trên điện thoại; hãy gửi lại trước khi quét mã khác.`;
    delivery.className = "error";
    delivery.hidden = false;
    retry.hidden = false;
    setLink("offline", "Máy tính mất kết nối");
  } finally {
    sending = false;
  }
}

function showLookup(found, completed = false) {
  cells.replaceChildren();
  cells.hidden = true;
  lookupPanel.hidden = false;
  empty.hidden = true;
  product.textContent = found?.product_id ? `${found.product_id} · ${found.product_name}` : "";
  const label = {
    found: ["Đã tìm thấy", "found"], unassigned: ["Chưa có vị trí", "warn"], not_found: ["Không có trong danh mục", "stop"],
    ambiguous: ["Nhiều mã phù hợp", "warn"],
  }[found?.status] || ["Chưa bật tra cứu", ""];
  showBadge(completed ? `${label[0]} · bổ sung từ danh mục` : label[0], completed && found?.status === "found" ? "catalog" : label[1]);
  if (found?.status === "found") {
    locations.className = "";
    locations.replaceChildren(...found.locations.map(name => {
      const tag = document.createElement("span");
      tag.className = "loc stamp";
      tag.textContent = name;
      return tag;
    }));
    if (cellData.checked && found.cells?.length) {
      for (const cell of found.cells) {
        const table = document.createElement("table");
        table.createCaption().textContent = cell.location;
        const header = table.createTHead().insertRow();
        for (const text of ["Mã vạch", "Sản phẩm", "Tồn kho"]) {
          const th = document.createElement("th");
          th.scope = "col";
          th.textContent = text;
          header.append(th);
        }
        const body = table.createTBody();
        for (const item of cell.products) {
          const row = body.insertRow();
          for (const value of [item.product_id, item.product_name, item.stock_qty ?? "—"]) {
            row.insertCell().textContent = value;
          }
        }
        cells.append(table);
      }
      cells.hidden = false;
    }
  } else {
    locations.className = "message";
    locations.textContent = found?.status === "unassigned" ? "Đã tìm thấy sản phẩm nhưng chưa có vị trí lưu." :
      found?.status === "not_found" ? "Không tìm thấy mã vạch trong kho." :
      found?.status === "ambiguous" ? `Mã vạch khớp với nhiều mã sản phẩm: ${found.matches.join(", ")}.` :
      "Máy tính chưa được cấu hình tra cứu kho.";
  }
}

function nextFrame(callback) {
  if (video.requestVideoFrameCallback) frameHandle = video.requestVideoFrameCallback(callback);
  else frameHandle = requestAnimationFrame(callback);
}

function frame(now) {
  if (!active) return;
  if (!pending && video.readyState >= 2) {
    const phoneDue = phoneDecoding() && !decoder.busy && now >= decoder.next;
    const laptopNow = laptopDue(now);
    const crop = phoneDue || laptopNow ? windowCrop() : null;
    if (crop && crop.width >= 16 && crop.height >= 16) {
      // No network, no JPEG, full resolution; at most DECODE_INTERVAL apart.
      if (phoneDue) {
        decoder.next = Math.max(decoder.next + DECODE_INTERVAL, now);
        sendToPhoneDecoder(crop, performance.now());
      }
      if (laptopNow) {
        laptop.previous = Math.max(laptop.previous + DECODE_INTERVAL, now + 1);
        void sendToLaptop(crop, generation);
      }
    }
  }
  nextFrame(frame);
}

function stop() {
  active = false;
  generation++;
  laptop.request?.abort();
  laptop.busy = false;
  decoder.busy = false;
  if (video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(frameHandle);
  else cancelAnimationFrame(frameHandle);
  stream?.getTracks().forEach(t => t.stop());
  stream = track = null;
  video.srcObject = null;
  startButton.hidden = false;
  startButton.disabled = false;
  stopButton.hidden = true;
  torchButton.hidden = true;
  torchButton.setAttribute("aria-pressed", "false");
  zoomControl.hidden = true;
  hint.hidden = false;
  hint.textContent = "Bấm Mở camera, rồi đưa toàn bộ mã vạch vào khung.";
  setLink("off", "Camera đã tắt");
  clearOverlay();
}

async function cameraControls() {
  const capabilities = track.getCapabilities?.() || {};
  const advanced = {};
  // Best effort: cameras/browsers differ in which controls they expose.
  if (capabilities.focusMode?.includes("continuous")) advanced.focusMode = "continuous";
  if (capabilities.zoom) {
    const { min, max, step } = capabilities.zoom;
    Object.assign(zoom, { min, max, step: step || .1 });
    const saved = Number(stored("scanner-zoom"));
    zoom.value = saved >= min && saved <= max ? saved : min;
    advanced.zoom = Number(zoom.value);
    zoomControl.hidden = max <= min;
  }
  torchButton.hidden = !capabilities.torch;
  if (Object.keys(advanced).length) {
    try { await track.applyConstraints({ advanced: [advanced] }); } catch (_) { /* Device defaults remain. */ }
  }
}

async function start() {
  if (starting || active) return;
  if (!token) return message("Mở liên kết quét hiện tại từ trang nhận trên máy tính.", true);
  if (!isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    return message("Camera cần kết nối HTTPS được tin cậy. Mở liên kết cài đặt từ máy tính trên điện thoại, cài chứng chỉ rồi mở lại liên kết quét.", true);
  }
  starting = true;
  const current = generation;
  startButton.disabled = true;
  setLink("off", "Đang mở…");
  try {
    audio ??= new (window.AudioContext || window.webkitAudioContext)();
    void audio.resume?.();
  } catch (_) { audio = null; }
  message("");
  try {
    // Verify the session before asking permission; old links must not silently lose scans.
    const check = await fetch("/api/scans", { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5000) });
    if (check.status === 403) throw new Error("Liên kết quét đã hết hạn. Mở liên kết mới từ trang nhận trên máy tính.");
    if (!check.ok) throw new Error("Không kết nối được máy tính. Kiểm tra máy chủ rồi bấm Mở camera lần nữa.");
    if (generation !== current) return;
    stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
      facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 },
      frameRate: { ideal: 30, min: 15 },
    } });
    if (generation !== current) { stop(); return; }
    video.srcObject = stream;
    await video.play();
    track = stream.getVideoTracks()[0];
    await cameraControls();
    if (generation !== current) { stop(); return; }
    active = true;
    lastText = null;
    processed = elapsed = 0;
    laptop.previous = decoder.next = 0;
    sampleAt = scanningSince = performance.now();
    startButton.hidden = true;
    stopButton.hidden = false;
    hint.hidden = true;
    showMode();
    decoder.worker?.postMessage({ type: "reset" });
    nextFrame(frame);
    if (pending) void sendPending();
  } catch (error) {
    stop();
    message(error.name === "NotAllowedError" ? "Cho phép trình duyệt dùng camera rồi thử lại." : error.message, true);
  } finally {
    starting = false;
  }
}

startButton.addEventListener("click", start);
stopButton.addEventListener("click", () => { stop(); message("Đã dừng camera."); });
retry.addEventListener("click", sendPending);
search.addEventListener("submit", event => {
  event.preventDefault();
  const text = manual.value.trim();
  if (!text) return manual.focus();
  if (pending) {
    delivery.hidden = false;
    return;
  }
  manual.value = "";
  manual.blur();
  lookUp({ text, format: "Typed" });
});
filter.addEventListener("change", clearOverlay);
cellData.addEventListener("change", () => {
  cells.replaceChildren();
  cells.hidden = true;
});
soundButton.setAttribute("aria-pressed", String(sound));
soundButton.addEventListener("click", () => {
  sound = !sound;
  soundButton.setAttribute("aria-pressed", String(sound));
  store("scanner-sound", sound ? "on" : "off");
});
torchButton.addEventListener("click", async () => {
  const on = torchButton.getAttribute("aria-pressed") !== "true";
  try {
    await track?.applyConstraints({ advanced: [{ torch: on }] });
    torchButton.setAttribute("aria-pressed", String(on));
  } catch (_) { torchButton.hidden = true; }
});
zoom.addEventListener("input", () => {
  store("scanner-zoom", zoom.value);
  track?.applyConstraints({ advanced: [{ zoom: Number(zoom.value) }] }).catch(() => {});
});
addEventListener("pagehide", stop);
document.addEventListener("visibilitychange", () => {
  if (document.hidden && active) { stop(); message("Camera đã tạm dừng khi chuyển sang thẻ khác. Bấm Mở camera để tiếp tục."); }
});
startDecoder();
try {
  pending = JSON.parse(sessionStorage.getItem("pending-scan"));
  if (pending) {
    result.textContent = pending.text;
    empty.hidden = true;
    delivery.textContent = "Có mã vạch đang chờ gửi. Bấm Gửi lại.";
    delivery.hidden = false;
    retry.hidden = false;
  }
} catch (_) { sessionStorage.removeItem("pending-scan"); }
