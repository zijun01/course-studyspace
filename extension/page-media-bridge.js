(function () {
  window.__courseStudyspacePageBridgeVersion = "0.7.7";

  // Flutter creates main.dart.js dynamically. Replace its URL before it is
  // attached, which also works when Songy's Service Worker owns the page.
  const extensionBase = document.currentScript?.src?.match(/^(chrome-extension:\/\/[^/]+\/)/)?.[1]
    || String(new Error().stack || "").match(/chrome-extension:\/\/[^/]+\//)?.[0];
  const bridgedBundle = extensionBase ? `${extensionBase}vendor/songy-main-bridged.js` : "";
  const redirectSongyBundle = (node) => {
    if (bridgedBundle && node?.tagName === "SCRIPT" && /\/main\.dart\.js(?:[?#]|$)/.test(node.src || "")) {
      node.src = bridgedBundle;
    }
    return node;
  };
  const nativeAppendChild = Node.prototype.appendChild;
  Node.prototype.appendChild = function (node) {
    return nativeAppendChild.call(this, redirectSongyBundle(node));
  };
  const nativeInsertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function (node, reference) {
    return nativeInsertBefore.call(this, redirectSongyBundle(node), reference);
  };
  const mediaInstances = new Set();
  let lastActive = null;
  let controlledMedia = null;
  function effectiveControlPoint() {
    // The assistant occupies the right 55vw; Songy's player is centered in the
    // remaining left 45vw and its transport row is 77px above the viewport end.
    return {x: window.innerWidth * 0.225, y: window.innerHeight - 77};
  }

  function track(media) {
    if (!media || mediaInstances.has(media)) return media;
    mediaInstances.add(media);
    let lastProgressSentAt = 0;
    const publishProgress = (force = false) => {
      const now = performance.now();
      if (!force && now - lastProgressSentAt < 200) return;
      lastProgressSentAt = now;
      window.postMessage({
        source: "course-studyspace-page", type: "media-progress",
        currentUrl: media.currentSrc || media.src || "",
        currentTime: Number(media.currentTime) || 0, paused: media.paused, ended: media.ended,
      }, "*");
    };
    media.addEventListener("timeupdate", () => publishProgress());
    media.addEventListener("seeking", () => publishProgress(true));
    media.addEventListener("seeked", () => publishProgress(true));
    media.addEventListener("loadedmetadata", () => publishProgress(true));
    media.addEventListener("pause", () => publishProgress(true));
    media.addEventListener("ended", () => publishProgress(true));
    media.addEventListener("play", () => {
      lastActive = media;
      controlledMedia = media;
      publishProgress(true);
    });
    return media;
  }

  // Flutter may cache the native Audio constructor before application code runs.
  // Prototype hooks still see that player's real media instance, so transcript
  // controls operate on the exact object that drives Flutter's progress and icon.
  const nativePlay = HTMLMediaElement.prototype.play;
  const nativePause = HTMLMediaElement.prototype.pause;
  HTMLMediaElement.prototype.play = function (...args) {
    track(this);
    lastActive = this;
    return nativePlay.apply(this, args);
  };
  HTMLMediaElement.prototype.pause = function (...args) {
    track(this);
    return nativePause.apply(this, args);
  };

  const srcDescriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "src");
  if (srcDescriptor?.get && srcDescriptor?.set) {
    Object.defineProperty(HTMLMediaElement.prototype, "src", {
      configurable: srcDescriptor.configurable,
      enumerable: srcDescriptor.enumerable,
      get: srcDescriptor.get,
      set(value) {
        track(this);
        return srcDescriptor.set.call(this, value);
      },
    });
  }

  const NativeAudio = window.Audio;
  if (NativeAudio) {
    function TrackedAudio(...args) { return track(new NativeAudio(...args)); }
    TrackedAudio.prototype = NativeAudio.prototype;
    Object.setPrototypeOf(TrackedAudio, NativeAudio);
    window.Audio = TrackedAudio;
  }

  const nativeCreateElement = Document.prototype.createElement;
  Document.prototype.createElement = function (name, options) {
    const element = nativeCreateElement.call(this, name, options);
    return /^(audio|video)$/i.test(String(name)) ? track(element) : element;
  };

  function fileName(url) {
    try { return decodeURIComponent(new URL(url).pathname.split("/").pop() || ""); }
    catch (_) { return ""; }
  }

  function matches(media, url) {
    const current = media.currentSrc || media.src || "";
    const expected = fileName(url);
    return current === url || Boolean(expected && decodeURIComponent(current).includes(expected));
  }

  function selectMedia(url, mediaType) {
    const instances = [...mediaInstances];
    const newestFirst = [...instances].reverse();
    const typed = (media) => !mediaType || String(media.tagName).toLowerCase() === mediaType;
    return (url && controlledMedia && typed(controlledMedia) && matches(controlledMedia, url) ? controlledMedia : null)
      || (url && lastActive && typed(lastActive) && matches(lastActive, url) ? lastActive : null)
      || (url ? newestFirst.find((media) => typed(media) && matches(media, url)) : null)
      || (controlledMedia && typed(controlledMedia) ? controlledMedia : null)
      || (lastActive && typed(lastActive) ? lastActive : null)
      || newestFirst.find((media) => !media.paused && typed(media))
      || newestFirst.find((media) => String(media.tagName).toLowerCase() === mediaType)
      || lastActive || newestFirst[0] || null;
  }

  window.addEventListener("message", async (event) => {
    const message = event.data;
    if (event.source !== window || message?.source !== "course-studyspace-content" || message?.type !== "media-command") return;
    const respond = (payload) => window.postMessage({source: "course-studyspace-page", type: "media-result", requestId: message.requestId, ...payload}, "*");
    try {
      if (message.action === "control") {
        const playerPoint = effectiveControlPoint();
        respond({
          ok: true,
          controlPoint: {
            x: window.screenX + playerPoint.x,
            y: window.screenY + playerPoint.y,
          },
        });
        return;
      }
      const justAudio = window.__courseStudyspaceJustAudio;
      if (justAudio && message.mediaType !== "video" && ["play", "pause"].includes(message.action)) {
        if (message.action === "pause") {
          await justAudio.call("pause");
        } else {
          if (Number.isInteger(message.mediaIndex)) {
            await justAudio.call("seek", message.mediaIndex, Math.max(0, Number(message.time) || 0) * 1000);
          }
          await justAudio.call("play");
        }
        await new Promise((resolve) => setTimeout(resolve, 120));
        const actualMedia = selectMedia(message.url, message.mediaType);
        if (!actualMedia) throw new Error("学升播放器执行命令后没有创建媒体实例");
        controlledMedia = actualMedia;
        lastActive = actualMedia;
        respond({
          ok: true, paused: actualMedia.paused, currentTime: actualMedia.currentTime,
          currentUrl: actualMedia.currentSrc || actualMedia.src || "",
          playbackRate: actualMedia.playbackRate || 1,
        });
        return;
      }
      const media = controlledMedia || selectMedia(message.url, message.mediaType);
      if (!media) throw new Error("学升播放器尚未创建");
      if (message.action === "status") {
        const playerPoint = effectiveControlPoint();
        respond({
          ok: true, paused: media.paused, currentTime: media.currentTime,
          currentUrl: media.currentSrc || media.src || "", playbackRate: media.playbackRate || 1,
          controlPoint: {
            x: window.screenX + playerPoint.x,
            y: window.screenY + playerPoint.y,
          },
        });
        return;
      }
      let nativeClick = null;
      if (message.action === "pause") {
        if (!media.paused) nativeClick = effectiveControlPoint();
      } else {
        if (message.url && !matches(media, message.url)) throw new Error("左侧播放器尚未切换到对应媒体块");
        if (Number.isFinite(message.time)) media.currentTime = Math.max(0, message.time);
        if (media.paused) nativeClick = effectiveControlPoint();
        lastActive = media;
        controlledMedia = media;
      }
      if (nativeClick) {
        respond({
          ok: true, paused: media.paused, currentTime: media.currentTime,
          playbackRate: media.playbackRate || 1,
          nativeClick: {
            x: window.screenX + nativeClick.x,
            // Chrome sometimes reports innerHeight === outerHeight for this
            // Flutter page even though the 56px tab/address toolbar is present.
            y: window.screenY + nativeClick.y,
          },
        });
      } else {
        respond({ok: true, paused: media.paused, currentTime: media.currentTime, playbackRate: media.playbackRate || 1});
      }
    } catch (error) {
      respond({ok: false, error: error?.message || String(error)});
    }
  });
})();
