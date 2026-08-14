chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id) chrome.tabs.sendMessage(tab.id, {type: "TOGGLE_PANEL"}).catch(() => {});
});

function ensureLocalServer() {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage("info.songy.course_launcher", {action: "start"}, (response) => {
      const error = chrome.runtime.lastError;
      if (error) return reject(new Error(error.message));
      if (!response?.ok) return reject(new Error(response?.error || "无法启动本机课程服务"));
      resolve(response);
    });
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "DNR_DEBUG") {
    Promise.all([
      chrome.declarativeNetRequest.getEnabledRulesets(),
      chrome.declarativeNetRequest.testMatchOutcome({
        url: "https://webapp.songy.info/main.dart.js",
        initiator: "https://webapp.songy.info",
        method: "get",
        type: "script",
      }),
    ])
      .then(([enabledRulesets, outcome]) => sendResponse({ok: true, enabledRulesets, outcome}))
      .catch((error) => sendResponse({ok: false, error: error.message}));
    return true;
  }
  if (message?.type === "ENSURE_LOCAL_SERVER") {
    ensureLocalServer()
      .then((response) => sendResponse(response))
      .catch((error) => sendResponse({ok: false, error: error.message}));
    return true;
  }
  if (message?.type !== "CLICK_PLAYER_CONTROL") return false;
  chrome.runtime.sendNativeMessage("info.songy.course_launcher", {
    action: "click_player", x: message.x, y: message.y,
  }, (response) => {
    const error = chrome.runtime.lastError;
    sendResponse(error ? {ok: false, error: error.message} : response);
  });
  return true;
});
