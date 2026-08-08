let recorder = null;
let mediaStream = null;
let audioContext = null;
let captureStartedAt = 0;
let active = null;
let uploadQueue = Promise.resolve();
let segmentTimer = null;
let stopRequested = false;
const SEGMENT_MS = 20000;

async function startCapture(message) {
  if (recorder?.state === "recording") return;
  active = message;
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: message.streamId
      }
    },
    video: false
  });

  // tabCapture removes the captured audio from normal playback; route it back.
  audioContext = new AudioContext();
  audioContext.createMediaStreamSource(mediaStream).connect(audioContext.destination);
  captureStartedAt = performance.now();
  stopRequested = false;
  startSegment();
  notify({type: "CAPTURE_STATUS", status: "recording"});
}

function startSegment() {
  if (stopRequested || !mediaStream?.active) return;
  const parts = [];
  const segmentStart = (performance.now() - captureStartedAt) / 1000;
  recorder = new MediaRecorder(mediaStream, {mimeType: "audio/webm;codecs=opus"});
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) parts.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    clearTimeout(segmentTimer);
    const blob = new Blob(parts, {type: "audio/webm;codecs=opus"});
    if (blob.size) uploadQueue = uploadQueue.then(() => uploadChunk(blob, segmentStart));
    if (stopRequested) cleanup();
    else startSegment();
  }, {once: true});
  recorder.start();
  segmentTimer = setTimeout(() => {
    if (recorder?.state === "recording") recorder.stop();
  }, SEGMENT_MS);
}

async function uploadChunk(blob, start) {
  notify({type: "CAPTURE_STATUS", status: "transcribing"});
  try {
    const response = await fetch("http://127.0.0.1:4317/transcribe", {
      method: "POST",
      headers: {
        "Content-Type": blob.type || "audio/webm",
        "X-Course-Url": active.courseUrl,
        "X-Course-Title": encodeURIComponent(active.courseTitle),
        "X-Chunk-Start": String(start)
      },
      body: blob
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "转写失败");
    notify({type: "TRANSCRIPT_CHUNK", record: data.record});
    if (recorder?.state === "recording") notify({type: "CAPTURE_STATUS", status: "recording"});
  } catch (error) {
    notify({type: "CAPTURE_STATUS", status: "error", error: error.message});
  }
}

function stopCapture() {
  stopRequested = true;
  clearTimeout(segmentTimer);
  if (recorder?.state === "recording") {
    recorder.stop();
  } else {
    cleanup();
  }
}

function cleanup() {
  mediaStream?.getTracks().forEach((track) => track.stop());
  audioContext?.close();
  recorder = null;
  mediaStream = null;
  audioContext = null;
  segmentTimer = null;
  notify({type: "CAPTURE_STATUS", status: "stopped"});
}

function notify(message) {
  chrome.runtime.sendMessage({target: "content", tabId: active?.tabId, ...message});
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.target !== "offscreen") return;
  if (message.type === "START_CAPTURE") startCapture(message).catch((error) => {
    active = message;
    notify({type: "CAPTURE_STATUS", status: "error", error: error.message});
  });
  if (message.type === "STOP_CAPTURE") stopCapture();
});
