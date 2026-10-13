"use strict";
const video = document.querySelector("#video");
const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const status = document.querySelector("#status");
const delivery = document.querySelector("#delivery");
const retry = document.querySelector("#retry");
const filter = document.querySelector("#filter");
const aim = document.querySelector(".aim");
const canvas = document.createElement("canvas");
const context = canvas.getContext("2d", { willReadFrequently: true });
const fragment = location.hash.slice(1);
if (fragment) {
  sessionStorage.setItem("scanner-token", fragment);
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("scanner-token");
let stream, worker, frameHandle, active = false, starting = false, busy = false;
let previous = 0, frames = 0, processed = 0, elapsed = 0, sampleAt = 0;
let lastText = null, lastSeen = 0, pending = null, sending = false;

function message(text, error = false) {
  status.textContent = text;
  status.className = error ? "error" : "";
}

function stop() {
  active = false;
  if (video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(frameHandle);
  else cancelAnimationFrame(frameHandle);
  worker?.terminate();
  worker = null;
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
  video.srcObject = null;
  busy = false;
  startButton.disabled = false;
  stopButton.disabled = true;
  aim.hidden = true;
}

async function sendPending() {
  if (!pending || sending) return;
  sending = true;
  retry.hidden = true;
  delivery.className = "";
  delivery.textContent = "Sending to laptop…";
  try {
    const response = await fetch("/api/scans", {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(pending), signal: AbortSignal.timeout(5000),
    });
    const answer = await response.json();
    if (!response.ok || !answer.ok) throw new Error(answer.error || "Laptop rejected the scan.");
    pending = null;
    sessionStorage.removeItem("pending-scan");
    delivery.textContent = "Received by laptop.";
    delivery.className = "success";
    navigator.vibrate?.(70);
  } catch (error) {
    delivery.textContent = `Not received: ${error.message} The barcode is kept on this phone; retry before scanning another.`;
    delivery.className = "error";
    retry.hidden = false;
  } finally {
    sending = false;
  }
}

function receiveFrame(event) {
  if (!active || event.data.type === "ready") return;
  busy = false;
  if (event.data.type === "error") {
    stop();
    message(`Decoder failed: ${event.data.message}`, true);
    return;
  }
  processed++;
  elapsed += event.data.milliseconds;
  const now = performance.now();
  if (now - sampleAt >= 1000) {
    document.querySelector("#rate").textContent =
      `${(processed * 1000 / (now - sampleAt)).toFixed(1)} scans/s · ${(elapsed / processed).toFixed(0)} ms processing · target 15`;
    processed = 0;
    elapsed = 0;
    sampleAt = now;
  }
  const found = event.data.results[0];
  if (!found) return;
  const repeated = found.text === lastText && now - lastSeen < 1200;
  lastText = found.text;
  lastSeen = now;
  if (repeated || pending) return;
  document.querySelector("#result").textContent = found.text;
  pending = { id: crypto.randomUUID(), text: found.text, format: found.format };
  sessionStorage.setItem("pending-scan", JSON.stringify(pending));
  void sendPending();
}

function nextFrame(callback) {
  if (video.requestVideoFrameCallback) frameHandle = video.requestVideoFrameCallback(callback);
  else frameHandle = requestAnimationFrame(callback);
}

function frame(now) {
  if (!active) return;
  if (!busy && now >= previous - 2 && video.readyState >= 2) {
    // Carry the deadline forward so video-frame jitter cannot accumulate drift.
    previous = Math.max(previous + 1000 / 15, now + 1);
    // Crop exactly the aiming box and scale uniformly; never stretch barcode bars.
    const width = video.videoWidth * .9, height = video.videoHeight * .6;
    const scale = Math.min(1, 960 / width, 480 / height);
    const targetWidth = Math.max(1, Math.round(width * scale));
    const targetHeight = Math.max(1, Math.round(height * scale));
    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
    }
    context.drawImage(video, video.videoWidth * .05, video.videoHeight * .2,
                      width, height, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    busy = true;
    worker.postMessage({ buffer: pixels.data.buffer, width: canvas.width, height: canvas.height,
                         sharpen: filter.checked && (++frames % 2 === 0) }, [pixels.data.buffer]);
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
  startButton.disabled = true;
  message("Starting camera and decoder…");
  try {
    // Verify the session before asking permission; old links must not silently lose scans.
    const check = await fetch("/api/scans", { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5000) });
    if (!check.ok) throw new Error("Phone link expired. Open the new link from the laptop receiver.");
    worker = new Worker("/worker.js");
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Decoder did not load. Reload the page.")), 15000);
      worker.onerror = event => { clearTimeout(timer); reject(new Error(event.message || "Decoder failed to load.")); };
      worker.onmessage = event => {
        clearTimeout(timer);
        if (event.data.type === "ready") resolve();
        else reject(new Error(event.data.message));
      };
    });
    stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
      facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 },
      frameRate: { ideal: 30, min: 15 },
    } });
    video.srcObject = stream;
    await video.play();
    const track = stream.getVideoTracks()[0];
    // Best effort: cameras/browsers differ in whether they expose continuous focus.
    try {
      if (track.getCapabilities?.().focusMode?.includes("continuous")) {
        await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] });
      }
    } catch (_) { /* Device's default autofocus remains available. */ }
    video.style.maxHeight = "none";
    document.querySelector(".camera").style.maxWidth = `${Math.min(760, innerHeight * .62 * video.videoWidth / video.videoHeight)}px`;
    worker.onmessage = receiveFrame;
    worker.onerror = () => { stop(); message("Decoder stopped. Start the camera again.", true); };
    active = true;
    lastText = null;
    previous = frames = processed = elapsed = 0;
    sampleAt = performance.now();
    stopButton.disabled = false;
    aim.hidden = false;
    message("Scanning. Keep the whole barcode inside the box.");
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
    retry.hidden = false;
  }
} catch (_) { sessionStorage.removeItem("pending-scan"); }
