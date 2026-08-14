const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {choosePageMedia} = require("../extension/playback.js");

function media(tagName, src, visible = true) {
  return {
    tagName,
    currentSrc: src,
    src,
    getClientRects: () => visible ? [{}] : [],
  };
}

test("uses the existing page player already showing the same resource", () => {
  const audio = media("AUDIO", "https://media.example/one.mp3");
  const video = media("VIDEO", "https://media.example/two.mp4");
  assert.equal(choosePageMedia([audio, video], {
    url: "https://media.example/two.mp4", mediaType: "video",
  }), video);
});

test("prefers Flutter's last active player over an earlier preload instance", () => {
  const preload = media("AUDIO", "https://media.example/one.mp3");
  const active = media("AUDIO", "https://media.example/one.mp3");
  assert.equal(choosePageMedia([preload, active], {
    url: "https://media.example/one.mp3", mediaType: "audio",
  }, active), active);
});

test("falls back to the visible page player of the same media type", () => {
  const audio = media("AUDIO", "https://media.example/old.mp3");
  const video = media("VIDEO", "https://media.example/old.mp4");
  assert.equal(choosePageMedia([audio, video], {
    url: "https://media.example/new.mp3", mediaType: "audio",
  }), audio);
});

test("never invents a hidden second player", () => {
  assert.equal(choosePageMedia([], {
    url: "https://media.example/one.mp3", mediaType: "audio",
  }), null);
  const content = fs.readFileSync(path.join(__dirname, "../extension/content.js"), "utf8");
  assert.equal(content.includes("new Audio("), false);
});

test("uses one extension-owned course player instead of patching Flutter", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "../extension/manifest.json"), "utf8"));
  assert.equal(manifest.permissions.includes("declarativeNetRequest"), false);
  assert.equal(Boolean(manifest.declarative_net_request), false);
  const content = fs.readFileSync(path.join(__dirname, "../extension/content.js"), "utf8");
  assert.equal(content.includes('class="course-player"'), true);
  assert.equal(content.includes('<audio controls preload="metadata">'), true);
  assert.equal(content.includes('<video controls playsinline preload="metadata"'), true);
  assert.equal(content.includes("async function useCoursePlayer"), true);
  assert.equal(content.includes("await useCoursePlayer(source, localTime, true)"), true);
});

test("left player progress and transcript clicks share the same media element", () => {
  const content = fs.readFileSync(path.join(__dirname, "../extension/content.js"), "utf8");
  assert.equal(content.includes("activeCourseSource = source"), true);
  assert.equal(content.includes('clearTranscriptPlaybackState("正在定位对应媒体…")'), true);
  assert.equal(content.includes("highlightTranscriptAtMediaProgress"), true);
  assert.equal(content.includes('player.addEventListener("timeupdate"'), true);
  assert.equal(content.includes('player.addEventListener("seeking"'), true);
  assert.equal(content.includes('player.addEventListener("play"'), true);
  assert.equal(content.includes('player.addEventListener("pause"'), true);
  assert.equal(content.includes("await playingAudio.play()"), true);
  assert.equal(content.includes("playingAudio.pause()"), true);
  assert.equal(content.includes('scrollIntoView({block: "nearest"'), true);
});
