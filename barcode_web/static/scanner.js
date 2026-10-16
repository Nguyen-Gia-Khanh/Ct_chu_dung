"use strict";
const video = document.querySelector("#video");
const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const status = document.querySelector("#status");
const delivery = document.querySelector("#delivery");
const retry = document.querySelector("#retry");
const filter = document.querySelector("#filter");
const lookupPanel = document.querySelector("#lookup");
const product = document.querySelector("#product");
const locations = document.querySelector("#locations");
const cellData = document.querySelector("#cell-data");
const cells = document.querySelector("#cells");
const aim = document.querySelector(".aim");
const camera = document.querySelector(".camera");
const mask = document.querySelector("#mask");
const canvas = document.createElement("canvas");
const context = canvas.getContext("2d");
const fragment = location.hash.slice(1);
if (fragment) {
  sessionStorage.setItem("scanner-token", fragment);
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("scanner-token");
let stream, frameRequest, frameHandle, active = false, starting = false, busy = false;
let previous = 0, processed = 0, elapsed = 0, sampleAt = 0, generation = 0;
let lastText = null, lastSeen = 0, pending = null, sending = false;

function message(text, error = false) {
  status.textContent = text;
  status.className = error ? "error" : "";
  status.hidden = !error;
}

function clearMask() {
  mask.hidden = true;
  mask.removeAttribute("src");
}

function stop() {
  active = false;
  generation++;
  frameRequest?.abort();
  if (video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(frameHandle);
  else cancelAnimationFrame(frameHandle);
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
  video.srcObject = null;
  busy = false;
  startButton.disabled = false;
  stopButton.disabled = true;
  aim.hidden = true;
  clearMask();
}

async function sendPending() {
  if (!pending || sending) return;
  sending = true;
  retry.hidden = true;
  delivery.className = "";
  delivery.hidden = true;
  delivery.textContent = "Sending to laptop…";
  try {
    const response = await fetch("/api/scans", {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ ...pending, include_cell_contents: cellData.checked }), signal: AbortSignal.timeout(5000),
    });
    const answer = await response.json();
    if (!response.ok || !answer.ok) throw new Error(answer.error || "Laptop rejected the scan.");
    showLookup(answer.lookup);
    pending = null;
    sessionStorage.removeItem("pending-scan");
    delivery.textContent = "Received by laptop.";
    delivery.className = "success";
    navigator.vibrate?.(70);
  } catch (error) {
    delivery.textContent = `Not received: ${error.message} The barcode is kept on this phone; retry before scanning another.`;
    delivery.className = "error";
    delivery.hidden = false;
    retry.hidden = false;
  } finally {
    sending = false;
  }
}

function showLookup(found) {
  cells.replaceChildren();
  cells.hidden = true;
  lookupPanel.hidden = false;
  product.textContent = found?.product_id ? `${found.product_id} · ${found.product_name}` : "";
  locations.className = "";
  if (found?.status === "found") {
    locations.textContent = found.locations.join("\n");
    locations.className = "success";
    if (cellData.checked && found.cells?.length) {
      for (const cell of found.cells) {
        const table = document.createElement("table");
        const caption = table.createCaption();
        caption.textContent = cell.location;
        const header = table.createTHead().insertRow();
        for (const label of ["Barcode", "Product", "Stock"]) {
          const th = document.createElement("th");
          th.scope = "col";
          th.textContent = label;
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
    locations.textContent = found?.status === "unassigned" ? "Product found; no saved location." :
      found?.status === "not_found" ? "Barcode not found in the warehouse." :
      found?.status === "ambiguous" ? `Barcode matches multiple IDs: ${found.matches.join(", ")}.` :
      "Warehouse lookup is not configured on the laptop.";
  }
}

function receiveFrame(answer) {
  mask.hidden = !filter.checked || !answer.mask;
  if (!mask.hidden) mask.src = answer.mask;
  processed++;
  elapsed += answer.milliseconds;
  const now = performance.now();
  if (now - sampleAt >= 1000) {
    document.querySelector("#rate").textContent =
      `${(processed * 1000 / (now - sampleAt)).toFixed(1)} processed frames/s · ${(elapsed / processed).toFixed(0)} ms on laptop · ${answer.stage}`;
    processed = 0;
    elapsed = 0;
    sampleAt = now;
  }
  const found = answer.results[0];
  if (!found) return;
  const repeated = found.text === lastText && now - lastSeen < 1200;
  lastText = found.text;
  lastSeen = now;
  if (repeated || pending) return;
  document.querySelector("#result").textContent = found.text;
  lookupPanel.hidden = false;
  product.textContent = "";
  locations.textContent = "Looking up location…";
  locations.className = "";
  cells.replaceChildren();
  cells.hidden = true;
  pending = { id: crypto.randomUUID(), text: found.text, format: found.format };
  sessionStorage.setItem("pending-scan", JSON.stringify(pending));
  void sendPending();
}

async function sendFrame(current) {
  const request = new AbortController();
  frameRequest = request;
  let timer;
  try {
    const jpeg = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", .92));
    if (!active || generation !== current) return;
    if (!jpeg) throw new Error("Camera frame could not be captured.");
    timer = setTimeout(() => request.abort(), 5000);
    const response = await fetch("/api/frames", {
      method: "POST", headers: { "Content-Type": "image/jpeg", Authorization: `Bearer ${token}`,
        "X-Enhance": filter.checked ? "1" : "0" }, body: jpeg, signal: request.signal,
    });
    if (!active || generation !== current) return;
    const answer = await response.json();
    if (!active || generation !== current) return;
    if (response.status === 429) return;
    if (!response.ok || !answer.ok) throw new Error(answer.error || "Laptop could not process the frame.");
    message("Scanning barcode strip.");
    receiveFrame(answer);
  } catch (error) {
    if (active && generation === current) {
      clearMask();
      message(`Frame not processed: ${error.name === "AbortError" ? "Laptop timed out." : error.message} Retrying…`, true);
      previous = performance.now() + 1000;
    }
  } finally {
    clearTimeout(timer);
    if (generation === current) {
      busy = false;
      frameRequest = null;
    }
  }
}

function nextFrame(callback) {
  if (video.requestVideoFrameCallback) frameHandle = video.requestVideoFrameCallback(callback);
  else frameHandle = requestAnimationFrame(callback);
}

function frame(now) {
  if (!active) return;
  if (!busy && !pending && now >= previous - 2 && video.readyState >= 2) {
    // Carry the deadline forward so video-frame jitter cannot accumulate drift.
    previous = Math.max(previous + 1000 / 15, now + 1);
    // Match object-fit: cover exactly. Nothing outside the horizontal strip is uploaded.
    const width = video.videoWidth, height = video.videoHeight;
    const ratio = video.clientWidth / video.clientHeight;
    const cropWidth = Math.min(width, height * ratio);
    const cropHeight = cropWidth / ratio;
    const scale = Math.min(1, 1280 / cropWidth);
    const targetWidth = Math.max(16, Math.round(cropWidth * scale));
    const targetHeight = Math.max(16, Math.round(cropHeight * scale));
    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
    }
    context.drawImage(video, (width - cropWidth) / 2, (height - cropHeight) / 2,
      cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);
    busy = true;
    void sendFrame(generation);
  }
  nextFrame(frame);
}

async function start() {
  if (starting || active) return;
  if (!token) return message("Open the current phone link from the laptop receiver.", true);
  if (!isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    return message("Camera needs trusted HTTPS. Install the certificate using the laptop's setup link, then reopen the HTTPS phone link.", true);
  }
  starting = true;
  const current = generation;
  startButton.disabled = true;
  message("Connecting to laptop and starting camera…");
  try {
    // Verify the session before asking permission; old links must not silently lose scans.
    const check = await fetch("/api/scans", { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5000) });
    if (!check.ok) throw new Error("Phone link expired. Open the new link from the laptop receiver.");
    if (generation !== current) return;
    stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
      facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 },
      frameRate: { ideal: 30, min: 15 },
    } });
    if (generation !== current) { stop(); return; }
    video.srcObject = stream;
    await video.play();
    const track = stream.getVideoTracks()[0];
    // Best effort: cameras/browsers differ in whether they expose continuous focus.
    try {
      if (track.getCapabilities?.().focusMode?.includes("continuous")) {
        await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] });
      }
    } catch (_) { /* Device's default autofocus remains available. */ }
    if (generation !== current) { stop(); return; }
    active = true;
    lastText = null;
    previous = processed = elapsed = 0;
    sampleAt = performance.now();
    stopButton.disabled = false;
    aim.hidden = false;
    message("Scanning barcode strip.");
    nextFrame(frame);
    if (pending) void sendPending();
  } catch (error) {
    stop();
    message(error.name === "NotAllowedError" ? "Allow camera access in this browser, then try again." : error.message, true);
  } finally {
    starting = false;
  }
}

startButton.addEventListener("click", start);
stopButton.addEventListener("click", () => { stop(); message("Camera stopped."); });
retry.addEventListener("click", sendPending);
filter.addEventListener("change", () => {
  camera.classList.toggle("mask-mode", filter.checked);
  clearMask();
});
camera.classList.toggle("mask-mode", filter.checked);
cellData.addEventListener("change", () => {
  cells.replaceChildren();
  cells.hidden = true;
});
addEventListener("pagehide", stop);
document.addEventListener("visibilitychange", () => {
  if (document.hidden && active) { stop(); message("Camera paused while this tab was hidden. Press Start camera to resume."); }
});
if (token) message("Ready. Press Start camera.");
try {
  pending = JSON.parse(sessionStorage.getItem("pending-scan"));
  if (pending) {
    document.querySelector("#result").textContent = pending.text;
    delivery.textContent = "A barcode is waiting to be sent. Press Retry sending.";
    delivery.hidden = false;
    retry.hidden = false;
  }
} catch (_) { sessionStorage.removeItem("pending-scan"); }
