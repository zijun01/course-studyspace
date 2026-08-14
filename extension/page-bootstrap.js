// Run in the extension's isolated world, where chrome.runtime.getURL is always
// available, and explicitly inject the bridge into Songy's page world.
const courseStudyspaceBridgeScript = document.createElement("script");
courseStudyspaceBridgeScript.src = chrome.runtime.getURL("page-media-bridge.js");
courseStudyspaceBridgeScript.async = false;
(document.head || document.documentElement).prepend(courseStudyspaceBridgeScript);
courseStudyspaceBridgeScript.addEventListener("load", () => courseStudyspaceBridgeScript.remove(), {once: true});
