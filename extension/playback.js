(function (global) {
  function fileName(url) {
    try {
      return decodeURIComponent(new URL(url).pathname.split("/").pop() || "");
    } catch (_) {
      return "";
    }
  }

  function mediaMatches(media, sourceUrl) {
    const current = media?.currentSrc || media?.src || "";
    if (!current || !sourceUrl) return false;
    const expectedName = fileName(sourceUrl);
    return current === sourceUrl || Boolean(expectedName && decodeURIComponent(current).includes(expectedName));
  }

  function isVisible(media) {
    return typeof media?.getClientRects !== "function" || media.getClientRects().length > 0;
  }

  function choosePageMedia(mediaElements, source, lastActive = null) {
    const media = Array.from(mediaElements || []);
    if (lastActive && media.includes(lastActive)) return lastActive;
    const matching = media.find((item) => isVisible(item) && mediaMatches(item, source?.url))
      || media.find((item) => mediaMatches(item, source?.url));
    if (matching) return matching;
    const expectedTag = String(source?.mediaType || "").toUpperCase();
    return media.find((item) => isVisible(item) && item.tagName === expectedTag)
      || media.find((item) => item.tagName === expectedTag)
      || media.find(isVisible)
      || null;
  }

  const api = {choosePageMedia, mediaMatches};
  global.CoursePlayback = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
